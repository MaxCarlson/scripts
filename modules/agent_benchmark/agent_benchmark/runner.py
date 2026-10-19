"""Single-task serial pipeline using only benchmark_core models/storage/reports."""

import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
from typing import Any
import uuid

from benchmark_core import (RunInfo, TrialResult, append_result, format_utc_timestamp,
                            generate_reports, load_run, save_run, summarize)

from . import __version__
from .git_workspace import ISOLATION_POLICY
from .scratch import SCOPE_POLICY

from .attempt import _write_json, run_attempt, run_cli_attempt
from .bridge import connected_bridge
from .evidence import EVIDENCE_LIMITS, load_task
from .lifecycle import DispatchGuard, OwnedWorkspace, WorkerHandle, cleanup_workspace, confirm_termination
from .models_lifecycle import resolve_model_provider_and_key
from .results import base_metrics, trial_from_attempt, unavailable
from .state import command_lock, journal_at, read_pending, release, reserve, reserved_trial


BUDGET_PROFILES: dict[str, dict[str, Any]] = {
    "canonical-60s": {
        "task_seconds": 60.0,
        "grace_seconds": 10.0,
        "comparison_eligible": True,
        "description": "Canonical 60-second observation budget for cross-model leaderboard comparisons",
    },
    "extended-90s": {
        "task_seconds": 90.0,
        "grace_seconds": 10.0,
        "comparison_eligible": False,
        "description": "Extended 90-second experimental budget for local LLMs and complex reasoning",
    },
    "extended-120s": {
        "task_seconds": 120.0,
        "grace_seconds": 15.0,
        "comparison_eligible": False,
        "description": "Extended 120-second experimental budget for lower-throughput local hardware",
    },
    "extended-180s": {
        "task_seconds": 180.0,
        "grace_seconds": 20.0,
        "comparison_eligible": False,
        "description": "Extended 180-second experimental budget for large quantization or slow local inference",
    },
}


