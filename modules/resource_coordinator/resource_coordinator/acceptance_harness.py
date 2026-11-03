"""
Supervised Acceptance Test Harness for Miner / Local LLM Inference Coordination.

Executes and benchmarks the canonical test sequence:
1. Idle baseline and read-only model discovery (/api/v0/models -> /v1/models)
2. Single request stop-before-forward and 10.0s cooldown resumption (T01)
3. Cooldown interruption and cancellation / debounce (T02)
4. Concurrent overlapping request arbitration (T03)
5. Streaming SSE verification with [DONE] terminal detection (T04)
6. Error handling, truncated streams, and restart inhibition latching (T05, mock-only)
7. Guaranteed supervised cleanup in `finally` with miner & descendant stop verification

Repeatable, Evidence-Preserving Layout:
Each execution runs in an isolated, collision-resistant directory:
    <work_dir>/runs/<unique-run-id>/
        manifest.json
        journal_t01.json
        journal_t02.json
        ...
        acceptance_report.json
A deterministic pointer `<work_dir>/latest_run.json` always records the most recent run.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence
import uuid

import httpx
import psutil
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from resource_coordinator.adapters.miners.manifest import MinerManifest, redact_miner_args
from resource_coordinator.config import (
    CoordinatorConfig,
    CoordinatorSystem,
    PolicyConfig,
    ProcessConfig,
    ServiceConfig,
    build_system,
    load_config,
)
from resource_coordinator.core.durable_state import StateCodec
from resource_coordinator.core.lock import SingleInstanceLock, SingleInstanceLockError
from resource_coordinator.core.processes import (
    ProcessInfo,
    ProcessLifecycleOwner,
    ProcessState,
    WindowsProcessBackend,
)
from resource_coordinator.core.service import CoordinatorService, ServiceState
from resource_coordinator.monitors.gpu import GpuDeviceMetrics, NvidiaGpuMonitor

logger = logging.getLogger(__name__)

KNOWN_MINER_EXECUTABLES = {
    "krig-miner.exe",
    "srbminer-multi.exe",
    "srbminer.exe",
    "xmrig.exe",
    "lolminer.exe",
    "nbminer.exe",
    "t-rex.exe",
    "gminer.exe",
}


class ConfigurationMismatchError(ValueError):
    """Raised when an acceptance runner configuration does not match the preflight/base configuration."""


def get_git_commit(repo_dir: Optional[str | Path] = None) -> str:
    """Read the current Git commit SHA if git is available."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir) if repo_dir else None,
            capture_output=True,
            text=True,
            timeout=3.0,
            check=True,
        )
        return proc.stdout.strip()
    except Exception:
        return ""


