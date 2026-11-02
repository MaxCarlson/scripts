"""Persistent, sequential Harbor cohort execution and reporting."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable
from uuid import uuid4

from .harbor import execute_harbor_run, plan_benchmark
from .suite_revision import (
    DatasetRevisionError,
    verify_saved_registry_snapshot,
)

FROZEN_REVISION = "f30b14415dd733c83627204bad0af69a89ceb46f"
DEFAULT_MONITOR_URL = "http://host.docker.internal:8788/v1"
COHORTS: dict[str, dict[str, Any]] = {
    "aider-python-10": {
        "dataset": "aider/aider-polyglot",
        "revision": FROZEN_REVISION,
        "tasks": [
            "polyglot_python_beer-song", "polyglot_python_bottle-song", "polyglot_python_bowling",
            "polyglot_python_dot-dsl", "polyglot_python_pig-latin", "polyglot_python_react",
            "polyglot_python_robot-name", "polyglot_python_transpose",
            "polyglot_python_variable-length-quantity", "polyglot_python_zipper",
        ],
    },
}
_COMPLETED = {"passed", "failed", "timed_out", "infrastructure_invalid"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def load_cohort(cohort: str | None = None, manifest: Path | None = None) -> dict[str, Any]:
    if manifest is not None:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        tasks = data.get("tasks")
        if not isinstance(tasks, list) or not tasks or not all(isinstance(item, str) for item in tasks):
            raise ValueError("custom manifest requires a non-empty string tasks array")
        if len(set(tasks)) != len(tasks):
            raise ValueError("custom manifest task IDs must be unique")
        if not data.get("dataset") or not data.get("source_revision"):
            raise ValueError("custom manifest requires dataset and source_revision")
        return {"id": data.get("id", manifest.stem), "dataset": data["dataset"],
                "revision": data["source_revision"], "tasks": tasks,
                "manifest_path": str(manifest.resolve())}
    if cohort not in COHORTS:
        raise ValueError(f"unknown cohort {cohort!r}; choose one of {sorted(COHORTS)} or use --manifest")
    return {"id": cohort, **COHORTS[cohort]}


def build_manifest(
    *, cohort: str | None = None, manifest: Path | None = None, agent: str, model: str | None,
    base_url: str | None, api_format: str | None, llm_monitor: bool, recording: str,
    jobs: int = 1, monitor_url: str | None = None, monitor_host_url: str | None = None,
    study_adapter: bool = False, prompt_policy_file: Path | None = None,
) -> dict[str, Any]:
    from .spec_verification_policy import BASELINE_ID, load_policy
    if prompt_policy_file is not None:
        study_adapter = True
    if study_adapter and agent.lower() != "opencode":
        raise ValueError("specification verification study requires opencode")
    policy = load_policy(prompt_policy_file)[2] if prompt_policy_file else {"id": BASELINE_ID}
    if jobs != 1:
        raise ValueError("suite execution currently requires sequential -j/--jobs 1")
    if recording not in {"off", "metadata", "content"}:
        raise ValueError("recording must be off, metadata, or content")
    if not llm_monitor and recording != "off":
        raise ValueError("non-off --recording requires -L/--llm-monitor")
    selected = load_cohort(cohort, manifest)
    effective_url = (monitor_url or DEFAULT_MONITOR_URL) if llm_monitor else base_url
    from .suite_monitor import host_monitor_origin
    effective_host_url = host_monitor_origin(effective_url, monitor_host_url) if llm_monitor else None
    effective_format = api_format
    if llm_monitor and agent.lower() in ("opencode", "opencode-v2"):
        if model and not (model.startswith("openai/") or model.startswith("llm-monitor/")):
            raise ValueError(f"{agent} LLM Monitor routing requires an OpenCode openai/<model> provider model")
        selected_monitor_url = monitor_url or DEFAULT_MONITOR_URL
        if base_url and base_url.rstrip("/") != selected_monitor_url.rstrip("/"):
            raise ValueError("explicit --base-url conflicts with required --monitor-url")
        if api_format not in (None, "openai_chat_completions"):
            raise ValueError(f"{agent} LLM Monitor routing requires openai_chat_completions")
        effective_format = "openai_chat_completions"
    elif llm_monitor and effective_format is None:
        raise ValueError("monitored routing requires explicit -A/--api-format for this agent")
    plan = plan_benchmark(
        selected["dataset"], agent=agent, model=model, base_url=effective_url,
        model_api_format=effective_format, task_ids=selected["tasks"], repetitions=1,
        seed=None,
    )
    task_fingerprints = [
        {"task_id": task, "source_revision": selected["revision"],
         "identity_key_sha256": hashlib.sha256(f"{selected['revision']}:{task}".encode()).hexdigest(),
         "content_fingerprint": None}
        for task in plan.selected_tasks
    ]
    effective_agent_model = (
        "llm-monitor/" + model.split("/", 1)[1]
        if llm_monitor and agent.lower() in ("opencode", "opencode-v2") and model else plan.model
    )
    agent_version = "2.2.5" if agent.lower() == "opencode-v2" else ("1.19.5" if agent.lower() == "opencode" else None)
    result: dict[str, Any] = {
        "schema": "agent-benchmark-suite-manifest-v1",
        "cohort": selected["id"], "dataset": selected["dataset"],
        "source_revision": selected["revision"], "tasks": list(plan.selected_tasks),
        "agent": plan.agent, "model": plan.model, "jobs": jobs,
        "scoring_protocol": plan.scoring_protocol, "repetitions": 1, "retries": 0,
        "task_fingerprints": task_fingerprints,
        "provenance": {
            "requested_base_url": base_url,
            "effective_base_url": plan.base_url,
            "monitor_url": (monitor_url or DEFAULT_MONITOR_URL) if llm_monitor else None,
            "monitor_host_url": effective_host_url,
            "llm_monitor_required": llm_monitor,
            "recording_required": recording,
            "requested_api_format": api_format,
            "effective_api_format": plan.model_api_format,
            "effective_agent_model": effective_agent_model,
            "effective_agent_version": agent_version,
            "original_protocol": "openai_responses" if agent.lower() in ("opencode", "opencode-v2") else None,
            "harbor_version": plan.readiness.harbor_version,
            "harbor_dataset": plan.dataset.harbor_dataset,
            "registry_revision_required": (
                selected["dataset"] == "aider/aider-polyglot"
                and selected["revision"] == FROZEN_REVISION
            ),
        },
        "readiness": {
            "is_runnable": plan.readiness.is_runnable and (
                selected["revision"] != FROZEN_REVISION or "0.25.0" in str(plan.readiness.harbor_version)
            ),
            "blockers": list(plan.readiness.blockers) + (
                [f"Frozen aider-python-10 requires Harbor 0.25.0; found {plan.readiness.harbor_version!r}"]
                if selected["revision"] == FROZEN_REVISION and "0.25.0" not in str(plan.readiness.harbor_version)
                else []
            ),
            "harbor_installed": plan.readiness.harbor_installed,
            "docker_available": plan.readiness.docker_available,
            "harbor_version": plan.readiness.harbor_version,
        },
    }
    if study_adapter:
        result["prompt_policy"] = policy
        result["study_adapter"] = "opencode-v1-isolated-v1"
    digest_payload = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["manifest_sha256"] = hashlib.sha256(digest_payload).hexdigest()
    return result


def create_run(
    root: Path, *, cohort: str | None, manifest: Path | None = None, agent: str, model: str | None,
    base_url: str | None, api_format: str | None, llm_monitor: bool, recording: str,
    jobs: int = 1, monitor_url: str | None = None, monitor_host_url: str | None = None,
    planned_manifest: dict[str, Any] | None = None, registry_snapshot: bytes | None = None,
    prompt_policy_file: Path | None = None,
) -> Path:
    plan = planned_manifest or build_manifest(cohort=cohort, manifest=manifest, agent=agent, model=model,
                                               base_url=base_url, api_format=api_format, llm_monitor=llm_monitor,
                                               recording=recording, jobs=jobs, monitor_url=monitor_url,
                                               monitor_host_url=monitor_host_url)
    registry_resolution = plan["provenance"].get("registry_resolution")
    if registry_resolution is not None and registry_snapshot is None:
        raise DatasetRevisionError("verified registry snapshot bytes are missing; no inference was dispatched")
    if registry_snapshot is not None:
        actual_digest = hashlib.sha256(registry_snapshot).hexdigest()
        if registry_resolution is None or actual_digest != registry_resolution.get("registry_sha256"):
            raise DatasetRevisionError("verified registry snapshot digest changed; no inference was dispatched")
    run_id = f"suite-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:10]}"
    run_dir = root.expanduser().resolve() / run_id
    policy_bytes = None
    template_bytes = None
    if plan.get("prompt_policy", {}).get("id") == "sv1-specification-verification-v1":
        from .spec_verification_policy import load_policy
        if prompt_policy_file is None:
            raise ValueError("planned prompt policy file is required")
        policy_bytes, template_bytes, identity = load_policy(prompt_policy_file)
        if identity != plan["prompt_policy"]:
            raise ValueError("prompt policy changed since planning")
    run_dir.mkdir(parents=True, exist_ok=False)
    if policy_bytes is not None:
        policy_dir = run_dir / "policy"
        policy_dir.mkdir()
        (policy_dir / "source.md").write_bytes(policy_bytes)
        (policy_dir / "prompt-template.j2").write_bytes(template_bytes)
    _write_json_atomic(run_dir / "manifest.json", {**plan, "run_id": run_id, "created_at": _now()})
    if registry_snapshot is not None:
        registry_path = run_dir / registry_resolution["registry_path"]
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_bytes(registry_snapshot)
    _write_json_atomic(run_dir / "checkpoint.json", {
        "schema": "agent-benchmark-suite-checkpoint-v1", "run_id": run_id, "state": "planned",
        "created_at": _now(), "updated_at": _now(), "run_dir": str(run_dir),
        "manifest_sha256": plan["manifest_sha256"], "source_revision": plan["source_revision"],
        "study_adapter": plan.get("study_adapter"),
        "cohort": plan["cohort"], "agent": plan["agent"], "model": plan["model"],
        "effective_endpoint": plan["provenance"]["effective_base_url"],
        "effective_api_format": plan["provenance"]["effective_api_format"],
        "monitoring_required": plan["provenance"]["llm_monitor_required"],
        "recording_configuration": plan["provenance"]["recording_required"], "tasks": [
            {"task_id": task, "status": "pending", "trial_id": None,
             "started_at": None, "ended_at": None, "native_artifacts": []}
            for task in plan["tasks"]],
    })
    (run_dir / "logs").mkdir()
    return run_dir


class RunStore:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.manifest = json.loads((self.run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.path = self.run_dir / "checkpoint.json"

    def read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def update_task(self, task_id: str, *, status: str, **fields: Any) -> None:
        if task_id not in self.manifest["tasks"]:
            raise ValueError(f"task {task_id!r} is not in the run manifest")
        checkpoint = self.read()
        record = next(item for item in checkpoint["tasks"] if item["task_id"] == task_id)
        if record["status"] in _COMPLETED and record["status"] != "infrastructure_invalid":
            raise ValueError(f"accepted completed task {task_id!r} cannot be overwritten")
        if record["status"] == "infrastructure_invalid" and status == "running":
            history = list(record.get("attempt_history", []))
            history.append({key: value for key, value in record.items() if key != "attempt_history"})
            fields["attempt_history"] = history
        if record["status"] == "infrastructure_invalid" and status == "infrastructure_invalid":
            history = list(record.get("attempt_history", []))
            history.append({key: value for key, value in record.items() if key != "attempt_history"})
            fields["attempt_history"] = history
        record.update(fields, status=status, updated_at=_now())
        checkpoint["updated_at"] = _now()
        _write_json_atomic(self.path, checkpoint)

    def set_state(self, state: str, **fields: Any) -> None:
        checkpoint = self.read()
        checkpoint.update(fields, state=state, updated_at=_now())
        _write_json_atomic(self.path, checkpoint)


def summarize_run(checkpoint: dict[str, Any]) -> dict[str, Any]:
    tasks = checkpoint["tasks"]
    scored = [item for item in tasks if item["status"] in {"passed", "failed", "timed_out"}]
    passed = sum(item["status"] == "passed" for item in scored)
    failed = sum(item["status"] == "failed" for item in scored)
    invalid = sum(item["status"] == "infrastructure_invalid" for item in tasks)
    durations: list[float] = []
    input_tokens = output_tokens = 0
    token_counts_available = False
    monitor_input_tokens = monitor_output_tokens = 0
    monitor_token_counts_available = False
    monitor_preflight: dict[str, Any] | None = None
    preflight_path = Path(checkpoint.get("run_dir", "")) / "monitor-preflight.json"
    if preflight_path.is_file():
        try:
            monitor_preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            monitor_preflight = None
    for item in tasks:
        for request in item.get("monitor_requests", []):
            for name, target in (("input_tokens", "input"), ("output_tokens", "output")):
                value = request.get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    monitor_token_counts_available = True
                    if target == "input":
                        monitor_input_tokens += value
                    else:
                        monitor_output_tokens += value
        for artifact in item.get("native_artifacts", []):
            trial_file = Path(artifact) / "trials.jsonl"
            if not trial_file.is_file():
                continue
            for line in trial_file.read_text(encoding="utf-8").splitlines():
                trial = json.loads(line)
                if trial.get("task_id") != item["task_id"]:
                    continue
                metrics = trial.get("metrics", {})
                wall = metrics.get("duration.wall_ms", {})
                if isinstance(wall, dict) and isinstance(wall.get("value"), (int, float)):
                    durations.append(float(wall["value"]))
                for name, target in (("tokens.worker.input", "input"), ("tokens.worker.output", "output")):
                    token = metrics.get(name, {})
                    if isinstance(token, dict) and isinstance(token.get("value"), (int, float)):
                        token_counts_available = True
                        if target == "input":
                            input_tokens += int(token["value"])
                        else:
                            output_tokens += int(token["value"])
                break
    return {
        "run_id": checkpoint["run_id"], "state": checkpoint["state"], "planned": len(tasks),
        "cohort": checkpoint.get("cohort"), "source_revision": checkpoint.get("source_revision"),
        "manifest_sha256": checkpoint.get("manifest_sha256"), "agent": checkpoint.get("agent"),
        "model": checkpoint.get("model"), "effective_endpoint": checkpoint.get("effective_endpoint"),
        "effective_api_format": checkpoint.get("effective_api_format"),
        "scored": len(scored), "passed": passed, "failed": failed,
        "timed_out": sum(item["status"] == "timed_out" for item in scored),
        "infrastructure_invalid": invalid,
        "pending": sum(item["status"] == "pending" for item in tasks),
        "pass_rate_pct": round(100 * passed / len(scored), 2) if scored else None,
        "coverage_pct": round(100 * len(scored) / len(tasks), 2) if tasks else 0.0,
        "total_wall_time_ms": round(sum(durations), 2),
        "per_task_latency_ms": {item["task_id"]: item.get("duration_wall_ms") for item in tasks
                                 if item.get("duration_wall_ms") is not None},
        "model_tokens": {"input": input_tokens, "output": output_tokens, "source": "Harbor"}
        if token_counts_available else None,
        "monitor_tokens": {"input": monitor_input_tokens, "output": monitor_output_tokens,
                           "source": "LLM Monitor"} if monitor_token_counts_available else None,
        "telemetry_discrepancies": ([
            {"metric": key, "harbor": harbor_value, "llm_monitor": monitor_value}
            for key, harbor_value, monitor_value in (
                ("input_tokens", input_tokens, monitor_input_tokens),
                ("output_tokens", output_tokens, monitor_output_tokens),
            ) if token_counts_available and monitor_token_counts_available and harbor_value != monitor_value
        ]),
        "monitoring_coverage": {
            "preflight_verified": (monitor_preflight.get("verified") if monitor_preflight else False)
            if checkpoint.get("monitoring_required") else None,
            "tasks_with_observed_requests": sum(bool(item.get("monitor_request_ids")) for item in tasks),
            "planned_tasks": len(tasks),
            "task_request_correlation": "unavailable_without_trustworthy_request_id_link",
        },
        "recording_configuration": checkpoint.get("recording_configuration"),
        "recording_health": ({"healthy": monitor_preflight.get("recording_healthy"),
                              "dropped_observations": monitor_preflight.get("dropped_observations"),
                              "last_error": monitor_preflight.get("recording_error")}
                             if monitor_preflight else None),
        "coordinator_output_tokens": None,
        "coordinator_output_reduction": "not_measured; llm-friendly changes presentation only",
        "tasks": [{key: row.get(key) for key in ("task_id", "status", "trial_id", "started_at", "ended_at",
                                                   "duration_wall_ms", "content_fingerprint", "error_code",
                                                   "native_artifacts", "log", "monitor_request_ids",
                                                   "monitor_requests") if row.get(key) is not None}
                  for row in tasks],
        "checkpoint": str(Path("checkpoint.json")), "manifest": str(Path("manifest.json")),
    }


def _run_one(store: RunStore, task: str) -> dict[str, Any]:
    manifest = store.manifest
    from .suite_output import capture_process_output
    from .suite_monitor import host_monitor_origin, request_snapshot, validate_monitor, verify_recorded_requests
    log_path = store.run_dir / "logs" / f"{task}.log"
    saved: Path | None = None
    started_at = _now()
    store.update_task(task, status="running", started_at=started_at, log=str(log_path))
    try:
        monitor_before = None
        if manifest["provenance"]["llm_monitor_required"]:
            host_url = host_monitor_origin(manifest["provenance"]["monitor_url"],
                                           manifest["provenance"].get("monitor_host_url"))
            monitor_health = validate_monitor(
                agent=manifest["agent"], model=manifest["model"],
                monitor_url=manifest["provenance"]["monitor_url"], monitor_host_url=host_url,
                recording=manifest["provenance"]["recording_required"],
                api_format=manifest["provenance"]["effective_api_format"],
            )
            monitor_before = request_snapshot(monitor_url=host_url)
        plan = plan_benchmark(
            manifest["dataset"], agent=manifest["agent"],
            model=manifest["provenance"].get("effective_agent_model", manifest["model"]),
            base_url=manifest["provenance"]["effective_base_url"],
            model_api_format=manifest["provenance"]["effective_api_format"],
            task_ids=[task], repetitions=1, seed=None,
        )
        output_dir = store.run_dir / "results"
        jobs_dir = store.run_dir / "harbor-jobs"
        registry_path = verify_saved_registry_snapshot(store.run_dir, manifest)
        template_path = None
        if manifest.get("study_adapter"):
            from .spec_verification_policy import verify_frozen_policy
            template_path = verify_frozen_policy(store.run_dir, manifest["prompt_policy"])
        with capture_process_output(log_path):
            saved, summary = execute_harbor_run(
                plan, execute=True, output_dir=output_dir, jobs_dir=jobs_dir,
                n_concurrent=1, quiet=True, registry_path=registry_path,
                study_adapter=bool(manifest.get("study_adapter")), prompt_template_path=template_path,
            )
        status = ("infrastructure_invalid" if summary.get("infrastructure_error", 0) else
                  "passed" if summary.get("passed", 0) else
                  "timed_out" if summary.get("timed_out", 0) else "failed")
        observed_revision = summary.get("dataset_source_revision")
        if observed_revision != manifest["source_revision"]:
            return {"status": "infrastructure_invalid", "trial_id": None, "ended_at": _now(),
                    "summary": summary, "native_artifacts": [str(saved)],
                    "error_code": "SOURCE_REVISION_MISMATCH",
                    "error_detail": f"expected {manifest['source_revision']}; Harbor recorded {observed_revision}"}
        trial_id = None
        duration = content_fingerprint = None
        trials_file = saved / "trials.jsonl"
        if trials_file.is_file():
            for line in trials_file.read_text(encoding="utf-8").splitlines():
                trial = json.loads(line)
                if trial.get("task_id") == task:
                    trial_id = trial.get("trial_id")
                    metric = trial.get("metrics", {}).get("duration.wall_ms", {})
                    duration = metric.get("value") if isinstance(metric, dict) else None
                    content_fingerprint = trial.get("details", {}).get("task_checksum")
                    break
        else:
            duration = content_fingerprint = None
        request_ids: list[str] = []
        recording_coverage = None
        if monitor_before is not None:
            monitor_health_after = validate_monitor(
                agent=manifest["agent"], model=manifest["model"],
                monitor_url=manifest["provenance"]["monitor_url"], monitor_host_url=host_url,
                recording=manifest["provenance"]["recording_required"],
                api_format=manifest["provenance"]["effective_api_format"],
            )
            if monitor_health_after["dropped_observations"] != monitor_health["dropped_observations"]:
                from .suite_monitor import MonitorPreflightError
                raise MonitorPreflightError("monitor dropped observations during the task")
            monitor_after = request_snapshot(monitor_url=host_url)
            previous_ids = set(monitor_before["request_ids"])
            new_requests = [row for row in monitor_after["requests"] if row["request_id"] not in previous_ids]
            request_ids = sorted(row["request_id"] for row in new_requests)
            if not request_ids:
                return {"status": "infrastructure_invalid", "trial_id": trial_id, "ended_at": _now(),
                        "duration_wall_ms": duration, "content_fingerprint": content_fingerprint,
                        "summary": summary, "native_artifacts": [str(saved)],
                        "error_code": "MONITOR_REQUEST_UNOBSERVED",
                        "error_detail": "no new LLM Monitor request ID observed around Harbor task"}
            if manifest["provenance"]["recording_required"] != "off":
                recording_coverage = verify_recorded_requests(
                    monitor_url=host_url, request_ids=request_ids,
                    recording=manifest["provenance"]["recording_required"],
                )
        return {"status": status, "trial_id": trial_id, "ended_at": _now(),
                "duration_wall_ms": duration, "content_fingerprint": content_fingerprint,
                "summary": summary, "native_artifacts": [str(saved)],
                "error_code": "HARBOR_INFRASTRUCTURE_ERROR" if status == "infrastructure_invalid" else None,
                "monitor_request_ids": request_ids,
                "recording_coverage": recording_coverage,
                "monitor_requests": new_requests if monitor_before is not None else []}
    except Exception as error:  # subprocess and result parsing boundary
        with log_path.open("a", encoding="utf-8", errors="replace") as logfile:
            logfile.write(f"{type(error).__name__}: {error}\n")
        from .suite_monitor import MonitorPreflightError
        return {"status": "infrastructure_invalid", "trial_id": None, "ended_at": _now(),
                "error_code": ("MONITOR_CAPTURE_FAILED" if isinstance(error, MonitorPreflightError) else
                               "SOURCE_REVISION_MISMATCH" if isinstance(error, DatasetRevisionError) else
                               "HARBOR_EXECUTION_ERROR"),
                "error_detail": str(error), "native_artifacts": [str(saved)] if saved else []}


def _claim(run_dir: Path) -> Path:
    lock = run_dir / "worker.lock"
    store = RunStore(run_dir)
    if lock.exists():
        try:
            lock_data = json.loads(lock.read_text(encoding="utf-8"))
            import psutil
            if psutil.pid_exists(int(lock_data.get("pid", -1))):
                raise RuntimeError("another worker owns this run")
        except RuntimeError:
            raise
        except Exception:
            pass
        if any(task["status"] == "running" for task in store.read()["tasks"]):
            raise RuntimeError("stale worker lock with a running task; reconcile native Harbor evidence before resume")
        lock.unlink(missing_ok=True)
    if any(task["status"] == "running" for task in store.read()["tasks"]):
        raise RuntimeError("run has an uncertain running task; reconcile native Harbor evidence before resume")
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "started_at": _now()}, handle)
    return lock


def execute_pending(run_dir: Path, *, execute: bool, retry_invalid: bool = False,
                    executor: Callable[[RunStore, str], dict[str, Any]] = _run_one,
                    on_task: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    if not execute:
        raise PermissionError("suite execution requires explicit -x/--execute authorization")
    run_dir = Path(run_dir).resolve()
    lock = _claim(run_dir)
    store = RunStore(run_dir)
    try:
        checkpoint = store.read()
        if checkpoint.get("study_adapter") or store.manifest.get("study_adapter"):
            payload = {key: value for key, value in store.manifest.items()
                       if key not in {"manifest_sha256", "run_id", "created_at"}}
            actual = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if (actual != store.manifest.get("manifest_sha256")
                    or actual != checkpoint.get("manifest_sha256")
                    or checkpoint.get("study_adapter") != store.manifest.get("study_adapter")):
                raise ValueError("study manifest changed; no inference was dispatched")
        should_dispatch = any(
            row["status"] == "pending"
            or (retry_invalid and row["status"] == "infrastructure_invalid"
                and len(row.get("attempt_history", [])) + bool(row.get("error_code")) < 2)
            for row in store.read()["tasks"]
        )
        if should_dispatch and executor is _run_one:
            if store.manifest.get("study_adapter"):
                from .spec_verification_policy import verify_frozen_policy
                verify_frozen_policy(run_dir, store.manifest["prompt_policy"])
            if (store.manifest["provenance"].get("llm_monitor_required")
                    and store.manifest["agent"].lower() in ("opencode", "opencode-v2")
                    and not store.manifest["provenance"].get("effective_agent_model")):
                raise RuntimeError("legacy monitored OpenCode run has no verified provider selector; create a new run")
            verify_saved_registry_snapshot(run_dir, store.manifest)
        store.set_state("running", worker_pid=os.getpid(), started_at=_now())
        for task in store.manifest["tasks"]:
            row = next(item for item in store.read()["tasks"] if item["task_id"] == task)
            retry_count = len(row.get("attempt_history", [])) + bool(row.get("error_code"))
            if row["status"] == "pending" or (retry_invalid and row["status"] == "infrastructure_invalid" and retry_count < 2):
                if store.manifest["provenance"].get("llm_monitor_required"):
                    try:
                        from .suite_recovery import check_task_boundary_recorder
                        monitor_url = store.manifest["provenance"]["monitor_url"]
                        check_task_boundary_recorder(monitor_url=monitor_url)
                    except Exception as rec_err:
                        store.update_task(
                            task,
                            status="infrastructure_invalid",
                            error_code="MONITOR_RECORDER_UNHEALTHY",
                            error_detail=str(rec_err),
                        )
                        break
                attempt = executor(store, task)
                task_status = attempt.pop("status")
                store.update_task(task, status=task_status, **attempt)
                if on_task:
                    on_task({"task": task, "status": task_status,
                             "done": sum(item["status"] in _COMPLETED for item in store.read()["tasks"]),
                             "total": len(store.manifest["tasks"])})
                error_code = attempt.get("error_code") or ""
                if (error_code.startswith("MONITOR_") or error_code in
                        {"SOURCE_REVISION_MISMATCH", "HARBOR_INFRASTRUCTURE_ERROR"}):
                    break
        checkpoint = store.read()
        state = "finished" if not any(row["status"] in {"pending", "running"} for row in checkpoint["tasks"]) else "interrupted"
        finished_at = _now() if state == "finished" else None
        report = summarize_run({**checkpoint, "state": state})
        _write_json_atomic(run_dir / "report.json", report)
        store.set_state(state, finished_at=finished_at)
        return report
    finally:
        lock.unlink(missing_ok=True)


def launch_background(run_dir: Path, *, retry_invalid: bool = False) -> int:
    run_dir = Path(run_dir).resolve()
    launcher_lock = run_dir / "launcher.lock"
    if launcher_lock.exists():
        try:
            owner = json.loads(launcher_lock.read_text(encoding="utf-8"))
            import psutil
            if psutil.pid_exists(int(owner.get("pid", -1))):
                raise RuntimeError("a background launch or worker already owns this run")
        except RuntimeError:
            raise
        except Exception:
            pass
        launcher_lock.unlink(missing_ok=True)
    checkpoint = RunStore(run_dir).read()
    if checkpoint["state"] in {"starting", "running"}:
        pid = checkpoint.get("worker_pid")
        try:
            import psutil
            if pid and psutil.pid_exists(int(pid)):
                raise RuntimeError("a background worker already owns this run")
        except RuntimeError:
            raise
        except Exception:
            pass
    fd = os.open(launcher_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "started_at": _now()}, handle)
    stdout_path = run_dir / "logs" / "worker.stdout.log"
    stderr_path = run_dir / "logs" / "worker.stderr.log"
    stdout = stdout_path.open("ab")
    stderr = stderr_path.open("ab")
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": stdout, "stderr": stderr,
                              "cwd": str(Path.cwd()), "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    RunStore(run_dir).set_state("starting", launcher_pid=os.getpid())
    try:
        RunStore(run_dir).set_state("starting", launcher_pid=os.getpid())
        command = [sys.executable, "-m", "agent_benchmark.suite_worker", str(run_dir), "--execute"]
        if retry_invalid:
            command.append("--retry-invalid")
        proc = subprocess.Popen(command, **kwargs)
        _write_json_atomic(launcher_lock, {"pid": proc.pid, "started_at": _now()})
    except Exception:
        launcher_lock.unlink(missing_ok=True)
        raise
    finally:
        stdout.close()
        stderr.close()
    import time
    deadline = time.monotonic() + 1.0
    checkpoint = RunStore(run_dir)
    while time.monotonic() < deadline:
        if (run_dir / "worker.lock").exists() or checkpoint.read()["state"] in {"running", "finished"}:
            break
        time.sleep(0.02)
    return proc.pid


def status_run(run_dir: Path) -> dict[str, Any]:
    store = RunStore(run_dir)
    checkpoint = store.read()
    result = summarize_run(checkpoint)
    pid = checkpoint.get("worker_pid")
    alive = False
    if pid:
        try:
            import psutil
            alive = psutil.pid_exists(int(pid))
        except (ImportError, ValueError, OSError):
            alive = False
    result.update({"worker_pid": pid, "worker_alive": alive,
                   "worker_lock_present": (Path(run_dir) / "worker.lock").exists(),
                   "logs": str(Path(run_dir) / "logs")})
    if result["state"] in {"starting", "running"} and not alive:
        result["state"] = "interrupted"
        result["recovery_required"] = True
    return result