async def run_benchmark(
    task_dir: Path, *, reports: Path, state: Path, model: str, provider: str = "lmstudio",
    agent: str = "local-worker", base_url: str = "http://127.0.0.1:4096", task_seconds: float | None = None,
    budget_profile: str = "canonical-60s",
    grace_seconds: float = 10, request_seconds: float = 10, verifier_seconds: float = 10,
    connector=connected_bridge,
) -> Path:
    resolved_provider, resolved_model = resolve_model_provider_and_key(model, default_provider=provider)
    task = load_task(task_dir)
    profile_cfg = BUDGET_PROFILES.get(budget_profile, BUDGET_PROFILES["canonical-60s"])
    if task_seconds is None:
        effective_task_seconds = profile_cfg["task_seconds"]
        effective_grace_seconds = profile_cfg["grace_seconds"]
        comparison_eligible = profile_cfg["comparison_eligible"]
        effective_profile = budget_profile
    else:
        effective_task_seconds = task_seconds
        effective_grace_seconds = grace_seconds
        comparison_eligible = False if task_seconds != 60.0 else profile_cfg["comparison_eligible"]
        effective_profile = "custom" if task_seconds != 60.0 else budget_profile

    state, reports = state.resolve(), reports.resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    run_dir = reports / run_id
    evidence_dir = run_dir / "evidence" / "trial-001"
    with reserved_trial(state, evidence_dir) as guard:
        cancelled = False
        fingerprint = hashlib.sha256()
        for path in sorted(task.path.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                fingerprint.update(path.relative_to(task.path).as_posix().encode())
                fingerprint.update(hashlib.sha256(path.read_bytes()).digest())
        info = RunInfo(
            run_id, format_utc_timestamp(), "agent-smoke", task.suite_version, [task.task_id],
            {"worker": {"provider": resolved_provider, "model": resolved_model, "role": agent,
                        "effective_context_length": None, "effective_reasoning": None, "warm_state": "unverified"}},
            1, "worker_first_attempt_full_success",
            {"python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine()},
            {"cancel_grace_seconds": effective_grace_seconds, "task_seconds": effective_task_seconds,
             "budget_profile": effective_profile, "comparison_eligible": comparison_eligible,
             "request_seconds": request_seconds, "verifier_seconds": verifier_seconds,
             "suite_fingerprint": fingerprint.hexdigest(), "task_order": [task.task_id], "randomization_seed": None,
             "benchmark_version": __version__, "isolation_policy": ISOLATION_POLICY, "scope_policy": SCOPE_POLICY,
             "evidence_limits": asdict(EVIDENCE_LIMITS)},
        )
        save_run(run_dir, info)
        trial = None
        try:
            if resolved_provider in ("gemini", "codex"):
                evidence = await run_cli_attempt(
                    task, guard, workspace_root=state / "workspaces", evidence_dir=evidence_dir,
                    provider=resolved_provider, model=resolved_model, task_seconds=effective_task_seconds,
                    grace_seconds=effective_grace_seconds, verifier_seconds=verifier_seconds,
                )
            else:
                async with connector(base_url=base_url, request_seconds=request_seconds) as bridge:
                    evidence = await run_attempt(
                        task, bridge, guard, workspace_root=state / "workspaces", evidence_dir=evidence_dir,
                        provider=resolved_provider, model=resolved_model, agent=agent, task_seconds=effective_task_seconds,
                        grace_seconds=effective_grace_seconds, verifier_seconds=verifier_seconds,
                    )
            runtime = json.loads((evidence_dir / "runtime.json").read_text(encoding="utf-8"))
            info = replace(info, metadata={**info.metadata, "runtime": runtime})
            save_run(run_dir, info, overwrite=True)  # Update only this newly owned run.
            trial = trial_from_attempt(evidence, run_id=run_id, trial_id="trial-001", task_id=task.task_id,
                                       variant_id="worker", repetition=1, evidence_path="evidence/trial-001")
        except asyncio.CancelledError:
            cancelled = True
        except Exception as error:  # Top-level execution/transport boundary; never a worker pass.
            failure = type(error).__name__
            if trial is not None:
                trial = replace(trial, details={**trial.details, "transport_close_error": failure})
        if trial is None:
            metrics = base_metrics()
            metrics["agent.worker_first_pass"] = unavailable("boolean", "Infrastructure prevented reliable evaluation")
            for key in ("duration.wall_ms", "duration.worker_ms", "duration.verification_ms"):
                metrics[key] = unavailable("ms", "No completed first-attempt measurement")
            trial = TrialResult(run_id, "trial-001", task.task_id, "worker", 1, "infrastructure_error", metrics,
                                {"execution_error": "CallerCancelled" if cancelled else failure, "scope_policy": SCOPE_POLICY,
                                 "evidence_path": "evidence/trial-001"})
        # Exactly one canonical record per attempted repetition; all reports use core.
        append_result(run_dir, trial)
        generate_reports(summarize(*load_run(run_dir)), run_dir, write=True)
        if cancelled:
            raise asyncio.CancelledError()
        return run_dir

async def cleanup_trial(
    *, state: Path, run_dir: Path | None = None, execute: bool = False,
    base_url: str = "http://127.0.0.1:4096", grace_seconds: float = 10,
    request_seconds: float = 10, connector=connected_bridge,
) -> dict:
    """Preview by default; fresh reconciliation before any owned workspace removal.

    Never rewrite canonical results or scores. An unresolved recovery remains
    blocked across future invocations even if cancellation was acknowledged.
    """
    state = state.resolve()
    pending = read_pending(state)
    evidence_dir = (Path(pending["evidence_dir"]) if pending else
                    (run_dir.resolve() / "evidence/trial-001" if run_dir else None))
    if evidence_dir is None:
        return {"removed": False, "diagnostic": "No pending worker; specify --run-dir for completed workspace cleanup"}
    if run_dir and evidence_dir != run_dir.resolve() / "evidence/trial-001":
        raise RuntimeError("Requested run does not match unresolved pending receipt")
    if not execute:
        return {"removed": False, "execute_required": True, "evidence_dir": str(evidence_dir)}
    with command_lock(state):
        # Reread after acquiring lock; another command may have changed the receipt.
        if read_pending(state) != pending:
            raise RuntimeError("Pending receipt changed; inspect status before cleanup")
        journal = journal_at(evidence_dir)
        data = journal.get("workspace", {})
        workspace = OwnedWorkspace(Path(data["root"]), Path(data["path"]), data["allocation_id"])
        if workspace.root != state / "workspaces":
            raise RuntimeError("Workspace root does not belong to this benchmark state")
        raw = journal.get("handle", {})
        if (journal.get("stage") not in ("not_submitted", "preflight_failed")
                and Path(raw.get("workspace", "")) != workspace.path):
            raise RuntimeError("Recorded handle workspace does not match owned workspace")
        if pending is None:
            pending = reserve(state, evidence_dir)
        if journal.get("stage") in ("not_submitted", "preflight_failed"):
            # No worker was dispatched. Preserve its small diagnostic workspace.
            release(state, pending)
            return {"removed": False, "termination_confirmed": True, "diagnostic": "No worker dispatched; state released"}
        handle = WorkerHandle(raw.get("job_id", ""), raw.get("session_id", ""), raw.get("message_id", ""),
                              workspace.path, raw.get("project_id", ""))
        if journal.get("git") and handle.project_id != journal["git"].get("root_commit"):
            raise RuntimeError("Recorded job project does not match owned trial Git identity")
        if not handle.session_id or not handle.message_id or not handle.job_id:
            raise RuntimeError("Submission ownership unknown; preserve workspace and pending receipt")
        async with connector(base_url=base_url, request_seconds=request_seconds) as bridge:
            decision = await confirm_termination(bridge, handle, grace_seconds=grace_seconds,
                                                 cancel_first=not journal.get("termination", {}).get("confirmed", False))
        DispatchGuard().record(decision)
        journal.update(termination=asdict(decision), stage="terminated" if decision.confirmed else "termination_unresolved")
        _write_json(evidence_dir / "lifecycle.json", journal)
        outcome = cleanup_workspace(workspace, decision)
        _write_json(evidence_dir / "cleanup.json", asdict(outcome))
        if decision.confirmed:
            release(state, pending)
        return {"termination_confirmed": decision.confirmed, **asdict(outcome)}