def redact_config_dict(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep copy of a configuration dictionary with sensitive credentials redacted."""
    redacted = copy.deepcopy(config_dict)
    processes = redacted.get("processes", {})
    if isinstance(processes, dict):
        for proc in processes.values():
            if isinstance(proc, dict) and "arguments" in proc and isinstance(proc["arguments"], list):
                proc["arguments"] = redact_miner_args(proc["arguments"])
    return redacted


def compute_config_fingerprint(config_dict: Dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 fingerprint of a configuration dictionary."""
    redacted = redact_config_dict(config_dict)
    data = json.dumps(redacted, sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def validate_acceptance_config_equivalence(
    config: CoordinatorConfig,
    proc_config: ProcessConfig,
    target_process_name: Optional[str] = None,
) -> None:
    """
    Ensure the exact process configuration executed by the runner is identical
    to the configuration verified during preflight.
    """
    proc_name = target_process_name or proc_config.name
    if proc_name not in config.processes:
        raise ConfigurationMismatchError(
            f"Process '{proc_name}' from runner is not present in base configuration processes: {list(config.processes)}"
        )
    base_proc = config.processes[proc_name]

    mismatches: List[str] = []

    # 1. Executable normalized path
    base_exe = os.path.normcase(os.path.realpath(base_proc.executable)) if base_proc.executable else ""
    run_exe = os.path.normcase(os.path.realpath(proc_config.executable)) if proc_config.executable else ""
    if base_exe != run_exe:
        mismatches.append(f"executable mismatch: base={base_proc.executable!r} vs runner={proc_config.executable!r}")

    # 2. Working directory normalized path
    base_cwd = os.path.normcase(os.path.realpath(base_proc.working_directory)) if base_proc.working_directory else ""
    run_cwd = os.path.normcase(os.path.realpath(proc_config.working_directory)) if proc_config.working_directory else ""
    if base_cwd != run_cwd:
        mismatches.append(f"working_directory mismatch: base={base_proc.working_directory!r} vs runner={proc_config.working_directory!r}")

    # 3. Arguments
    if list(base_proc.arguments) != list(proc_config.arguments):
        mismatches.append(f"arguments mismatch: base={base_proc.arguments} vs runner={proc_config.arguments}")

    # 4. Backend
    if base_proc.backend != proc_config.backend:
        mismatches.append(f"backend mismatch: base={base_proc.backend} vs runner={proc_config.backend}")

    # 5. Ownership & external adoption permissions
    if base_proc.adopt_external != proc_config.adopt_external:
        mismatches.append(f"adopt_external mismatch: base={base_proc.adopt_external} vs runner={proc_config.adopt_external}")
    if base_proc.allow_external_stop != proc_config.allow_external_stop:
        mismatches.append(f"allow_external_stop mismatch: base={base_proc.allow_external_stop} vs runner={proc_config.allow_external_stop}")
    if base_proc.allow_external_restart != proc_config.allow_external_restart:
        mismatches.append(f"allow_external_restart mismatch: base={base_proc.allow_external_restart} vs runner={proc_config.allow_external_restart}")

    if mismatches:
        raise ConfigurationMismatchError(
            f"Acceptance configuration mismatch between preflight config and runner execution: {'; '.join(mismatches)}"
        )


async def discover_live_model(client: httpx.AsyncClient) -> Dict[str, Any]:
    """
    Discover an active, loaded LLM/VLM model via read-only LM Studio endpoints.

    1. Queries `GET /api/v0/models` first. If supported (200 OK), selects a model
       with `state == "loaded"` and `type not in ("embeddings", "embedding")`.
       If `/api/v0/models` returns 200 OK with models but none are in `state == "loaded"`,
       fails closed rather than risking an unintended automatic model load in LM Studio.
    2. If `/api/v0/models` returns 404 (e.g. standard OpenAI-compatible mock server),
       falls back to `GET /v1/models` and selects the first non-embedding model.
    """
    try:
        resp_v0 = await client.get("/api/v0/models")
    except Exception as exc:
        raise RuntimeError(f"Failed to query upstream /api/v0/models: {exc}") from exc

    if resp_v0.status_code == 200:
        payload = resp_v0.json()
        models = payload.get("data", []) if isinstance(payload, dict) else []
        loaded_candidates = [
            m
            for m in models
            if isinstance(m, dict)
            and m.get("id")
            and m.get("state") == "loaded"
            and str(m.get("type", "llm")).lower() not in {"embeddings", "embedding"}
        ]
        if loaded_candidates:
            chosen = loaded_candidates[0]
            return {
                "model_id": str(chosen["id"]),
                "source": "/api/v0/models",
                "state": str(chosen.get("state", "loaded")),
                "type": str(chosen.get("type", "llm")),
                "loaded_context_length": chosen.get("loaded_context_length"),
                "max_context_length": chosen.get("max_context_length"),
            }
        raise RuntimeError(
            "No loaded LLM/VLM model found in LM Studio (/api/v0/models returned no model with state='loaded'; "
            "refusing to send inference request that could trigger an unintended model load)"
        )

    if resp_v0.status_code != 404:
        raise RuntimeError(f"Unexpected status {resp_v0.status_code} from /api/v0/models")

    try:
        resp_v1 = await client.get("/v1/models")
    except Exception as exc:
        raise RuntimeError(f"Failed to query upstream /v1/models: {exc}") from exc

    if resp_v1.status_code != 200:
        raise RuntimeError(f"Upstream /v1/models returned HTTP {resp_v1.status_code}")

    payload_v1 = resp_v1.json()
    models_v1 = payload_v1.get("data", []) if isinstance(payload_v1, dict) else []
    v1_candidates = [
        m
        for m in models_v1
        if isinstance(m, dict)
        and m.get("id")
        and not str(m.get("id", "")).lower().startswith("text-embedding")
        and str(m.get("type", "llm")).lower() not in {"embeddings", "embedding"}
    ]
    if not v1_candidates:
        raise RuntimeError("No usable LLM/VLM model found in /v1/models response")

    chosen_v1 = v1_candidates[0]
    return {
        "model_id": str(chosen_v1["id"]),
        "source": "/v1/models",
        "state": "assumed_loaded",
        "type": str(chosen_v1.get("type", "llm")),
        "loaded_context_length": chosen_v1.get("loaded_context_length"),
        "max_context_length": chosen_v1.get("max_context_length"),
    }


def scan_external_miners(
    configured_exe_names: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    """Inspect OS process table for any running miner processes."""
    all_names = set(KNOWN_MINER_EXECUTABLES)
    if configured_exe_names:
        all_names.update(configured_exe_names)
    external_miners: List[Dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            pname = (proc.info.get("name") or "").strip()
            pexe = (proc.info.get("exe") or "").strip()
            if pname.casefold() in all_names or (pexe and Path(pexe).name.casefold() in all_names):
                external_miners.append(
                    {
                        "pid": proc.info.get("pid"),
                        "name": pname,
                        "exe": pexe,
                    }
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return external_miners


async def run_live_acceptance_preflight(
    config: CoordinatorConfig | str | Path,
    http_client: Optional[httpx.AsyncClient] = None,
    lock_path: Optional[str | Path] = None,
    gpu_metrics_override: Optional[List[GpuDeviceMetrics]] = None,
    external_miners_override: Optional[List[Dict[str, Any]]] = None,
    min_free_vram_mb: float = 1024.0,
) -> Dict[str, Any]:
    """
    Strictly read-only preflight check for supervised live hardware acceptance.

    Does NOT launch miners, alter GPU clocks/power limits, or interrupt active services.
    Checks:
    1. External miner processes in OS process table (`psutil.process_iter`).
    2. Coordinator `SingleInstanceLock` availability.
    3. `CoordinatorService.preflight_check()` and process ownership flags (`adopt_external == False`).
    4. LM Studio upstream reachability and currently loaded LLM/VLM model (`/api/v0/models`).
    5. GPU VRAM headroom (`free_mb >= min_free_vram_mb`).
    """
    if isinstance(config, (str, Path)):
        resolved_config = load_config(config)
    else:
        resolved_config = config

    blocking_reasons: List[str] = []
    warnings: List[str] = []

    # 1. Inspect OS process table for any running miner processes
    if external_miners_override is not None:
        external_miners = list(external_miners_override)
    else:
        configured_exe_names = {
            Path(p.executable).name.casefold() for p in resolved_config.processes.values() if p.executable
        }
        external_miners = scan_external_miners(configured_exe_names)

    if external_miners:
        blocking_reasons.append(
            f"External miner process(es) currently running: {external_miners}. "
            "Stop external miners manually before starting supervised acceptance."
        )

    # 2. Probe SingleInstanceLock availability without holding it
    resolved_lock_path = lock_path
    if not resolved_lock_path and getattr(resolved_config.service, "state_persistence_path", ""):
        resolved_lock_path = Path(resolved_config.service.state_persistence_path).with_suffix(".lock")
    lock_available = True
    if resolved_lock_path:
        probe_lock = SingleInstanceLock(resolved_lock_path)
        if probe_lock.acquire():
            probe_lock.release()
        else:
            lock_available = False
            blocking_reasons.append(
                f"Coordinator SingleInstanceLock at '{resolved_lock_path}' is already held by another process."
            )

    # 3. Validate coordinator configuration and ownership flags
    system = build_system(resolved_config, use_fake_processes=False)
    try:
        service = CoordinatorService(system=system)
        config_passed, config_messages = service.preflight_check()
    finally:
        await system.gateway.close()
    if not config_passed:
        for msg in config_messages:
            if msg.startswith("ERROR"):
                blocking_reasons.append(msg)

    for pname, pcfg in resolved_config.processes.items():
        if pcfg.adopt_external or pcfg.allow_external_stop or pcfg.allow_external_restart:
            blocking_reasons.append(
                f"Process '{pname}' enables external adoption/stop/restart, which is forbidden for supervised acceptance."
            )
        gpu_mutating_flags = {"--gpu-plimit", "--gpu-cclock", "--gpu-coffset", "--gpu-mclock"}
        present_mutating = [arg for arg in pcfg.arguments if arg in gpu_mutating_flags]
        if present_mutating:
            warnings.append(
                f"Process '{pname}' arguments include GPU clock/power flags {present_mutating}; "
                "verify explicit operator authorization before live execution."
            )

    # 4. Read-only LM Studio loaded model discovery
    loaded_model: Optional[Dict[str, Any]] = None
    close_client = False
    client = http_client
    if client is None:
        client = httpx.AsyncClient(base_url=resolved_config.service.upstream_url, timeout=5.0)
        close_client = True
    try:
        loaded_model = await discover_live_model(client)
    except Exception as exc:
        blocking_reasons.append(f"LM Studio upstream model discovery failed: {exc}")
    finally:
        if close_client and client is not None:
            await client.aclose()

    # 5. Read-only GPU telemetry & VRAM headroom assessment
    gpus = gpu_metrics_override if gpu_metrics_override is not None else await NvidiaGpuMonitor().get_metrics()
    vram_headroom: Optional[Dict[str, Any]] = None
    if gpus:
        primary = gpus[0]
        free_mb = max(0.0, primary.memory_total_mb - primary.memory_used_mb)
        vram_headroom = {
            "device_id": primary.device_id,
            "memory_used_mb": primary.memory_used_mb,
            "memory_total_mb": primary.memory_total_mb,
            "free_mb": free_mb,
            "min_required_free_mb": min_free_vram_mb,
            "sufficient": free_mb >= min_free_vram_mb,
        }
        if free_mb < min_free_vram_mb:
            blocking_reasons.append(
                f"Insufficient free GPU VRAM for safe concurrent resident LLM + KRig launch: "
                f"{free_mb:.0f} MiB free < {min_free_vram_mb:.0f} MiB minimum threshold "
                f"({primary.memory_used_mb:.0f}/{primary.memory_total_mb:.0f} MiB used). "
                "Reduce LM Studio loaded_context_length or KV cache allocation before launching KRig."
            )
    else:
        warnings.append("No NVIDIA GPU metrics returned by nvidia-smi during preflight.")

    return {
        "timestamp": time.time(),
        "ready_for_supervised_live": len(blocking_reasons) == 0,
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "external_miners": external_miners,
        "lock_available": lock_available,
        "config_preflight_passed": config_passed,
        "config_messages": config_messages,
        "loaded_model": loaded_model,
        "vram_headroom": vram_headroom,
        "gpus": [
            {
                "device_id": g.device_id,
                "utilization_pct": g.utilization_pct,
                "memory_used_mb": g.memory_used_mb,
                "memory_total_mb": g.memory_total_mb,
                "power_draw_w": g.power_draw_w,
            }
            for g in gpus
        ],
    }


@dataclass
class TrialEvidence:
    trial_id: str
    name: str
    status: str = "PENDING"  # PASS, FAIL, NOT_RUN
    start_monotonic: float = 0.0
    end_monotonic: float = 0.0
    duration_seconds: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[str] = field(default_factory=list)
    error: Optional[str] = None
    process_contract_verified: bool = False
    inference_arbitration_contract_verified: bool = False
    mining_activity_contract_verified: bool = False
    initial_miner_uptime_before_inference_seconds: Optional[float] = None
    initial_mining_activity_verified: bool = False
    initial_hashrate: Optional[str] = None
    initial_pool_connected: Optional[bool] = None
    restart_mining_activity_verified: bool = False
    restart_time_to_hashing_seconds: Optional[float] = None
    gpu_idle_baseline: Optional[Dict[str, Any]] = None
    gpu_samples: List[Dict[str, Any]] = field(default_factory=list)
    peak_gpu_utilization_pct: Optional[float] = None
    peak_gpu_power_w: Optional[float] = None
    mining_verification_method: Optional[str] = None
    initial_generation: Optional[Dict[str, Any]] = None
    restart_generation: Optional[Dict[str, Any]] = None


import re

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

POOL_CONNECTED_RE = re.compile(
    r"(?:connected\s*(?:to|:)|pool connected\s*(?:to|:)?)[:\s]*(stratum(?:\+ssl|\+tcp)?://[^\s\"']+)",
    re.IGNORECASE,
)
POOL_GENERIC_CONNECTED_RE = re.compile(
    r"(?:subscribed to pool|authorized worker|subscription successful)",
    re.IGNORECASE,
)
STRATUM_JOB_RE = re.compile(
    r"stratum:\s*new job|new job\s+[0-9a-f_]+|subscribed to pool jobs",
    re.IGNORECASE,
)
HASHRATE_RE = re.compile(
    r"(?:Total|Speed|Hashrate)[:\s]+([\d.]+)\s*([KMGTPE]?H)/s",
    re.IGNORECASE,
)

UNIT_SCALE = {
    "H": 1e-12,
    "KH": 1e-9,
    "MH": 1e-6,
    "GH": 1e-3,
    "TH": 1.0,
    "PH": 1e3,
    "EH": 1e6,
}


def parse_miner_stdout_log(log_path: Path | str, start_offset: int = 0) -> Dict[str, Any]:
    """Parse miner stdout log file for pool connectivity, jobs, and reported hashrate starting at start_offset."""
    path = Path(log_path)
    if not path.is_file():
        return {
            "exists": False,
            "pool_connected": False,
            "connected_pool_url": None,
            "pool_job_received": False,
            "hashrate": None,
            "hashrate_ths": None,
            "start_offset": start_offset,
            "end_offset": start_offset,
            "line_count": 0,
        }
    try:
        with path.open("rb") as f:
            if start_offset > 0:
                f.seek(max(0, start_offset))
            raw_bytes = f.read()
            end_offset = f.tell()
        content = raw_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Error reading miner stdout log '%s': %s", path, exc)
        return {
            "exists": True,
            "pool_connected": False,
            "connected_pool_url": None,
            "pool_job_received": False,
            "hashrate": None,
            "hashrate_ths": None,
            "start_offset": start_offset,
            "end_offset": start_offset,
            "error": str(exc),
            "line_count": 0,
        }

    clean_content = ANSI_ESCAPE_RE.sub("", content)
    lines = clean_content.splitlines()
    pool_connected = False
    connected_pool_url: Optional[str] = None
    pool_job_received = False
    hashrate: Optional[str] = None
    hashrate_ths: Optional[float] = None

    for line in lines:
        m_conn = POOL_CONNECTED_RE.search(line)
        if m_conn:
            pool_connected = True
            connected_pool_url = m_conn.group(1).strip()
        elif POOL_GENERIC_CONNECTED_RE.search(line):
            pool_connected = True

        if STRATUM_JOB_RE.search(line):
            pool_job_received = True

        m_hash = HASHRATE_RE.search(line)
        if m_hash:
            val_str = m_hash.group(1)
            unit_str = m_hash.group(2).upper()
            hashrate = f"{val_str} {unit_str}/s"
            try:
                scale = UNIT_SCALE.get(unit_str, 1.0)
                hashrate_ths = float(val_str) * scale
            except ValueError:
                pass

    return {
        "exists": True,
        "pool_connected": pool_connected,
        "connected_pool_url": connected_pool_url,
        "pool_job_received": pool_job_received,
        "hashrate": hashrate,
        "hashrate_ths": hashrate_ths,
        "start_offset": start_offset,
        "end_offset": end_offset,
        "line_count": len(lines),
    }


@dataclass
class PhaseGpuEvidence:
    phase_name: str
    pid: Optional[int] = None
    create_time: Optional[float] = None
    baseline: Optional[Dict[str, Any]] = None
    samples: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def peak_power_w(self) -> Optional[float]:
        if not self.samples:
            return None
        return max(s.get("power_draw_w", 0.0) for s in self.samples)

    @property
    def peak_utilization_pct(self) -> Optional[float]:
        if not self.samples:
            return None
        return max(s.get("utilization_pct", 0.0) for s in self.samples)


class GpuActivitySampler:
    """Samples and evaluates GPU compute and power metrics with per-phase isolation."""

    def __init__(
        self,
        monitor: Optional[Any] = None,
        min_consecutive: int = 2,
        min_power_delta_w: float = 35.0,
        min_util_delta_pct: float = 15.0,
    ) -> None:
        self.monitor = monitor or NvidiaGpuMonitor()
        self.min_consecutive = min_consecutive
        self.min_power_delta_w = min_power_delta_w
        self.min_util_delta_pct = min_util_delta_pct
        self.baseline: Optional[Dict[str, Any]] = None
        self.samples: List[Dict[str, Any]] = []
        self.phase_evidence: Dict[str, PhaseGpuEvidence] = {}
        self.current_phase: Optional[PhaseGpuEvidence] = None

    def start_phase(
        self,
        phase_name: str,
        pid: Optional[int] = None,
        create_time: Optional[float] = None,
    ) -> PhaseGpuEvidence:
        phase = PhaseGpuEvidence(
            phase_name=phase_name,
            pid=pid,
            create_time=create_time,
            baseline=dict(self.baseline) if self.baseline else None,
        )
        self.phase_evidence[phase_name] = phase
        self.current_phase = phase
        return phase

    async def sample_baseline(self) -> Optional[Dict[str, Any]]:
        metrics = await self.monitor.get_metrics()
        if metrics:
            m = metrics[0]
            self.baseline = {
                "device_id": m.device_id,
                "power_draw_w": m.power_draw_w,
                "utilization_pct": m.utilization_pct,
                "memory_used_mb": m.memory_used_mb,
                "timestamp": time.time(),
                "monotonic": time.monotonic(),
            }
            if self.current_phase and not self.current_phase.baseline:
                self.current_phase.baseline = dict(self.baseline)
        return self.baseline

    async def sample(self) -> Optional[Dict[str, Any]]:
        metrics = await self.monitor.get_metrics()
        if not metrics:
            return None
        m = metrics[0]
        s = {
            "device_id": m.device_id,
            "power_draw_w": m.power_draw_w,
            "utilization_pct": m.utilization_pct,
            "memory_used_mb": m.memory_used_mb,
            "timestamp": time.time(),
            "monotonic": time.monotonic(),
        }
        self.samples.append(s)
        if self.current_phase is not None:
            self.current_phase.samples.append(s)
        return s

    def is_activity_sustained(self, phase_name: Optional[str] = None) -> bool:
        target = self.phase_evidence.get(phase_name) if phase_name else self.current_phase
        target_samples = target.samples if target is not None else self.samples
        target_baseline = target.baseline if (target and target.baseline) else self.baseline

        if not target_baseline or len(target_samples) < self.min_consecutive:
            return False
        base_power = target_baseline.get("power_draw_w", 0.0)
        base_util = target_baseline.get("utilization_pct", 0.0)
        recent = target_samples[-self.min_consecutive:]
        power_elevated = all(s.get("power_draw_w", 0.0) >= base_power + self.min_power_delta_w for s in recent)
        util_elevated = all(s.get("utilization_pct", 0.0) >= base_util + self.min_util_delta_pct for s in recent)
        return power_elevated or util_elevated

    @property
    def peak_power_w(self) -> Optional[float]:
        if not self.samples:
            return None
        return max(s.get("power_draw_w", 0.0) for s in self.samples)

    @property
    def peak_utilization_pct(self) -> Optional[float]:
        if not self.samples:
            return None
        return max(s.get("utilization_pct", 0.0) for s in self.samples)


@dataclass
class AcceptanceReport:
    timestamp: float = field(default_factory=time.time)
    iso_timestamp: str = ""
    run_id: str = ""
    run_dir: str = ""
    git_commit: str = ""
    configuration_fingerprint: str = ""
    effective_configuration: Dict[str, Any] = field(default_factory=dict)
    mode: str = "simulated"  # "simulated", "disposable_helper", "live"
    process_backend: str = "fake"  # "fake", "windows_cscript", "windows_miner"
    upstream_type: str = "mock"  # "mock", "live_lmstudio"
    verification_level: str = "unit_simulation"
    run_verification_level: str = "unit_simulation"
    aggregate_verification_level: Optional[str] = None
    aggregate_trials_verified: List[str] = field(default_factory=list)
    aggregate_status: Optional[str] = None
    trials: List[TrialEvidence] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "iso_timestamp": self.iso_timestamp,
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "git_commit": self.git_commit,
            "configuration_fingerprint": self.configuration_fingerprint,
            "effective_configuration": self.effective_configuration,
            "mode": self.mode,
            "process_backend": self.process_backend,
            "upstream_type": self.upstream_type,
            "verification_level": self.verification_level,
            "run_verification_level": self.run_verification_level,
            "aggregate_verification_level": self.aggregate_verification_level,
            "aggregate_trials_verified": self.aggregate_trials_verified,
            "aggregate_status": self.aggregate_status,
            "trials": [asdict(t) for t in self.trials],
            "summary": self.summary,
        }

    def save(self, output_path: str | Path) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


class AcceptanceHarness:
    """
    Automated execution runner for the supervised coordination test sequence.
    """

    def __init__(
        self,
        mode: str = "simulated",
        config: Optional[CoordinatorConfig | str | Path] = None,
        cooldown_seconds: Optional[float] = None,
        allow_live_lmstudio: bool = False,
        allow_real_miner: bool = False,
        lmstudio_url: Optional[str] = None,
        miner_process_config: Optional[ProcessConfig] = None,
        work_dir: Optional[str | Path] = None,
        lock_path: Optional[str | Path] = None,
        trials_to_run: Optional[List[str]] = None,
        require_mining_activity: Optional[bool] = None,
        mining_warmup_timeout_seconds: float = 60.0,
        mining_settle_seconds: float = 3.0,
        gpu_monitor: Optional[Any] = None,
        _allow_short_cooldown_for_test: bool = False,
        _upstream_app_override_for_test: Any = None,
        _external_miners_override_for_test: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if mode not in {"simulated", "disposable_helper", "live"}:
            raise ValueError(f"Unsupported acceptance harness mode: {mode!r}")

        self.mode = mode
        self.allow_live_lmstudio = allow_live_lmstudio
        self.allow_real_miner = allow_real_miner
        self.require_mining_activity = (
            require_mining_activity
            if require_mining_activity is not None
            else (
                mode == "live"
                and _upstream_app_override_for_test is None
                and not _allow_short_cooldown_for_test
            )
        )
        self.mining_warmup_timeout_seconds = float(mining_warmup_timeout_seconds)
        self.mining_settle_seconds = float(mining_settle_seconds)
        self.gpu_monitor = gpu_monitor
        self._allow_short_cooldown_for_test = _allow_short_cooldown_for_test
        self._upstream_app_override_for_test = _upstream_app_override_for_test
        self._external_miners_override_for_test = _external_miners_override_for_test
        self.trials_to_run = [t.strip().upper() for t in trials_to_run] if trials_to_run else None

        # Resolve base configuration
        self.base_config: Optional[CoordinatorConfig] = None
        if config is not None:
            if isinstance(config, (str, Path)):
                self.base_config = load_config(config)
            else:
                self.base_config = config

        # Base working directory setup
        if work_dir is not None:
            self._base_work_dir = Path(work_dir)
            self._base_work_dir.mkdir(parents=True, exist_ok=True)
            self._temp_dir_obj = None
        else:
            self._temp_dir_obj = tempfile.TemporaryDirectory(prefix="rc_acceptance_")
            self._base_work_dir = Path(self._temp_dir_obj.name)

        # Resolve miner process configuration and validate equivalence
        resolved_proc_cfg = miner_process_config
        if self.base_config is not None:
            if resolved_proc_cfg is None:
                # Discover process with inference policy or take the first process
                target_name = None
                for p in self.base_config.policies:
                    if p.trigger_event == "lmstudio.inference_requested" and p.target_process:
                        target_name = p.target_process
                        break
                if not target_name and self.base_config.processes:
                    target_name = next(iter(self.base_config.processes))
                if target_name and target_name in self.base_config.processes:
                    resolved_proc_cfg = self.base_config.processes[target_name]
            else:
                validate_acceptance_config_equivalence(self.base_config, resolved_proc_cfg)

        self.miner_process_config = resolved_proc_cfg

        # Resolve LM Studio URL
        if lmstudio_url is not None:
            self.lmstudio_url = lmstudio_url
        elif self.base_config is not None and self.base_config.service.upstream_url:
            self.lmstudio_url = self.base_config.service.upstream_url
        else:
            self.lmstudio_url = "http://127.0.0.1:1234"

        # Resolve lock path
        if lock_path is not None:
            self.lock_path = Path(lock_path)
        elif self.base_config is not None and getattr(self.base_config.service, "state_persistence_path", ""):
            self.lock_path = Path(self.base_config.service.state_persistence_path).with_suffix(".lock")
        else:
            self.lock_path = self._base_work_dir / "coordinator.lock"

        # Resolve cooldown
        if cooldown_seconds is not None:
            effective_cooldown = float(cooldown_seconds)
        elif self.base_config is not None and self.base_config.policies:
            effective_cooldown = float(self.base_config.policies[0].cooldown_seconds)
        elif mode == "live":
            effective_cooldown = 10.0
        elif mode == "disposable_helper":
            effective_cooldown = 0.2
        else:
            effective_cooldown = 0.1

        if mode == "live":
            if not allow_live_lmstudio or not allow_real_miner:
                raise ValueError(
                    "Live acceptance mode requires both allow_live_lmstudio=True and allow_real_miner=True"
                )
            if effective_cooldown < 10.0 and not _allow_short_cooldown_for_test:
                raise ValueError("Live acceptance mode requires cooldown_seconds >= 10.0 seconds")
            process_backend = "windows_miner"
            upstream_type = "live_lmstudio"
            verification_level = "pending_live_verification"
        elif mode == "disposable_helper":
            if os.name != "nt":
                raise RuntimeError("Disposable helper acceptance mode requires Windows (os.name == 'nt')")
            process_backend = "windows_cscript"
            upstream_type = "mock"
            verification_level = "os_process_contract"
        else:
            process_backend = "fake"
            upstream_type = "mock"
            verification_level = "unit_simulation"

        self.cooldown_seconds = effective_cooldown
        self.report = AcceptanceReport(
            mode=mode,
            process_backend=process_backend,
            upstream_type=upstream_type,
            verification_level=verification_level,
            run_verification_level=verification_level,
        )

        self.current_run_id: str = ""
        self.current_run_dir: Optional[Path] = None
        self.host_lock: Optional[SingleInstanceLock] = None

    @classmethod
    def from_config(
        cls,
        config: CoordinatorConfig | str | Path,
        mode: str = "simulated",
        work_dir: Optional[str | Path] = None,
        allow_live_lmstudio: bool = False,
        allow_real_miner: bool = False,
        lock_path: Optional[str | Path] = None,
        trials_to_run: Optional[List[str]] = None,
        require_mining_activity: Optional[bool] = None,
        mining_warmup_timeout_seconds: float = 60.0,
        mining_settle_seconds: float = 3.0,
        gpu_monitor: Optional[Any] = None,
        _allow_short_cooldown_for_test: bool = False,
        _upstream_app_override_for_test: Any = None,
    ) -> AcceptanceHarness:
        """Construct AcceptanceHarness directly from a verified CoordinatorConfig or path."""
        return cls(
            mode=mode,
            config=config,
            allow_live_lmstudio=allow_live_lmstudio,
            allow_real_miner=allow_real_miner,
            work_dir=work_dir,
            lock_path=lock_path,
            trials_to_run=trials_to_run,
            require_mining_activity=require_mining_activity,
            mining_warmup_timeout_seconds=mining_warmup_timeout_seconds,
            mining_settle_seconds=mining_settle_seconds,
            gpu_monitor=gpu_monitor,
            _allow_short_cooldown_for_test=_allow_short_cooldown_for_test,
            _upstream_app_override_for_test=_upstream_app_override_for_test,
        )

    def _generate_effective_config_dict(self) -> Dict[str, Any]:
        """Produce the exact dictionary representation of the effective configuration."""
        if self.base_config is not None:
            raw = {
                "version": self.base_config.version,
                "service": self.base_config.service.__dict__,
                "resources": self.base_config.resources,
                "processes": {k: v.__dict__ for k, v in self.base_config.processes.items()},
                "policies": [p.__dict__ for p in self.base_config.policies],
            }
        else:
            proc_dict = self.miner_process_config.__dict__ if self.miner_process_config else {}
            raw = {
                "version": "1.0",
                "service": {
                    "listen_host": "127.0.0.1",
                    "listen_port": 1235,
                    "upstream_url": self.lmstudio_url,
                },
                "resources": {"gpu.inference": {"cooldown_seconds": self.cooldown_seconds}},
                "processes": {proc_dict.get("name", "miner"): proc_dict},
                "policies": [
                    {
                        "name": "acceptance-stop",
                        "trigger_event": "lmstudio.inference_requested",
                        "target_process": proc_dict.get("name", "miner"),
                        "stop_process": True,
                        "restart_process": True,
                        "cooldown_seconds": self.cooldown_seconds,
                    }
                ],
            }
        return redact_config_dict(raw)

    def _ensure_run_dir(self) -> Path:
        """Ensure per-run directory and report run metadata are initialized."""
        if self.current_run_dir is None:
            now_dt = datetime.now(timezone.utc)
            self.current_run_id = f"{now_dt.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            runs_parent = self._base_work_dir / "runs"
            runs_parent.mkdir(parents=True, exist_ok=True)
            self.current_run_dir = runs_parent / self.current_run_id
            self.current_run_dir.mkdir(parents=True, exist_ok=False)

            self.report.run_id = self.current_run_id
            self.report.run_dir = str(self.current_run_dir)
            self.report.iso_timestamp = now_dt.isoformat()
            self.report.git_commit = get_git_commit(self._base_work_dir)
            effective_cfg = self._generate_effective_config_dict()
            self.report.effective_configuration = effective_cfg
            self.report.configuration_fingerprint = compute_config_fingerprint(effective_cfg)
        return self.current_run_dir

    def _scan_aggregate_evidence(self) -> Dict[str, Any]:
        """Scan historical run reports to determine aggregate trial coverage and verification level."""
        runs_parent = self._base_work_dir / "runs"
        passed_trials: set[str] = {t.trial_id for t in self.report.trials if t.status == "PASS"}
        if runs_parent.is_dir():
            for child in runs_parent.iterdir():
                if not child.is_dir() or child.name == self.current_run_id:
                    continue
                rep_file = child / "acceptance_report.json"
                if rep_file.is_file():
                    try:
                        data = json.loads(rep_file.read_text(encoding="utf-8"))
                        if data.get("mode") == self.mode or (self.mode == "live" and data.get("mode") == "live"):
                            for tr in data.get("trials", []):
                                if tr.get("status") == "PASS":
                                    passed_trials.add(tr.get("trial_id"))
                    except Exception:
                        pass

        all_live_trials = {"T01", "T02", "T03", "T04"}
        all_passed_live = all_live_trials.issubset(passed_trials)
        is_test_override = (
            self._allow_short_cooldown_for_test or self._upstream_app_override_for_test is not None
        )
        if self.mode == "live":
            if is_test_override:
                agg_level = "live_contract_rehearsal"
                agg_status = "COMPLETE" if all_passed_live else "PARTIAL"
            else:
                agg_level = "live_hardware" if all_passed_live else self.report.run_verification_level
                agg_status = "COMPLETE" if all_passed_live else "PARTIAL"
        else:
            agg_level = self.report.run_verification_level
            agg_status = "COMPLETE" if len(passed_trials) >= len(self.report.trials) else "PARTIAL"

        return {
            "aggregate_trials_verified": sorted(list(passed_trials)),
            "aggregate_verification_level": agg_level,
            "aggregate_status": agg_status,
        }

    async def run_all(self, output_file: Optional[str | Path] = None) -> AcceptanceReport:
        """Run all applicable test sequence trials and return the structured acceptance report."""
        logger.info("Starting Acceptance Test Sequence in mode: %s", self.mode)
        if self.mode == "live" and (
            self.miner_process_config is None or self.miner_process_config.backend != "windows"
        ):
            raise RuntimeError(
                "Live acceptance mode requires an explicit Windows miner_process_config; "
                "refusing to fall back to simulated backend"
            )

        # 1. Initialize collision-resistant run directory
        self._ensure_run_dir()
        assert self.current_run_dir is not None

        # Write manifest.json inside run directory
        manifest_data = {
            "run_id": self.current_run_id,
            "timestamp": time.time(),
            "iso_timestamp": self.report.iso_timestamp,
            "git_commit": self.report.git_commit,
            "mode": self.mode,
            "process_backend": self.report.process_backend,
            "upstream_type": self.report.upstream_type,
            "effective_configuration": self.report.effective_configuration,
            "configuration_fingerprint": self.report.configuration_fingerprint,
            "lock_path": str(self.lock_path),
            "trials_requested": self.trials_to_run,
        }
        (self.current_run_dir / "manifest.json").write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        # Update latest_run.json pointer
        latest_pointer_data = {
            "latest_run_id": self.current_run_id,
            "run_dir": str(self.current_run_dir),
            "mode": self.mode,
            "timestamp": time.time(),
            "status": "IN_PROGRESS",
            "trials_requested": self.trials_to_run,
        }
        (self._base_work_dir / "latest_run.json").write_text(
            json.dumps(latest_pointer_data, indent=2), encoding="utf-8"
        )

        # 2. Acquire shared host SingleInstanceLock in live mode
        interrupted = False
        self.host_lock = SingleInstanceLock(self.lock_path)
        if self.mode == "live":
            if not self.host_lock.acquire():
                latest_pointer_data["status"] = "BLOCKED_LOCK_HELD"
                (self._base_work_dir / "latest_run.json").write_text(
                    json.dumps(latest_pointer_data, indent=2), encoding="utf-8"
                )
                raise SingleInstanceLockError(
                    f"Cannot run live acceptance: coordinator instance lock at '{self.lock_path}' is already held by another process."
                )

        try:
            # 3. Safety re-check immediately before launching any trial in live mode
            if self.mode == "live":
                configured_exe_names = (
                    {Path(self.miner_process_config.executable).name.casefold()}
                    if self.miner_process_config and self.miner_process_config.executable
                    else None
                )
                if self._external_miners_override_for_test is not None:
                    external_miners = list(self._external_miners_override_for_test)
                else:
                    external_miners = scan_external_miners(configured_exe_names)
                if external_miners:
                    raise RuntimeError(
                        f"Cannot start live acceptance: external miner process(es) currently running: {external_miners}. "
                        "Stop external miners manually before starting supervised acceptance."
                    )

            # 4. Execute requested trials
            to_run = self.trials_to_run

            if to_run is None or "T01" in to_run:
                await self._run_trial_1_single_request()
            if to_run is None or "T02" in to_run:
                await self._run_trial_2_cooldown_interruption()
            if to_run is None or "T03" in to_run:
                await self._run_trial_3_concurrent_requests()
            if to_run is None or "T04" in to_run:
                await self._run_trial_4_streaming_sse()

            mock_only_skipped = 0
            if self.mode != "live":
                if to_run is None or "T05" in to_run:
                    await self._run_trial_5_error_inhibition()
            else:
                if to_run is None or "T05" in to_run:
                    mock_only_skipped = 1

            total = len(self.report.trials)
            passed = sum(1 for t in self.report.trials if t.status == "PASS")
            failed = sum(1 for t in self.report.trials if t.status == "FAIL")
            all_passed = passed == total and total > 0

            # Determine run_verification_level for the current execution
            if self.mode == "live":
                is_test_override = (
                    self._allow_short_cooldown_for_test or self._upstream_app_override_for_test is not None
                )
                if all_passed and not is_test_override:
                    if total >= 4 and (to_run is None or len(to_run) >= 4):
                        self.report.run_verification_level = "live_hardware"
                    else:
                        self.report.run_verification_level = "live_hardware_partial_stage"
                elif all_passed and is_test_override:
                    self.report.run_verification_level = "live_contract_rehearsal"
                else:
                    self.report.run_verification_level = "failed_live_verification"
            else:
                self.report.run_verification_level = self.report.verification_level

            # Determine aggregate verification level by scanning historical runs
            agg = self._scan_aggregate_evidence()
            self.report.aggregate_verification_level = agg["aggregate_verification_level"]
            self.report.aggregate_trials_verified = agg["aggregate_trials_verified"]
            self.report.aggregate_status = agg["aggregate_status"]
            if self.mode == "live" and is_test_override:
                self.report.verification_level = "live_contract_rehearsal"
            else:
                self.report.verification_level = agg["aggregate_verification_level"] or self.report.run_verification_level

            self.report.summary = {
                "run_id": self.current_run_id,
                "total_trials": total,
                "passed": passed,
                "failed": failed,
                "mock_only_trials_skipped": mock_only_skipped,
                "trials_executed": [t.trial_id for t in self.report.trials],
                "all_passed": all_passed,
                "verification_level": self.report.verification_level,
                "run_verification_level": self.report.run_verification_level,
                "aggregate_verification_level": self.report.aggregate_verification_level,
                "aggregate_trials_verified": self.report.aggregate_trials_verified,
                "aggregate_status": self.report.aggregate_status,
                "run_dir": str(self.current_run_dir),
            }
        except (KeyboardInterrupt, asyncio.CancelledError) as exc:
            interrupted = True
            self.report.summary = {
                "run_id": self.current_run_id,
                "status": "INTERRUPTED",
                "error": str(exc) or type(exc).__name__,
                "total_trials": len(self.report.trials),
                "passed": sum(1 for t in self.report.trials if t.status == "PASS"),
                "failed": sum(1 for t in self.report.trials if t.status == "FAIL"),
                "all_passed": False,
                "run_dir": str(self.current_run_dir),
            }
            raise
        except Exception as exc:
            self.report.summary = {
                "run_id": self.current_run_id,
                "status": "FAILED",
                "error": str(exc),
                "total_trials": len(self.report.trials),
                "passed": sum(1 for t in self.report.trials if t.status == "PASS"),
                "failed": sum(1 for t in self.report.trials if t.status == "FAIL"),
                "all_passed": False,
                "run_dir": str(self.current_run_dir),
            }
            raise
        finally:
            # Always save acceptance_report.json inside run directory preserving evidence
            report_file_in_run = self.current_run_dir / "acceptance_report.json"
            self.report.save(report_file_in_run)
            logger.info("Saved acceptance report to %s", report_file_in_run)

            # Update latest_run.json
            final_status = "INTERRUPTED" if interrupted else "COMPLETED" if self.report.summary.get("all_passed") else "FAILED"
            latest_pointer_data["status"] = final_status
            latest_pointer_data["report_file"] = str(report_file_in_run)
            latest_pointer_data["summary"] = self.report.summary
            (self._base_work_dir / "latest_run.json").write_text(
                json.dumps(latest_pointer_data, indent=2), encoding="utf-8"
            )

            # If user requested explicit output_file, copy report there too
            if output_file:
                self.report.save(output_file)

            # Release host single instance lock
            if self.host_lock is not None and self.host_lock.is_acquired:
                self.host_lock.release()

        return self.report

    def _build_test_harness(
        self,
        trial_id: str,
        cooldown_seconds: float,
        mock_handler: Optional[Callable] = None,
    ):
        """Build isolated per-trial environment with durable journal, single-instance lock, and telemetry."""
        run_dir = self._ensure_run_dir()
        trial_dir = run_dir / trial_id.lower()
        trial_dir.mkdir(parents=True, exist_ok=True)
        journal_path = run_dir / f"journal_{trial_id.lower()}.json"
        StateCodec.initialize(journal_path)
        log_path = trial_dir / "miner_stdout.log"

        active_leases = 0
        peak_active_leases = 0
        telemetry: Dict[str, Any] = {
            "journal_path": str(journal_path),
            "lock_path": str(self.lock_path),
            "log_path": str(log_path),
            "stop_verified_monotonic": None,
            "lease_acquired_monotonic": None,
            "upstream_dispatch_monotonic": None,
            "stopped_before_forward_verified": False,
            "observed_running_during_inference": False,
            "cooldown_started_monotonic": None,
            "restarted_monotonic": None,
            "observed_pids": [],
            "active_leases": 0,
            "peak_active_leases": 0,
        }

        async def default_upstream_handler(request):
            body = await request.json()
            is_stream = body.get("stream", False)
            if is_stream:

                async def event_generator():
                    yield b'data: {"choices": [{"delta": {"content": "OK"}}]}\n\n'
                    await asyncio.sleep(0.01)
                    yield b"data: [DONE]\n\n"

                return StreamingResponse(event_generator(), media_type="text/event-stream")
            return JSONResponse({"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]})

        raw_handler = mock_handler or default_upstream_handler

        async def instrumented_mock_handler(request):
            now_mono = time.monotonic()
            if telemetry["upstream_dispatch_monotonic"] is None:
                telemetry["upstream_dispatch_monotonic"] = now_mono
            info = await supervisor.status()
            if info.state != ProcessState.STOPPED:
                telemetry["observed_running_during_inference"] = True
            elif (
                telemetry["stop_verified_monotonic"] is not None
                and telemetry["stop_verified_monotonic"] <= now_mono
            ):
                telemetry["stopped_before_forward_verified"] = True
            return await raw_handler(request)

        mock_upstream_app = Starlette(
            routes=[
                Route("/v1/chat/completions", instrumented_mock_handler, methods=["POST"]),
                Route(
                    "/api/v0/models",
                    lambda r: JSONResponse(
                        {
                            "data": [
                                {
                                    "id": "test-model",
                                    "type": "llm",
                                    "state": "loaded",
                                    "loaded_context_length": 8192,
                                }
                            ]
                        }
                    ),
                    methods=["GET"],
                ),
                Route("/v1/models", lambda r: JSONResponse({"data": [{"id": "test-model"}]}), methods=["GET"]),
            ]
        )

        upstream_client: Optional[httpx.AsyncClient] = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_upstream_app),
            base_url="http://mock-upstream",
        )

        if self.mode == "live":
            if self.miner_process_config is None or self.miner_process_config.backend != "windows":
                raise RuntimeError(
                    "Live acceptance mode requires an explicit Windows miner_process_config; "
                    "refusing to fall back to simulated backend"
                )
            target_proc_name = self.miner_process_config.name
            live_proc_cfg = copy.deepcopy(self.miner_process_config)
            live_proc_cfg.stdout_log_path = str(log_path)
            cfg = CoordinatorConfig(
                service=ServiceConfig(
                    upstream_url=self.lmstudio_url,
                    state_persistence_path=str(journal_path),
                ),
                processes={target_proc_name: live_proc_cfg},
                policies=[
                    PolicyConfig(
                        name="stop-miner-live",
                        trigger_event="lmstudio.inference_requested",
                        target_process=target_proc_name,
                        stop_process=True,
                        restart_process=True,
                        resource="gpu.inference",
                        lease_type="shared",
                        cooldown_seconds=cooldown_seconds,
                        only_if_stopped_by_coordinator=True,
                    )
                ],
            )
            system = build_system(cfg, use_fake_processes=False)
            if self._upstream_app_override_for_test is not None:
                await_close = upstream_client
                asyncio.create_task(await_close.aclose())
                upstream_client = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self._upstream_app_override_for_test),
                    base_url=self.lmstudio_url,
                )
                system.gateway._http_client = upstream_client
            elif mock_handler is not None:
                system.gateway._http_client = upstream_client
            else:
                await_close = upstream_client
                upstream_client = None
                asyncio.create_task(await_close.aclose())
            service = CoordinatorService(
                system,
                start_process_on_ready=target_proc_name,
                stop_process_on_shutdown=target_proc_name,
                instance_lock=self.host_lock,
                lock_path=self.lock_path,
            )
            supervisor = system.supervisors[target_proc_name]
            backend = supervisor.backend
        elif self.mode == "disposable_helper":
            if os.name != "nt":
                raise RuntimeError("Disposable helper acceptance mode requires Windows (os.name == 'nt')")
            vbs_path = Path(__file__).parent / "adapters" / "miners" / "windows_miner_helper.vbs"
            cscript_exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cscript.exe")
            proc_cfg = ProcessConfig(
                name="krig",
                backend="windows",
                executable=cscript_exe,
                arguments=["//B", "//NoLogo", str(vbs_path), f"rc_{trial_id}"],
                working_directory=str(trial_dir),
                stop_timeout_seconds=5.0,
                allow_force_termination=True,
                stdout_log_path=str(log_path),
            )
            cfg = CoordinatorConfig(
                service=ServiceConfig(
                    upstream_url="http://mock-upstream",
                    state_persistence_path=str(journal_path),
                ),
                processes={"krig": proc_cfg},
                policies=[
                    PolicyConfig(
                        name="stop-krig",
                        trigger_event="lmstudio.inference_requested",
                        target_process="krig",
                        stop_process=True,
                        restart_process=True,
                        resource="gpu.inference",
                        lease_type="shared",
                        cooldown_seconds=cooldown_seconds,
                        only_if_stopped_by_coordinator=True,
                    )
                ],
            )
            system = build_system(cfg, use_fake_processes=False)
            system.gateway._http_client = upstream_client
            service = CoordinatorService(
                system,
                start_process_on_ready="krig",
                stop_process_on_shutdown="krig",
                instance_lock=self.host_lock,
                lock_path=self.lock_path,
            )
            supervisor = system.supervisors["krig"]
            backend = supervisor.backend
        else:
            cfg = CoordinatorConfig(
                service=ServiceConfig(
                    upstream_url="http://mock-upstream",
                    state_persistence_path=str(journal_path),
                ),
                processes={"krig": ProcessConfig(name="krig", backend="fake")},
                policies=[
                    PolicyConfig(
                        name="stop-krig",
                        trigger_event="lmstudio.inference_requested",
                        target_process="krig",
                        stop_process=True,
                        restart_process=True,
                        resource="gpu.inference",
                        lease_type="shared",
                        cooldown_seconds=cooldown_seconds,
                        only_if_stopped_by_coordinator=True,
                    )
                ],
            )
            system = build_system(cfg, use_fake_processes=True)
            system.gateway._http_client = upstream_client
            service = CoordinatorService(
                system,
                start_process_on_ready="krig",
                stop_process_on_shutdown="krig",
                instance_lock=self.host_lock,
                lock_path=self.lock_path,
            )
            supervisor = system.supervisors["krig"]
            backend = supervisor.backend

        # Attach dispatcher listeners for monotonic timing and PID tracking
        async def on_process_started(event: Any) -> None:
            now_mono = time.monotonic()
            info = await supervisor.status()
            if info.pid is not None and info.create_time is not None:
                telemetry["observed_pids"].append({"pid": info.pid, "create_time": info.create_time})
            if telemetry["cooldown_started_monotonic"] is not None:
                telemetry["restarted_monotonic"] = now_mono
                telemetry["restarted_pid"] = info.pid
                telemetry["restarted_create_time"] = info.create_time

        async def on_process_stopped(event: Any) -> None:
            if telemetry["stop_verified_monotonic"] is None:
                telemetry["stop_verified_monotonic"] = time.monotonic()

        async def on_resource_acquired(event: Any) -> None:
            nonlocal active_leases, peak_active_leases
            telemetry["lease_acquired_monotonic"] = time.monotonic()
            active_leases += 1
            if active_leases > peak_active_leases:
                peak_active_leases = active_leases
            telemetry["active_leases"] = active_leases
            telemetry["peak_active_leases"] = peak_active_leases

        async def on_resource_released(event: Any) -> None:
            nonlocal active_leases
            active_leases = max(0, active_leases - 1)
            telemetry["active_leases"] = active_leases

        async def on_inference_forwarded(event: Any) -> None:
            now_mono = time.monotonic()
            if telemetry["upstream_dispatch_monotonic"] is None:
                telemetry["upstream_dispatch_monotonic"] = now_mono
            info = await supervisor.status()
            if info.state != ProcessState.STOPPED:
                telemetry["observed_running_during_inference"] = True
            elif (
                telemetry["stop_verified_monotonic"] is not None
                and telemetry["stop_verified_monotonic"] <= now_mono
            ):
                telemetry["stopped_before_forward_verified"] = True

        async def on_cooldown_started(event: Any) -> None:
            telemetry["cooldown_started_monotonic"] = time.monotonic()

        system.dispatcher.on("process.started", on_process_started)
        system.dispatcher.on("process.stopped", on_process_stopped)
        system.dispatcher.on("resource.acquired", on_resource_acquired)
        system.dispatcher.on("resource.released", on_resource_released)
        system.dispatcher.on("lmstudio.inference_forwarded", on_inference_forwarded)
        system.dispatcher.on("resource.cooldown_started", on_cooldown_started)

        gateway_app = system.gateway.create_app(service)
        coordinator_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway_app),
            base_url="http://coordinator",
        )

        return service, system, coordinator_client, upstream_client, supervisor, backend, telemetry

    async def _cleanup_trial_harness(
        self,
        t: TrialEvidence,
        service: Optional[CoordinatorService],
        system: Optional[CoordinatorSystem],
        client: Optional[httpx.AsyncClient],
        upstream_client: Optional[httpx.AsyncClient],
        supervisor: Any,
        backend: Any,
        telemetry: Optional[Dict[str, Any]],
    ) -> None:
        """
        Guaranteed supervised cleanup executed in `finally` of every trial.
        Verifies miner and descendant termination. Overrides trial status to FAIL
        if process stop cannot be verified.
        """
        if telemetry:
            t.metrics.setdefault("journal_path", telemetry.get("journal_path"))
            t.metrics.setdefault("lock_path", telemetry.get("lock_path"))

        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:
                t.diagnostics.append(f"Error closing coordinator client: {exc}")

        if upstream_client is not None:
            try:
                await upstream_client.aclose()
            except Exception as exc:
                t.diagnostics.append(f"Error closing mock upstream client: {exc}")

        cleanup_errors: List[str] = []
        if service is not None:
            try:
                await service.stop(reason=f"trial_{t.trial_id}_cleanup")
                if (
                    service.state == ServiceState.RECONCILIATION_REQUIRED
                    and service.failure_reason
                    and "unverified process stop" in service.failure_reason
                ):
                    cleanup_errors.append(f"Service shutdown reported: {service.failure_reason}")
            except Exception as exc:
                cleanup_errors.append(f"Exception in service.stop(): {exc}")

        backend_stopped = True
        if backend is not None:
            try:
                info: ProcessInfo = await backend.status()
                if info.state != ProcessState.STOPPED:
                    stopped_ok = await backend.stop(timeout=5.0)
                    info = await backend.status()
                    if not stopped_ok or info.state != ProcessState.STOPPED:
                        backend_stopped = False
                        cleanup_errors.append(
                            f"Backend process '{info.name}' remained in state '{info.state.value}' (PID {info.pid}) after stop"
                        )
            except Exception as exc:
                backend_stopped = False
                cleanup_errors.append(f"Exception verifying backend stop: {exc}")

        descendants_stopped = True
        observed_pids = (telemetry or {}).get("observed_pids", [])
        if os.name == "nt" and isinstance(backend, WindowsProcessBackend):
            for ident in observed_pids:
                pid = ident.get("pid")
                ct = ident.get("create_time")
                if not pid or not ct:
                    continue
                try:
                    proc = psutil.Process(pid)
                    if proc.create_time() == ct:
                        children = proc.children(recursive=True)
                        if proc.is_running():
                            proc.terminate()
                            try:
                                proc.wait(timeout=3.0)
                            except psutil.TimeoutExpired:
                                proc.kill()
                                proc.wait(timeout=2.0)
                        for child in children:
                            try:
                                if child.is_running():
                                    child.terminate()
                                    child.wait(timeout=2.0)
                            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                                pass
                        if proc.is_running() or any(c.is_running() for c in children):
                            descendants_stopped = False
                            cleanup_errors.append(f"Owned Windows PID {pid} or its descendants remained running")
                except psutil.NoSuchProcess:
                    continue
                except Exception as exc:
                    descendants_stopped = False
                    cleanup_errors.append(f"Error verifying Windows PID {pid} cleanup: {exc}")

        cleanup_verified = bool(backend_stopped and descendants_stopped and not cleanup_errors)
        t.metrics["cleanup_verified_stopped"] = cleanup_verified
        t.metrics["descendants_verified_stopped"] = descendants_stopped

        if not cleanup_verified:
            t.status = "FAIL"
            err_detail = "; ".join(cleanup_errors) or "unverified miner stop"
            cleanup_msg = f"Supervised cleanup failed: {err_detail}"
            t.error = f"{t.error} | {cleanup_msg}" if t.error else cleanup_msg

    async def _wait_for_restart(self, supervisor: Any, backend: Any, cooldown: float) -> ProcessInfo:
        deadline = time.monotonic() + cooldown + 3.0
        while time.monotonic() < deadline:
            info = await supervisor.status()
            if info.state == ProcessState.RUNNING:
                return info
            await asyncio.sleep(0.05)
        return await supervisor.status()

    def _record_trial_telemetry(self, t: TrialEvidence, telemetry: Dict[str, Any], cooldown: float) -> None:
        t.metrics["stopped_before_forward_verified"] = bool(telemetry.get("stopped_before_forward_verified"))
        t.metrics["observed_exit_during_inference"] = not bool(telemetry.get("observed_running_during_inference"))
        t.metrics["cooldown_target_seconds"] = cooldown
        cd_start = telemetry.get("cooldown_started_monotonic")
        restarted_at = telemetry.get("restarted_monotonic")
        if cd_start is not None and restarted_at is not None:
            t.metrics["cooldown_elapsed_seconds"] = restarted_at - cd_start
        if telemetry.get("restarted_pid") is not None:
            t.metrics["restarted_pid"] = telemetry.get("restarted_pid")
            t.metrics["restarted_create_time"] = telemetry.get("restarted_create_time")
        if telemetry.get("upstream_dispatch_monotonic") is not None:
            t.metrics["upstream_dispatch_monotonic"] = telemetry["upstream_dispatch_monotonic"]
        if telemetry.get("stop_verified_monotonic") is not None:
            t.metrics["stop_verified_monotonic"] = telemetry["stop_verified_monotonic"]
        if telemetry.get("lease_acquired_monotonic") is not None:
            t.metrics["lease_acquired_monotonic"] = telemetry["lease_acquired_monotonic"]
        t.metrics["max_concurrent_leases"] = telemetry.get("peak_active_leases", 1)

    async def _verify_mining_warmup(
        self,
        supervisor: Any,
        backend: Any,
        sampler: GpuActivitySampler,
        log_path: Path,
        timeout: float,
        phase: str,
        t: TrialEvidence,
        start_offset: int = 0,
        generation_num: int = 1,
    ) -> Dict[str, Any]:
        """
        Verify that the miner reaches and sustains actual mining/hashing activity.
        Uses a 5-state verification state machine:
          PROCESS_LAUNCHED -> ACTIVITY_DETECTED -> SUSTAINED_ACTIVITY_CONFIRMED -> SETTLING_IN_PROGRESS -> WARMUP_VERIFIED
        """
        t_start = time.monotonic()
        deadline = t_start + timeout
        state = "PROCESS_LAUNCHED"
        settle_deadline: Optional[float] = None
        settle_start_time: Optional[float] = None
        settling_verified = False
        method_parts: List[str] = []
        gpu_active_once = False
        last_log_parsed: Dict[str, Any] = {}
        last_end_offset = start_offset

        # Retrieve process PID and create_time
        info = await supervisor.status()
        current_pid = info.pid
        current_create_time = info.create_time

        # Start phase-isolated GPU sampling
        sampler.start_phase(phase_name=phase, pid=current_pid, create_time=current_create_time)

        try:
            while time.monotonic() < deadline:
                # Check if settling was completed
                if (
                    state == "SETTLING_IN_PROGRESS"
                    and settle_deadline is not None
                    and time.monotonic() >= settle_deadline
                ):
                    state = "WARMUP_VERIFIED"
                    settling_verified = True
                    break

                # 1. Verify process is still alive; fail fast if process terminates
                info = await supervisor.status()
                if info.state not in {ProcessState.RUNNING, ProcessState.EXTERNAL_RUNNING}:
                    raise RuntimeError(
                        f"Miner exited prematurely during {phase} warm-up (state={info.state.value}, PID={info.pid})"
                    )

                # 2. Sample GPU metrics for this phase
                await sampler.sample()

                # 3. Parse stdout log from phase start_offset
                log_info = parse_miner_stdout_log(log_path, start_offset=start_offset)
                last_log_parsed = log_info
                last_end_offset = log_info.get("end_offset", last_end_offset)

                if log_info.get("pool_connected"):
                    if phase == "initial":
                        t.initial_pool_connected = True
                if log_info.get("hashrate"):
                    if phase == "initial" and not t.initial_hashrate:
                        t.initial_hashrate = log_info["hashrate"]

                gpu_sustained = sampler.is_activity_sustained(phase)
                log_has_hashrate = bool(log_info.get("hashrate"))
                if gpu_sustained:
                    gpu_active_once = True

                # 4. State transitions
                if state in ("PROCESS_LAUNCHED", "ACTIVITY_DETECTED"):
                    if gpu_sustained or log_has_hashrate:
                        state = "SUSTAINED_ACTIVITY_CONFIRMED"
                        if gpu_sustained and "gpu_telemetry" not in method_parts:
                            method_parts.append("gpu_telemetry")
                        if log_has_hashrate and "miner_stdout" not in method_parts:
                            method_parts.append("miner_stdout")
                    elif (
                        sampler.current_phase
                        and sampler.current_phase.peak_power_w is not None
                        and sampler.current_phase.peak_power_w
                        > (sampler.baseline or {}).get("power_draw_w", 0.0) + sampler.min_power_delta_w
                    ) or log_info.get("pool_connected"):
                        state = "ACTIVITY_DETECTED"

                if state == "SUSTAINED_ACTIVITY_CONFIRMED":
                    if self.mining_settle_seconds > 0.0:
                        state = "SETTLING_IN_PROGRESS"
                        settle_start_time = time.monotonic()
                        settle_deadline = settle_start_time + self.mining_settle_seconds
                    else:
                        state = "WARMUP_VERIFIED"
                        settling_verified = True
                        break

                if state == "SETTLING_IN_PROGRESS":
                    activity_active = gpu_sustained or log_has_hashrate
                    if not activity_active:
                        logger.warning(
                            "Activity dropped during %s settling window; resetting settle timer",
                            phase,
                        )
                        state = "ACTIVITY_DETECTED"
                        settle_deadline = None
                    elif settle_deadline is not None and time.monotonic() >= settle_deadline:
                        state = "WARMUP_VERIFIED"
                        settling_verified = True
                        break

                await asyncio.sleep(0.05)
        finally:
            verified = (state == "WARMUP_VERIFIED") and settling_verified
            phase_gpu = sampler.phase_evidence.get(phase)
            peak_power = phase_gpu.peak_power_w if phase_gpu else None
            peak_util = phase_gpu.peak_utilization_pct if phase_gpu else None
            gpu_samples_count = len(phase_gpu.samples) if phase_gpu else 0

            has_hashrate = bool(last_log_parsed.get("hashrate"))
            pool_connected = bool(last_log_parsed.get("pool_connected"))
            connected_pool_url = last_log_parsed.get("connected_pool_url")
            pool_job_received = bool(last_log_parsed.get("pool_job_received"))
            hashrate_str = last_log_parsed.get("hashrate")
            hashrate_ths = last_log_parsed.get("hashrate_ths")

            is_running = info.state in {ProcessState.RUNNING, ProcessState.EXTERNAL_RUNNING}

            if verified:
                if gpu_active_once and has_hashrate:
                    classification = "hashing_verified"
                elif has_hashrate:
                    classification = "miner_hashrate_reported"
                elif gpu_active_once:
                    classification = "gpu_compute_activity_observed"
                elif pool_connected:
                    classification = "pool_connection_verified"
                else:
                    classification = "process_running"
            else:
                if has_hashrate and gpu_active_once:
                    classification = "hashing_verified"
                elif has_hashrate:
                    classification = "miner_hashrate_reported"
                elif gpu_active_once:
                    classification = "gpu_compute_activity_observed"
                elif pool_connected:
                    classification = "pool_connection_verified"
                elif is_running and (gpu_samples_count > 0 or last_log_parsed.get("exists")):
                    classification = "process_running"
                else:
                    classification = "verification_inconclusive"

            verification_method = "+".join(method_parts) if method_parts else "none"
            t_now = time.monotonic()
            settling_duration = (t_now - settle_start_time) if settle_start_time else 0.0

            gen_evidence: Dict[str, Any] = {
                "generation": generation_num,
                "phase": phase,
                "pid": current_pid,
                "create_time": current_create_time,
                "launch_monotonic": t_start,
                "verified": verified,
                "settling_verified": settling_verified,
                "evidence_classification": classification,
                "verification_method": verification_method,
                "peak_power_w": peak_power,
                "peak_utilization_pct": peak_util,
                "gpu_samples_count": gpu_samples_count,
                "log_start_offset": start_offset,
                "log_end_offset": last_end_offset,
                "pool_connected": pool_connected,
                "connected_pool_url": connected_pool_url,
                "pool_job_received": pool_job_received,
                "hashrate": hashrate_str,
                "hashrate_ths": hashrate_ths,
                "warmup_duration_seconds": t_now - t_start,
                "settling_duration_seconds": settling_duration,
            }

            if phase == "initial":
                t.initial_generation = gen_evidence
                t.initial_mining_activity_verified = verified
                if verified and not t.mining_verification_method:
                    t.mining_verification_method = verification_method
            else:
                t.restart_generation = gen_evidence
                t.restart_mining_activity_verified = verified

        return gen_evidence

    async def _verify_initial_mining(
        self,
        supervisor: Any,
        backend: Any,
        sampler: GpuActivitySampler,
        log_path: Path,
        t: TrialEvidence,
        t_miner_started: float,
        initial_info: ProcessInfo,
    ) -> None:
        if self.require_mining_activity:
            gen1_evidence = await self._verify_mining_warmup(
                supervisor=supervisor,
                backend=backend,
                sampler=sampler,
                log_path=log_path,
                timeout=self.mining_warmup_timeout_seconds,
                phase="initial",
                t=t,
                start_offset=getattr(backend, "last_launch_log_offset", 0),
                generation_num=getattr(backend, "generation", 1) or 1,
            )
            t.initial_miner_uptime_before_inference_seconds = time.monotonic() - t_miner_started
            if not gen1_evidence.get("verified"):
                raise RuntimeError(
                    f"Mining activity contract failed: miner did not reach sustained hashing state "
                    f"within {self.mining_warmup_timeout_seconds}s warm-up window"
                )
        else:
            t.initial_miner_uptime_before_inference_seconds = time.monotonic() - t_miner_started
            t.initial_mining_activity_verified = True
            t.mining_verification_method = "simulated"
            t.initial_generation = {
                "generation": 1,
                "phase": "initial",
                "pid": initial_info.pid,
                "create_time": initial_info.create_time,
                "launch_monotonic": t_miner_started,
                "verified": True,
                "settling_verified": True,
                "evidence_classification": "simulated",
                "verification_method": "simulated",
                "peak_power_w": 0.0,
                "peak_utilization_pct": 0.0,
                "gpu_samples_count": 0,
                "log_start_offset": 0,
                "log_end_offset": 0,
                "pool_connected": False,
                "connected_pool_url": None,
                "pool_job_received": False,
                "hashrate": None,
                "hashrate_ths": None,
            }

    async def _verify_restart_mining(
        self,
        supervisor: Any,
        backend: Any,
        sampler: GpuActivitySampler,
        log_path: Path,
        t: TrialEvidence,
        t_restarted: float,
        resumed_info: ProcessInfo,
    ) -> None:
        gen1_end_offset = t.initial_generation.get("log_end_offset", 0) if t.initial_generation else 0
        restart_log_offset = max(getattr(backend, "last_launch_log_offset", 0), gen1_end_offset)
        restart_gen_num = getattr(backend, "generation", 2) or 2

        if self.require_mining_activity:
            gen2_evidence = await self._verify_mining_warmup(
                supervisor=supervisor,
                backend=backend,
                sampler=sampler,
                log_path=log_path,
                timeout=self.mining_warmup_timeout_seconds,
                phase="restart",
                t=t,
                start_offset=restart_log_offset,
                generation_num=restart_gen_num,
            )
            t.restart_time_to_hashing_seconds = time.monotonic() - t_restarted
            if not gen2_evidence.get("verified"):
                raise RuntimeError(
                    f"Mining activity contract failed: restarted miner did not resume sustained hashing "
                    f"within {self.mining_warmup_timeout_seconds}s window"
                )
        else:
            t.restart_mining_activity_verified = True
            t.restart_time_to_hashing_seconds = time.monotonic() - t_restarted
            t.restart_generation = {
                "generation": 2,
                "phase": "restart",
                "pid": resumed_info.pid,
                "create_time": resumed_info.create_time,
                "launch_monotonic": t_restarted,
                "verified": True,
                "settling_verified": True,
                "evidence_classification": "simulated",
                "verification_method": "simulated",
                "peak_power_w": 0.0,
                "peak_utilization_pct": 0.0,
                "gpu_samples_count": 0,
                "log_start_offset": 0,
                "log_end_offset": 0,
                "pool_connected": False,
                "connected_pool_url": None,
                "pool_job_received": False,
                "hashrate": None,
                "hashrate_ths": None,
            }

    def _finalize_trial_sampler(self, t: TrialEvidence, sampler: Optional[GpuActivitySampler]) -> None:
        if sampler is not None:
            t.gpu_samples = list(sampler.samples)
            if sampler.samples:
                t.peak_gpu_power_w = max(s.get("power_draw_w", 0.0) for s in sampler.samples)
                t.peak_gpu_utilization_pct = max(s.get("utilization_pct", 0.0) for s in sampler.samples)

    async def _run_trial_1_single_request(
        self,
        mock_handler: Optional[Callable] = None,
        _post_build_hook: Optional[Callable] = None,
    ) -> None:
        """Trial 1: Single request stop-before-forward and exact idle cooldown restart."""
        t = TrialEvidence(trial_id="T01", name="Single Request Stop Before Forward and Cooldown")
        t.start_monotonic = time.monotonic()
        service = system = client = upstream_client = supervisor = backend = telemetry = sampler = None
        initial_info = resumed_info = resp = None
        try:
            cooldown = self.cooldown_seconds
            service, system, client, upstream_client, supervisor, backend, telemetry = self._build_test_harness(
                trial_id="T01",
                cooldown_seconds=cooldown,
                mock_handler=mock_handler,
            )
            if _post_build_hook is not None:
                _post_build_hook(service, system, backend)

            sampler = GpuActivitySampler(monitor=self.gpu_monitor)
            baseline = await sampler.sample_baseline()
            if baseline:
                t.gpu_idle_baseline = baseline

            if not await service.start():
                raise RuntimeError(f"Service failed to start: {service.failure_reason}")

            initial_info = await supervisor.status()
            assert initial_info.state == ProcessState.RUNNING
            t.metrics["initial_pid"] = initial_info.pid
            t.metrics["initial_create_time"] = initial_info.create_time
            t.process_contract_verified = True
            t_miner_started = time.monotonic()

            log_path = Path(telemetry.get("log_path", ""))

            await self._verify_initial_mining(
                supervisor=supervisor,
                backend=backend,
                sampler=sampler,
                log_path=log_path,
                t=t,
                t_miner_started=t_miner_started,
                initial_info=initial_info,
            )

            model_info = await discover_live_model(client)
            model_id = model_info["model_id"]
            t.metrics["model_id"] = model_id

            # Miner must still be running after read-only model discovery
            assert (await supervisor.status()).state == ProcessState.RUNNING

            t_req_start = time.monotonic()
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                    "max_tokens": 8,
                    "temperature": 0.0,
                },
            )
            t_req_end = time.monotonic()
            t.metrics["inference_result"] = {"status_code": resp.status_code}
            t.metrics["request_duration_ms"] = (t_req_end - t_req_start) * 1000.0

            assert resp.status_code == 200
            assert (await supervisor.status()).state == ProcessState.STOPPED
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True
            assert telemetry["stopped_before_forward_verified"] is True
            assert telemetry["observed_running_during_inference"] is False

            resumed_info = await self._wait_for_restart(supervisor, backend, cooldown)
            assert resumed_info.state == ProcessState.RUNNING
            t.metrics["miner_restarted"] = True
            t.metrics["restarted_pid"] = resumed_info.pid
            t.metrics["restarted_create_time"] = resumed_info.create_time
            t_restarted = time.monotonic()

            await self._verify_restart_mining(
                supervisor=supervisor,
                backend=backend,
                sampler=sampler,
                log_path=log_path,
                t=t,
                t_restarted=t_restarted,
                resumed_info=resumed_info,
            )

            self._record_trial_telemetry(t, telemetry, cooldown)
            if t.metrics.get("cooldown_elapsed_seconds") is not None:
                assert t.metrics["cooldown_elapsed_seconds"] >= cooldown - 0.15

            # Evaluate 3 verification contracts
            t.process_contract_verified = (
                initial_info.state == ProcessState.RUNNING
                and resumed_info.state == ProcessState.RUNNING
                and resumed_info.pid is not None
            )
            t.inference_arbitration_contract_verified = (
                resp.status_code == 200
                and telemetry["stopped_before_forward_verified"] is True
                and telemetry["observed_running_during_inference"] is False
            )
            t.mining_activity_contract_verified = (
                bool(t.initial_generation and t.initial_generation.get("verified"))
                and bool(t.restart_generation and t.restart_generation.get("verified"))
            ) if self.require_mining_activity else True

            if (
                t.process_contract_verified
                and t.inference_arbitration_contract_verified
                and (t.mining_activity_contract_verified or not self.require_mining_activity)
            ):
                t.status = "PASS"
            else:
                t.status = "FAIL"
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            if initial_info is not None and initial_info.state == ProcessState.RUNNING:
                t.process_contract_verified = True
            logger.exception("Trial 1 failed: %s", exc)
        finally:
            self._finalize_trial_sampler(t, sampler)
            await self._cleanup_trial_harness(
                t, service, system, client, upstream_client, supervisor, backend, telemetry
            )
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_2_cooldown_interruption(self) -> None:
        """Trial 2: Request arriving during cooldown cancels restart immediately."""
        t = TrialEvidence(trial_id="T02", name="Cooldown Interruption and Debounce")
        t.start_monotonic = time.monotonic()
        service = system = client = upstream_client = supervisor = backend = telemetry = sampler = None
        initial_info = resumed_info = resp1 = resp2 = None
        try:
            cooldown = self.cooldown_seconds
            service, system, client, upstream_client, supervisor, backend, telemetry = self._build_test_harness(
                trial_id="T02",
                cooldown_seconds=cooldown,
            )
            sampler = GpuActivitySampler(monitor=self.gpu_monitor)
            baseline = await sampler.sample_baseline()
            if baseline:
                t.gpu_idle_baseline = baseline

            if not await service.start():
                raise RuntimeError(f"Service failed to start: {service.failure_reason}")

            initial_info = await supervisor.status()
            assert initial_info.state == ProcessState.RUNNING
            t.metrics["initial_pid"] = initial_info.pid
            t.metrics["initial_create_time"] = initial_info.create_time
            t.process_contract_verified = True
            t_miner_started = time.monotonic()

            log_path = Path(telemetry.get("log_path", ""))

            await self._verify_initial_mining(
                supervisor=supervisor,
                backend=backend,
                sampler=sampler,
                log_path=log_path,
                t=t,
                t_miner_started=t_miner_started,
                initial_info=initial_info,
            )

            model_info = await discover_live_model(client)
            model_id = model_info["model_id"]
            t.metrics["model_id"] = model_id

            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                "max_tokens": 8,
                "temperature": 0.0,
            }

            resp1 = await client.post("/v1/chat/completions", json=payload)
            assert resp1.status_code == 200
            assert (await supervisor.status()).state == ProcessState.STOPPED
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            # Send Request 2 at 50% of cooldown duration
            await asyncio.sleep(cooldown * 0.5)
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True
            assert (await supervisor.status()).state == ProcessState.STOPPED

            resp2 = await client.post("/v1/chat/completions", json=payload)
            t.metrics["inference_result"] = {
                "first_status_code": resp1.status_code,
                "second_status_code": resp2.status_code,
            }
            assert resp2.status_code == 200

            # Cooldown was reset; miner must STILL be stopped immediately after second completion
            assert (await supervisor.status()).state == ProcessState.STOPPED
            t.metrics["cooldown_cancelled_on_arrival"] = True

            resumed_info = await self._wait_for_restart(supervisor, backend, cooldown)
            assert resumed_info.state == ProcessState.RUNNING
            t.metrics["miner_restarted"] = True
            t.metrics["restarted_pid"] = resumed_info.pid
            t.metrics["restarted_create_time"] = resumed_info.create_time
            t_restarted = time.monotonic()

            await self._verify_restart_mining(
                supervisor=supervisor,
                backend=backend,
                sampler=sampler,
                log_path=log_path,
                t=t,
                t_restarted=t_restarted,
                resumed_info=resumed_info,
            )

            self._record_trial_telemetry(t, telemetry, cooldown)

            # Evaluate 3 verification contracts
            t.process_contract_verified = (
                initial_info.state == ProcessState.RUNNING
                and resumed_info.state == ProcessState.RUNNING
                and resumed_info.pid is not None
            )
            t.inference_arbitration_contract_verified = (
                resp1.status_code == 200
                and resp2.status_code == 200
                and telemetry.get("stopped_before_forward_verified") is True
                and telemetry.get("observed_running_during_inference") is False
                and t.metrics.get("cooldown_cancelled_on_arrival") is True
            )
            t.mining_activity_contract_verified = (
                bool(t.initial_generation and t.initial_generation.get("verified"))
                and bool(t.restart_generation and t.restart_generation.get("verified"))
            ) if self.require_mining_activity else True

            if (
                t.process_contract_verified
                and t.inference_arbitration_contract_verified
                and (t.mining_activity_contract_verified or not self.require_mining_activity)
            ):
                t.status = "PASS"
            else:
                t.status = "FAIL"
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            if initial_info is not None and initial_info.state == ProcessState.RUNNING:
                t.process_contract_verified = True
            logger.exception("Trial 2 failed: %s", exc)
        finally:
            self._finalize_trial_sampler(t, sampler)
            await self._cleanup_trial_harness(
                t, service, system, client, upstream_client, supervisor, backend, telemetry
            )
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_3_concurrent_requests(self) -> None:
        """Trial 3: Overlapping concurrent requests: miner stays stopped until last completion + cooldown."""
        t = TrialEvidence(trial_id="T03", name="Concurrent Overlapping Requests")
        t.start_monotonic = time.monotonic()
        service = system = client = upstream_client = supervisor = backend = telemetry = sampler = None
        initial_info = resumed_info = resp1 = resp2 = None
        try:
            cooldown = self.cooldown_seconds

            # In simulated/disposable_helper modes, use a deterministic staggered handler
            req_counter = 0

            async def staggered_mock_handler(request):
                nonlocal req_counter
                req_counter += 1
                delay = 0.05 if req_counter == 1 else 0.14
                await asyncio.sleep(delay)
                return JSONResponse({"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]})

            mock_h = staggered_mock_handler if self.mode != "live" else None
            service, system, client, upstream_client, supervisor, backend, telemetry = self._build_test_harness(
                trial_id="T03",
                cooldown_seconds=cooldown,
                mock_handler=mock_h,
            )
            sampler = GpuActivitySampler(monitor=self.gpu_monitor)
            baseline = await sampler.sample_baseline()
            if baseline:
                t.gpu_idle_baseline = baseline

            if not await service.start():
                raise RuntimeError(f"Service failed to start: {service.failure_reason}")

            initial_info = await supervisor.status()
            assert initial_info.state == ProcessState.RUNNING
            t.metrics["initial_pid"] = initial_info.pid
            t.metrics["initial_create_time"] = initial_info.create_time
            t.process_contract_verified = True
            t_miner_started = time.monotonic()

            log_path = Path(telemetry.get("log_path", ""))

            await self._verify_initial_mining(
                supervisor=supervisor,
                backend=backend,
                sampler=sampler,
                log_path=log_path,
                t=t,
                t_miner_started=t_miner_started,
                initial_info=initial_info,
            )

            model_info = await discover_live_model(client)
            model_id = model_info["model_id"]
            t.metrics["model_id"] = model_id

            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                "max_tokens": 8,
                "temperature": 0.0,
            }

            task1 = asyncio.create_task(client.post("/v1/chat/completions", json=payload))
            task2 = asyncio.create_task(client.post("/v1/chat/completions", json=payload))

            if self.mode != "live":
                resp1 = await task1
                assert resp1.status_code == 200
                # Task 2 is still running: miner MUST be stopped and cooldown NOT active
                assert (await supervisor.status()).state == ProcessState.STOPPED
                assert system.lease_mgr.active_count("gpu.inference") == 1
                assert system.lease_mgr.is_cooling_down("gpu.inference") is False
                resp2 = await task2
                assert resp2.status_code == 200
            else:
                resp1, resp2 = await asyncio.gather(task1, task2)
                assert resp1.status_code == 200
                assert resp2.status_code == 200
                assert (await supervisor.status()).state == ProcessState.STOPPED

            t.metrics["inference_result"] = {
                "resp1_status": resp1.status_code,
                "resp2_status": resp2.status_code,
            }
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            resumed_info = await self._wait_for_restart(supervisor, backend, cooldown)
            assert resumed_info.state == ProcessState.RUNNING
            t.metrics["miner_restarted"] = True
            t.metrics["restarted_pid"] = resumed_info.pid
            t.metrics["restarted_create_time"] = resumed_info.create_time
            t_restarted = time.monotonic()

            await self._verify_restart_mining(
                supervisor=supervisor,
                backend=backend,
                sampler=sampler,
                log_path=log_path,
                t=t,
                t_restarted=t_restarted,
                resumed_info=resumed_info,
            )

            self._record_trial_telemetry(t, telemetry, cooldown)
            assert t.metrics.get("max_concurrent_leases", 0) >= 2, (
                f"Expected at least 2 concurrent leases during overlapping requests, "
                f"got {t.metrics.get('max_concurrent_leases')}"
            )

            # Evaluate 3 verification contracts
            t.process_contract_verified = (
                initial_info.state == ProcessState.RUNNING
                and resumed_info.state == ProcessState.RUNNING
                and resumed_info.pid is not None
            )
            t.inference_arbitration_contract_verified = (
                resp1.status_code == 200
                and resp2.status_code == 200
                and telemetry.get("stopped_before_forward_verified") is True
                and telemetry.get("observed_running_during_inference") is False
            )
            t.mining_activity_contract_verified = (
                bool(t.initial_generation and t.initial_generation.get("verified"))
                and bool(t.restart_generation and t.restart_generation.get("verified"))
            ) if self.require_mining_activity else True

            if (
                t.process_contract_verified
                and t.inference_arbitration_contract_verified
                and (t.mining_activity_contract_verified or not self.require_mining_activity)
            ):
                t.status = "PASS"
            else:
                t.status = "FAIL"
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            if initial_info is not None and initial_info.state == ProcessState.RUNNING:
                t.process_contract_verified = True
            logger.exception("Trial 3 failed: %s", exc)
        finally:
            self._finalize_trial_sampler(t, sampler)
            await self._cleanup_trial_harness(
                t, service, system, client, upstream_client, supervisor, backend, telemetry
            )
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_4_streaming_sse(self) -> None:
        """Trial 4: Streaming SSE request with verified [DONE] marker."""
        t = TrialEvidence(trial_id="T04", name="Streaming SSE Terminal Detection")
        t.start_monotonic = time.monotonic()
        service = system = client = upstream_client = supervisor = backend = telemetry = sampler = None
        initial_info = resumed_info = None
        try:
            cooldown = self.cooldown_seconds
            service, system, client, upstream_client, supervisor, backend, telemetry = self._build_test_harness(
                trial_id="T04",
                cooldown_seconds=cooldown,
            )
            sampler = GpuActivitySampler(monitor=self.gpu_monitor)
            baseline = await sampler.sample_baseline()
            if baseline:
                t.gpu_idle_baseline = baseline

            if not await service.start():
                raise RuntimeError(f"Service failed to start: {service.failure_reason}")

            initial_info = await supervisor.status()
            assert initial_info.state == ProcessState.RUNNING
            t.metrics["initial_pid"] = initial_info.pid
            t.metrics["initial_create_time"] = initial_info.create_time
            t.process_contract_verified = True
            t_miner_started = time.monotonic()

            log_path = Path(telemetry.get("log_path", ""))

            await self._verify_initial_mining(
                supervisor=supervisor,
                backend=backend,
                sampler=sampler,
                log_path=log_path,
                t=t,
                t_miner_started=t_miner_started,
                initial_info=initial_info,
            )

            model_info = await discover_live_model(client)
            model_id = model_info["model_id"]
            t.metrics["model_id"] = model_id

            done_marker_observed = False
            chunk_count = 0
            observed_running_during_stream = False
            stream_status_code = None

            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                "max_tokens": 8,
                "temperature": 0.0,
                "stream": True,
            }

            async with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
                stream_status_code = resp.status_code
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    chunk_count += 1
                    if "[DONE]" in line:
                        done_marker_observed = True
                    status_info = await supervisor.status()
                    if status_info.state != ProcessState.STOPPED:
                        observed_running_during_stream = True

            await asyncio.sleep(0.05)
            t.metrics["inference_result"] = {
                "status_code": stream_status_code,
                "done_marker_observed": done_marker_observed,
                "chunk_count": chunk_count,
            }
            assert stream_status_code == 200
            assert done_marker_observed is True
            assert observed_running_during_stream is False
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            resumed_info = await self._wait_for_restart(supervisor, backend, cooldown)
            assert resumed_info.state == ProcessState.RUNNING
            t.metrics["miner_restarted"] = True
            t.metrics["restarted_pid"] = resumed_info.pid
            t.metrics["restarted_create_time"] = resumed_info.create_time
            t_restarted = time.monotonic()

            await self._verify_restart_mining(
                supervisor=supervisor,
                backend=backend,
                sampler=sampler,
                log_path=log_path,
                t=t,
                t_restarted=t_restarted,
                resumed_info=resumed_info,
            )

            self._record_trial_telemetry(t, telemetry, cooldown)

            # Evaluate 3 verification contracts
            t.process_contract_verified = (
                initial_info.state == ProcessState.RUNNING
                and resumed_info.state == ProcessState.RUNNING
                and resumed_info.pid is not None
            )
            t.inference_arbitration_contract_verified = (
                stream_status_code == 200
                and done_marker_observed is True
                and not observed_running_during_stream
                and telemetry.get("stopped_before_forward_verified") is True
                and telemetry.get("observed_running_during_inference") is False
            )
            t.mining_activity_contract_verified = (
                bool(t.initial_generation and t.initial_generation.get("verified"))
                and bool(t.restart_generation and t.restart_generation.get("verified"))
            ) if self.require_mining_activity else True

            if (
                t.process_contract_verified
                and t.inference_arbitration_contract_verified
                and (t.mining_activity_contract_verified or not self.require_mining_activity)
            ):
                t.status = "PASS"
            else:
                t.status = "FAIL"
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            if initial_info is not None and initial_info.state == ProcessState.RUNNING:
                t.process_contract_verified = True
            logger.exception("Trial 4 failed: %s", exc)
        finally:
            self._finalize_trial_sampler(t, sampler)
            await self._cleanup_trial_harness(
                t, service, system, client, upstream_client, supervisor, backend, telemetry
            )
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_5_error_inhibition(self) -> None:
        """Trial 5 (Mock-only fault injection): Truncated stream latches restart inhibition."""
        t = TrialEvidence(trial_id="T05", name="Error and Truncated Stream Restart Inhibition")
        t.start_monotonic = time.monotonic()
        service = system = client = upstream_client = supervisor = backend = telemetry = None
        try:
            if self.mode == "live":
                raise RuntimeError("Trial 5 uses a synthetic truncated stream handler and is mock-only")

            cooldown = self.cooldown_seconds

            async def truncated_stream_handler(request):
                async def gen():
                    yield b'data: {"choices": [{"delta": {"content": "part"}}]}\n\n'
                    # Abrupt close without [DONE]

                return StreamingResponse(gen(), media_type="text/event-stream")

            service, system, client, upstream_client, supervisor, backend, telemetry = self._build_test_harness(
                trial_id="T05",
                cooldown_seconds=cooldown,
                mock_handler=truncated_stream_handler,
            )
            if not await service.start():
                raise RuntimeError(f"Service failed to start: {service.failure_reason}")

            initial_info = await supervisor.status()
            assert initial_info.state == ProcessState.RUNNING
            t.metrics["initial_pid"] = initial_info.pid
            t.metrics["initial_create_time"] = initial_info.create_time

            model_info = await discover_live_model(client)
            model_id = model_info["model_id"]
            t.metrics["model_id"] = model_id

            resp = await client.post(
                "/v1/chat/completions",
                json={"model": model_id, "messages": [], "stream": True},
            )
            t.metrics["inference_result"] = {
                "status_code": resp.status_code,
                "truncated": "[DONE]" not in resp.text,
            }
            assert resp.status_code == 200
            assert "part" in resp.text

            # Restart MUST be inhibited
            assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True

            # Wait past cooldown duration: miner MUST NOT restart
            await asyncio.sleep(cooldown + 0.05)
            assert (await supervisor.status()).state == ProcessState.STOPPED

            t.metrics["restart_inhibited"] = True
            self._record_trial_telemetry(t, telemetry, cooldown)
            t.status = "PASS"
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            logger.exception("Trial 5 failed: %s", exc)
        finally:
            await self._cleanup_trial_harness(
                t, service, system, client, upstream_client, supervisor, backend, telemetry
            )
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)
