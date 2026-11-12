"""Persistent, sequential Harbor cohort execution and reporting."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable
from uuid import uuid4

from .benchmarks.catalog import get_default_catalog
from .harbor import execute_harbor_run, plan_benchmark
from .suite_revision import (
    DatasetRevisionError,
    verify_saved_registry_snapshot,
)

FROZEN_REVISION = "f30b14415dd733c83627204bad0af69a89ceb46f"
DEFAULT_MONITOR_URL = "http://host.docker.internal:8788/v1"


class _CohortsDict(dict):
    """Backward-compatible dictionary facade providing access to registered cohorts."""

    def __getitem__(self, key: str) -> dict[str, Any]:
        c = get_default_catalog().get_cohort(key)
        return {
            "dataset": c.dataset_id,
            "revision": c.source_revision,
            "tasks": list(c.task_ids),
        }

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        try:
            get_default_catalog().get_cohort(key)
            return True
        except KeyError:
            return False

    def __iter__(self):
        return iter(c.id for c in get_default_catalog().list_cohorts())

    def __len__(self) -> int:
        return len(get_default_catalog().list_cohorts())

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def items(self):  # type: ignore[override]
        return [(c.id, self[c.id]) for c in get_default_catalog().list_cohorts()]

    def keys(self):  # type: ignore[override]
        return [c.id for c in get_default_catalog().list_cohorts()]

    def values(self):  # type: ignore[override]
        return [self[c.id] for c in get_default_catalog().list_cohorts()]


COHORTS: dict[str, dict[str, Any]] = _CohortsDict()
_COMPLETED = {"passed", "failed", "timed_out", "infrastructure_invalid"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        for attempt in range(11):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if attempt == 10:
                    raise
                time.sleep(0.02)
    finally:
        temp.unlink(missing_ok=True)


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
        return {
            "id": data.get("id", manifest.stem),
            "dataset": data["dataset"],
            "revision": data["source_revision"],
            "tasks": tasks,
            "task_prompts": data.get("task_prompts", {}),
            "task_metadata": data.get("task_metadata", {}),
            "manifest_path": str(manifest.resolve()),
        }
    if cohort not in COHORTS:
        raise ValueError(f"unknown cohort {cohort!r}; choose one of {sorted(COHORTS)} or use --manifest")
    return {"id": cohort, **COHORTS[cohort]}


def build_manifest(
    *,
    cohort: str | None = None,
    manifest: Path | None = None,
    agent: str,
    model: str | None,
    base_url: str | None,
    api_format: str | None,
    llm_monitor: bool,
    recording: str,
    jobs: int = 1,
    monitor_url: str | None = None,
    monitor_host_url: str | None = None,
    study_adapter: bool = False,
    prompt_policy_file: Path | None = None,
    study_repetition: int | None = None,
    study_seed: int | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    from .spec_verification_policy import BASELINE_ID, load_policy

    if prompt_policy_file is not None:
        study_adapter = True
    if study_adapter and agent.lower() != "opencode":
        raise ValueError("specification verification study requires opencode")
    if study_repetition is not None and study_repetition < 1:
        raise ValueError("study repetition must be positive")
    if not study_adapter and (study_repetition is not None or study_seed is not None):
        raise ValueError("study repetition and seed require the study adapter")
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

    catalog = get_default_catalog()
    cohort_desc = None
    try:
        cohort_desc = catalog.get_cohort(selected["id"])
    except KeyError:
        pass

    effective_backend = backend
    if not effective_backend:
        if cohort_desc and "direct_chat" in cohort_desc.tags:
            effective_backend = "direct_chat"
        else:
            try:
                ds_desc = catalog.resolve_dataset(selected["dataset"])
                b_desc = catalog.get_benchmark(ds_desc.benchmark_id) if ds_desc.benchmark_id else None
                if b_desc and "direct_chat" in b_desc.supported_backends:
                    effective_backend = "direct_chat"
                else:
                    effective_backend = "harbor"
            except (KeyError, AttributeError):
                effective_backend = "harbor"

    if effective_backend in ("direct_chat", "mock"):
        from .benchmarks.loader import resolve_task_prompt_and_metadata

        task_prompts: dict[str, str] = {}
        task_metadata: dict[str, dict[str, Any]] = {}
        custom_tasks_map = selected.get("custom_tasks") if isinstance(selected.get("custom_tasks"), dict) else None

        for task in selected["tasks"]:
            prompt_str = selected.get("task_prompts", {}).get(task, "")
            meta_dict = selected.get("task_metadata", {}).get(task, {})
            if not prompt_str:
                prompt_str, resolved_meta = resolve_task_prompt_and_metadata(
                    selected["dataset"],
                    task,
                    custom_manifest_tasks=custom_tasks_map,
                    cohort_id=selected.get("id"),
                )
                if not meta_dict:
                    meta_dict = resolved_meta
            if not prompt_str and effective_backend == "mock":
                prompt_str = f"Mock prompt for {task}"
            task_prompts[task] = prompt_str
            task_metadata[task] = meta_dict

        task_fingerprints = [
            {
                "task_id": task,
                "source_revision": selected.get("revision", "default"),
                "identity_key_sha256": hashlib.sha256(f"{selected.get('revision', 'default')}:{task}".encode()).hexdigest(),
                "content_fingerprint": hashlib.sha256(task_prompts.get(task, "").encode()).hexdigest() if task_prompts.get(task) else None,
            }
            for task in selected["tasks"]
        ]
        scoring_proto = cohort_desc.scorer_id if cohort_desc and cohort_desc.scorer_id else "mock_scorer"
        is_runnable = bool(model and effective_url)
        blockers = []
        if not is_runnable:
            if not model:
                blockers.append("Direct model execution requires --model")
            if not effective_url:
                blockers.append("Direct model execution requires --base-url")

        # Explicitly check for uninstalled full datasets: full benchmarks must never silently fall back to smoke data
        if selected.get("id") in ("lcb-v6-direct-100", "lcb-v6-direct-full"):
            from .benchmarks.loader import get_lcb_data_path
            if get_lcb_data_path(allow_smoke=False) is None:
                is_runnable = False
                blockers.append(
                    "Full LiveCodeBench dataset not installed. Smoke data cannot be used for 100-task or full cohorts. Run 'agent-benchmark setup install -d livecodebench -x'."
                )

        # Reject direct model execution if prompts cannot be resolved
        missing_prompts = [t for t in selected["tasks"] if not task_prompts.get(t)]
        if missing_prompts and effective_backend == "direct_chat":
            is_runnable = False
            blockers.append(f"Unresolved benchmark prompts for {len(missing_prompts)} tasks: {missing_prompts[:3]}")

        result: dict[str, Any] = {
            "schema": "agent-benchmark-suite-manifest-v1",
            "backend": effective_backend,
            "cohort": selected["id"],
            "dataset": selected["dataset"],
            "source_revision": selected.get("revision", "default"),
            "tasks": list(selected["tasks"]),
            "task_prompts": task_prompts,
            "task_metadata": task_metadata,
            "agent": agent or "direct",
            "model": model,
            "jobs": jobs,
            "scoring_protocol": scoring_proto,
            "repetitions": 1,
            "retries": 0,
            "task_fingerprints": task_fingerprints,
            "provenance": {
                "requested_base_url": base_url,
                "effective_base_url": effective_url,
                "monitor_url": (monitor_url or DEFAULT_MONITOR_URL) if llm_monitor else None,
                "monitor_host_url": effective_host_url,
                "llm_monitor_required": llm_monitor,
                "recording_required": recording,
                "requested_api_format": api_format,
                "effective_api_format": effective_format or "openai_chat_completions",
                "effective_agent_model": model,
                "backend": effective_backend,
                "scoring_protocol": scoring_proto,
            },
            "readiness": {
                "is_runnable": is_runnable,
                "blockers": blockers,
                "backend": effective_backend,
            },
        }
        digest_payload = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        result["manifest_sha256"] = hashlib.sha256(digest_payload).hexdigest()
        return result

    plan = plan_benchmark(
        selected["dataset"],
        agent=agent,
        model=model,
        base_url=effective_url,
        model_api_format=effective_format,
        task_ids=selected["tasks"],
        repetitions=1,
        seed=None,
    )
    task_fingerprints = [
        {
            "task_id": task,
            "source_revision": selected["revision"],
            "identity_key_sha256": hashlib.sha256(f"{selected['revision']}:{task}".encode()).hexdigest(),
            "content_fingerprint": None,
        }
        for task in plan.selected_tasks
    ]
    effective_agent_model = (
        "llm-monitor/" + model.split("/", 1)[1]
        if llm_monitor and agent.lower() in ("opencode", "opencode-v2") and model
        else plan.model
    )
    agent_version = "2.2.5" if agent.lower() == "opencode-v2" else ("1.19.5" if agent.lower() == "opencode" else None)
    result: dict[str, Any] = {
        "schema": "agent-benchmark-suite-manifest-v1",
        "backend": "harbor",
        "cohort": selected["id"],
        "dataset": selected["dataset"],
        "source_revision": selected["revision"],
        "tasks": list(plan.selected_tasks),
        "agent": plan.agent,
        "model": plan.model,
        "jobs": jobs,
        "scoring_protocol": plan.scoring_protocol,
        "repetitions": 1,
        "retries": 0,
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
            "effective_agent_version": None if study_adapter else agent_version,
            **({"requested_agent_version": "1.19.5"} if study_adapter else {}),
            "original_protocol": "openai_responses" if agent.lower() in ("opencode", "opencode-v2") else None,
            "harbor_version": plan.readiness.harbor_version,
            "harbor_dataset": plan.dataset.harbor_dataset,
            "registry_revision_required": (
                selected["dataset"] == "aider/aider-polyglot" and selected["revision"] == FROZEN_REVISION
            ),
        },
        "readiness": {
            "is_runnable": plan.readiness.is_runnable
            and (
                (selected["revision"] != FROZEN_REVISION and not study_adapter)
                or "0.25.0" in str(plan.readiness.harbor_version)
            ),
            "blockers": list(plan.readiness.blockers)
            + (
                [f"Frozen aider-python-10 requires Harbor 0.25.0; found {plan.readiness.harbor_version!r}"]
                if (selected["revision"] == FROZEN_REVISION or study_adapter)
                and "0.25.0" not in str(plan.readiness.harbor_version)
                else []
            ),
            "harbor_installed": plan.readiness.harbor_installed,
            "docker_available": plan.readiness.docker_available,
            "harbor_version": plan.readiness.harbor_version,
        },
    }
    if study_adapter:
        from .study_network_policy import NETWORK_POLICY, NETWORK_POLICY_ID

        result["prompt_policy"] = policy
        result["study_adapter"] = "opencode-v1-isolated-v1"
        result["study_web_access"] = {
            "native_web_tools": "deny-requested",
            "network_policy_id": NETWORK_POLICY_ID,
            "network_policy": NETWORK_POLICY,
            "network_enforcement": "requested; requires effective Docker sidecar qualification",
        }
        result["provenance"]["study_network"] = {
            "policy_id": NETWORK_POLICY_ID,
            "network_policy": NETWORK_POLICY,
            "enforcement_state": "planned",
            "task_snapshots": {},
        }
        result["study_design"] = {
            "id": "spec-verification-pilot-v1",
            "repetition": study_repetition,
            "randomization_seed": study_seed,
        }
    digest_payload = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["manifest_sha256"] = hashlib.sha256(digest_payload).hexdigest()
    return result


def create_run(
    root: Path,
    *,
    cohort: str | None,
    manifest: Path | None = None,
    agent: str,
    model: str | None,
    base_url: str | None,
    api_format: str | None,
    llm_monitor: bool,
    recording: str,
    jobs: int = 1,
    monitor_url: str | None = None,
    monitor_host_url: str | None = None,
    planned_manifest: dict[str, Any] | None = None,
    registry_snapshot: bytes | None = None,
    prompt_policy_file: Path | None = None,
    study_adapter: bool = False,
    study_repetition: int | None = None,
    study_seed: int | None = None,
    backend: str | None = None,
) -> Path:
    plan = planned_manifest or build_manifest(
        cohort=cohort,
        manifest=manifest,
        agent=agent,
        model=model,
        base_url=base_url,
        api_format=api_format,
        llm_monitor=llm_monitor,
        recording=recording,
        jobs=jobs,
        monitor_url=monitor_url,
        monitor_host_url=monitor_host_url,
        study_adapter=study_adapter,
        prompt_policy_file=prompt_policy_file,
        study_repetition=study_repetition,
        study_seed=study_seed,
        backend=backend,
    )
    plan = dict(plan)
    plan["provenance"] = dict(plan.get("provenance", {}))
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
    if plan.get("study_adapter"):
        from .study_network_policy import NETWORK_POLICY, NETWORK_POLICY_ID, materialize_study_task_snapshot
        from .study_task_integrity import verify_study_task_trees

        verified_trees = verify_study_task_trees(plan)
        resolution_rows = {
            row["task_id"]: row for row in plan.get("provenance", {}).get("registry_resolution", {}).get("tasks", [])
        }
        verified_rows = {row["task_id"]: row for row in verified_trees}
        if set(resolution_rows) != set(plan["tasks"]) or set(verified_rows) != set(plan["tasks"]):
            raise DatasetRevisionError("verified study task source set is incomplete; no inference was dispatched")
        snapshots: dict[str, dict[str, Any]] = {}
        for task_id in plan["tasks"]:
            source = resolution_rows[task_id]
            verified = verified_rows[task_id]
            snapshots[task_id] = materialize_study_task_snapshot(
                run_dir=run_dir,
                source_path=Path(verified["task_root"]),
                task_id=task_id,
                source_revision=source["git_commit_id"],
                source_git_url=source["git_url"],
                original_task_sha256=verified["task_sha256"],
                original_verifier_sha256=verified["verifier_sha256"],
            )
        plan["provenance"]["study_network"] = {
            "policy_id": NETWORK_POLICY_ID,
            "network_policy": NETWORK_POLICY,
            "enforcement_state": "declared in run-owned Harbor task metadata; effective enforcement must be container-qualified",
            "task_snapshots": snapshots,
        }
        digest_payload = {key: value for key, value in plan.items() if key != "manifest_sha256"}
        plan["manifest_sha256"] = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
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
    _write_json_atomic(
        run_dir / "checkpoint.json",
        {
            "schema": "agent-benchmark-suite-checkpoint-v1",
            "run_id": run_id,
            "state": "planned",
            "created_at": _now(),
            "updated_at": _now(),
            "run_dir": str(run_dir),
            "manifest_sha256": plan["manifest_sha256"],
            "backend": plan.get("backend", "harbor"),
            "source_revision": plan["source_revision"],
            **({"study_adapter": plan["study_adapter"]} if plan.get("study_adapter") else {}),
            "cohort": plan["cohort"],
            "agent": plan["agent"],
            "model": plan["model"],
            "effective_endpoint": plan["provenance"]["effective_base_url"],
            "effective_api_format": plan["provenance"]["effective_api_format"],
            "monitoring_required": plan["provenance"]["llm_monitor_required"],
            "recording_configuration": plan["provenance"]["recording_required"],
            "tasks": [
                {
                    "task_id": task,
                    "status": "pending",
                    "trial_id": None,
                    "started_at": None,
                    "ended_at": None,
                    "native_artifacts": [],
                }
                for task in plan["tasks"]
            ],
        },
    )
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
        if not item.get("native_artifacts"):
            wall_ms = item.get("duration_wall_ms")
            if isinstance(wall_ms, (int, float)):
                durations.append(float(wall_ms))
            tc = item.get("token_counts")
            if isinstance(tc, dict):
                token_counts_available = True
                input_tokens += int(tc.get("input", 0))
                output_tokens += int(tc.get("output", 0))
    return {
        "run_id": checkpoint["run_id"],
        "state": checkpoint["state"],
        "planned": len(tasks),
        "cohort": checkpoint.get("cohort"),
        "source_revision": checkpoint.get("source_revision"),
        "manifest_sha256": checkpoint.get("manifest_sha256"),
        "agent": checkpoint.get("agent"),
        "model": checkpoint.get("model"),
        "effective_endpoint": checkpoint.get("effective_endpoint"),
        "effective_api_format": checkpoint.get("effective_api_format"),
        "scored": len(scored),
        "passed": passed,
        "failed": failed,
        "timed_out": sum(item["status"] == "timed_out" for item in scored),
        "infrastructure_invalid": invalid,
        "pending": sum(item["status"] == "pending" for item in tasks),
        "pass_rate_pct": round(100 * passed / len(scored), 2) if scored else None,
        "coverage_pct": round(100 * len(scored) / len(tasks), 2) if tasks else 0.0,
        "total_wall_time_ms": round(sum(durations), 2),
        "per_task_latency_ms": {
            item["task_id"]: item.get("duration_wall_ms") for item in tasks if item.get("duration_wall_ms") is not None
        },
        "model_tokens": {"input": input_tokens, "output": output_tokens, "source": "Harbor"}
        if token_counts_available
        else None,
        "monitor_tokens": {"input": monitor_input_tokens, "output": monitor_output_tokens, "source": "LLM Monitor"}
        if monitor_token_counts_available
        else None,
        "telemetry_discrepancies": (
            [
                {"metric": key, "harbor": harbor_value, "llm_monitor": monitor_value}
                for key, harbor_value, monitor_value in (
                    ("input_tokens", input_tokens, monitor_input_tokens),
                    ("output_tokens", output_tokens, monitor_output_tokens),
                )
                if token_counts_available and monitor_token_counts_available and harbor_value != monitor_value
            ]
        ),
        "monitoring_coverage": {
            "preflight_verified": (monitor_preflight.get("verified") if monitor_preflight else False)
            if checkpoint.get("monitoring_required")
            else None,
            "tasks_with_observed_requests": sum(bool(item.get("monitor_request_ids")) for item in tasks),
            "planned_tasks": len(tasks),
            "task_request_correlation": "unavailable_without_trustworthy_request_id_link",
        },
        "recording_configuration": checkpoint.get("recording_configuration"),
        "recording_health": (
            {
                "healthy": monitor_preflight.get("recording_healthy"),
                "dropped_observations": monitor_preflight.get("dropped_observations"),
                "last_error": monitor_preflight.get("recording_error"),
            }
            if monitor_preflight
            else None
        ),
        "coordinator_output_tokens": None,
        "coordinator_output_reduction": "not_measured; llm-friendly changes presentation only",
        "tasks": [
            {
                key: row.get(key)
                for key in (
                    "task_id",
                    "status",
                    "trial_id",
                    "started_at",
                    "ended_at",
                    "duration_wall_ms",
                    "content_fingerprint",
                    "error_code",
                    "native_artifacts",
                    "log",
                    "monitor_request_ids",
                    "monitor_requests",
                )
                if row.get(key) is not None
            }
            for row in tasks
        ],
        "checkpoint": str(Path("checkpoint.json")),
        "manifest": str(Path("manifest.json")),
    }


def _run_one_generic(store: RunStore, task: str, *, backend_id: str) -> dict[str, Any]:
    """Execute a task attempt through a generic backend and scoring adapter."""
    from .execution import (
        ExecutionPlan,
        ResultNormalizer,
        TaskContext,
        get_backend,
        get_scorer,
    )

    manifest = store.manifest
    log_path = store.run_dir / "logs" / f"{task}.log"
    started_at = _now()
    store.update_task(
        task,
        status="running",
        started_at=started_at,
        log=str(log_path),
    )

    try:
        backend = get_backend(backend_id)
        scorer_id = manifest.get("scoring_protocol") or "mock_scorer"
        scorer = get_scorer(scorer_id)

        plan = ExecutionPlan(
            backend_id=backend_id,
            benchmark_id=manifest.get("dataset", "").split("/")[0],
            dataset_id=manifest.get("dataset", ""),
            task_ids=tuple(manifest.get("tasks", ())),
            cohort_id=manifest.get("cohort"),
            source_revision=manifest.get("source_revision"),
            scorer_id=scorer_id,
            model_id=manifest.get("model"),
            base_url=manifest.get("provenance", {}).get("effective_base_url"),
            api_format=manifest.get("provenance", {}).get("effective_api_format"),
        )

        task_prompt = manifest.get("task_prompts", {}).get(task)
        task_meta = manifest.get("task_metadata", {}).get(task) or {}

        # If prompt is still missing or placeholder, attempt dynamic resolution
        if not task_prompt:
            from .benchmarks.loader import resolve_task_prompt_and_metadata
            dyn_prompt, dyn_meta = resolve_task_prompt_and_metadata(manifest.get("dataset", ""), task)
            if dyn_prompt:
                task_prompt = dyn_prompt
                if not task_meta:
                    task_meta = dyn_meta
            elif backend_id == "mock":
                task_prompt = f"Mock prompt for {task}"

        # Reject empty or placeholder prompts before model dispatch
        if not task_prompt or not task_prompt.strip() or task_prompt == f"Solve task: {task}":
            return {
                "status": "infrastructure_invalid",
                "trial_id": None,
                "ended_at": _now(),
                "error_code": "MISSING_BENCHMARK_DATA",
                "error_detail": f"Direct model dispatch blocked: benchmark prompt for task '{task}' is missing or empty",
            }

        context = TaskContext(
            task_id=task,
            prompt=task_prompt,
            metadata=task_meta,
        )

        attempt = backend.execute_task(task, context, plan)
        scored = scorer.score_task(task, attempt, context)

        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(f"Task: {task}\n")
            lf.write(f"Backend: {backend_id}\n")
            lf.write(f"Status: {attempt.status}\n")
            lf.write(f"Duration: {attempt.duration_ms}ms | Tokens: {attempt.input_tokens}/{attempt.output_tokens}\n")
            if attempt.error_detail:
                lf.write(f"Error: {attempt.error_detail}\n")
            lf.write(f"Scorer: {scorer_id} -> {scored.status} (score={scored.score})\n")

        return ResultNormalizer.to_store_task_record(scored, attempt)

    except Exception as exc:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", errors="replace") as lf:
            lf.write(f"{type(exc).__name__}: {exc}\n")
        return {
            "status": "infrastructure_invalid",
            "trial_id": None,
            "ended_at": _now(),
            "error_code": "EXECUTION_BACKEND_ERROR",
            "error_detail": str(exc),
        }


def _run_one(store: RunStore, task: str) -> dict[str, Any]:
    manifest = store.manifest
    backend_id = manifest.get("backend", "harbor")
    if backend_id in ("direct_chat", "mock"):
        return _run_one_generic(store, task, backend_id=backend_id)

    from .suite_output import capture_process_output
    from .suite_monitor import host_monitor_origin, request_snapshot, validate_monitor, verify_recorded_requests

    log_path = store.run_dir / "logs" / f"{task}.log"
    saved: Path | None = None
    started_at = _now()
    store.update_task(
        task,
        status="running",
        started_at=started_at,
        log=str(log_path),
        **({"prompt_policy": manifest["prompt_policy"]} if manifest.get("study_adapter") else {}),
    )
    try:
        monitor_before = None
        if manifest["provenance"]["llm_monitor_required"]:
            host_url = host_monitor_origin(
                manifest["provenance"]["monitor_url"], manifest["provenance"].get("monitor_host_url")
            )
            monitor_health = validate_monitor(
                agent=manifest["agent"],
                model=manifest["model"],
                monitor_url=manifest["provenance"]["monitor_url"],
                monitor_host_url=host_url,
                recording=manifest["provenance"]["recording_required"],
                api_format=manifest["provenance"]["effective_api_format"],
            )
            monitor_before = request_snapshot(monitor_url=host_url)
        plan = plan_benchmark(
            manifest["dataset"],
            agent=manifest["agent"],
            model=manifest["provenance"].get("effective_agent_model", manifest["model"]),
            base_url=manifest["provenance"]["effective_base_url"],
            model_api_format=manifest["provenance"]["effective_api_format"],
            task_ids=[task],
            repetitions=1,
            seed=None,
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
                plan,
                execute=True,
                output_dir=output_dir,
                jobs_dir=jobs_dir,
                n_concurrent=1,
                quiet=True,
                registry_path=registry_path,
                study_adapter=bool(manifest.get("study_adapter")),
                prompt_template_path=template_path,
                study_policy=manifest.get("prompt_policy"),
                study_design=manifest.get("study_design"),
                study_manifest=manifest if manifest.get("study_adapter") else None,
                study_run_dir=store.run_dir if manifest.get("study_adapter") else None,
            )
        status = (
            "infrastructure_invalid"
            if summary.get("infrastructure_error", 0)
            else "passed"
            if summary.get("passed", 0)
            else "timed_out"
            if summary.get("timed_out", 0)
            else "failed"
        )
        observed_revision = summary.get("dataset_source_revision")
        if observed_revision != manifest["source_revision"]:
            return {
                "status": "infrastructure_invalid",
                "trial_id": None,
                "ended_at": _now(),
                "summary": summary,
                "native_artifacts": [str(saved)],
                "error_code": "SOURCE_REVISION_MISMATCH",
                "error_detail": f"expected {manifest['source_revision']}; Harbor recorded {observed_revision}",
            }
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
                agent=manifest["agent"],
                model=manifest["model"],
                monitor_url=manifest["provenance"]["monitor_url"],
                monitor_host_url=host_url,
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
                return {
                    "status": "infrastructure_invalid",
                    "trial_id": trial_id,
                    "ended_at": _now(),
                    "duration_wall_ms": duration,
                    "content_fingerprint": content_fingerprint,
                    "summary": summary,
                    "native_artifacts": [str(saved)],
                    "error_code": "MONITOR_REQUEST_UNOBSERVED",
                    "error_detail": "no new LLM Monitor request ID observed around Harbor task",
                }
            if manifest["provenance"]["recording_required"] != "off":
                recording_coverage = verify_recorded_requests(
                    monitor_url=host_url,
                    request_ids=request_ids,
                    recording=manifest["provenance"]["recording_required"],
                )
        return {
            "status": status,
            "trial_id": trial_id,
            "ended_at": _now(),
            "duration_wall_ms": duration,
            "content_fingerprint": content_fingerprint,
            "summary": summary,
            "native_artifacts": [str(saved)],
            "error_code": "HARBOR_INFRASTRUCTURE_ERROR" if status == "infrastructure_invalid" else None,
            "monitor_request_ids": request_ids,
            "recording_coverage": recording_coverage,
            "monitor_requests": new_requests if monitor_before is not None else [],
        }
    except Exception as error:  # subprocess and result parsing boundary
        with log_path.open("a", encoding="utf-8", errors="replace") as logfile:
            logfile.write(f"{type(error).__name__}: {error}\n")
        from .suite_monitor import MonitorPreflightError

        return {
            "status": "infrastructure_invalid",
            "trial_id": None,
            "ended_at": _now(),
            "error_code": (
                "MONITOR_CAPTURE_FAILED"
                if isinstance(error, MonitorPreflightError)
                else "SOURCE_REVISION_MISMATCH"
                if isinstance(error, DatasetRevisionError)
                else "HARBOR_EXECUTION_ERROR"
            ),
            "error_detail": str(error),
            "native_artifacts": [str(saved)] if saved else [],
        }


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


def execute_pending(
    run_dir: Path,
    *,
    execute: bool,
    retry_invalid: bool = False,
    executor: Callable[[RunStore, str], dict[str, Any]] = _run_one,
    on_task: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not execute:
        raise PermissionError("suite execution requires explicit -x/--execute authorization")
    run_dir = Path(run_dir).resolve()
    lock = _claim(run_dir)
    store = RunStore(run_dir)
    try:
        checkpoint = store.read()
        if checkpoint.get("study_adapter") or store.manifest.get("study_adapter"):
            payload = {
                key: value
                for key, value in store.manifest.items()
                if key not in {"manifest_sha256", "run_id", "created_at"}
            }
            actual = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if (
                actual != store.manifest.get("manifest_sha256")
                or actual != checkpoint.get("manifest_sha256")
                or checkpoint.get("run_id") != store.manifest.get("run_id")
                or checkpoint.get("study_adapter") != store.manifest.get("study_adapter")
            ):
                raise ValueError("study manifest changed; no inference was dispatched")
        should_dispatch = any(
            row["status"] == "pending"
            or (
                retry_invalid
                and row["status"] == "infrastructure_invalid"
                and len(row.get("attempt_history", [])) + bool(row.get("error_code")) < 2
            )
            for row in store.read()["tasks"]
        )
        if should_dispatch and store.manifest.get("study_adapter"):
            from .spec_verification_policy import verify_frozen_policy

            verify_frozen_policy(run_dir, store.manifest["prompt_policy"])
        if should_dispatch and executor is _run_one and store.manifest.get("study_adapter"):
            from .network_receipt import validate_receipt

            validate_receipt(run_dir, store.manifest)
        if should_dispatch and executor is _run_one and store.manifest.get("backend", "harbor") == "harbor":
            if (
                store.manifest["provenance"].get("llm_monitor_required")
                and store.manifest["agent"].lower() in ("opencode", "opencode-v2")
                and not store.manifest["provenance"].get("effective_agent_model")
            ):
                raise RuntimeError("legacy monitored OpenCode run has no verified provider selector; create a new run")
            verify_saved_registry_snapshot(run_dir, store.manifest)
        store.set_state("running", worker_pid=os.getpid(), started_at=_now())
        for task in store.manifest["tasks"]:
            row = next(item for item in store.read()["tasks"] if item["task_id"] == task)
            retry_count = len(row.get("attempt_history", [])) + bool(row.get("error_code"))
            if row["status"] == "pending" or (
                retry_invalid and row["status"] == "infrastructure_invalid" and retry_count < 2
            ):
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
                    on_task(
                        {
                            "task": task,
                            "status": task_status,
                            "done": sum(item["status"] in _COMPLETED for item in store.read()["tasks"]),
                            "total": len(store.manifest["tasks"]),
                        }
                    )
                error_code = attempt.get("error_code") or ""
                if error_code.startswith("MONITOR_") or error_code in {
                    "SOURCE_REVISION_MISMATCH",
                    "HARBOR_INFRASTRUCTURE_ERROR",
                }:
                    break
        checkpoint = store.read()
        state = (
            "finished"
            if not any(row["status"] in {"pending", "running"} for row in checkpoint["tasks"])
            else "interrupted"
        )
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
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": stdout,
        "stderr": stderr,
        "cwd": str(Path.cwd()),
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        RunStore(run_dir).set_state("starting", launcher_pid=os.getpid(), worker_pid=None)
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
    if not pid and checkpoint.get("state") == "starting":
        try:
            launcher = json.loads((Path(run_dir) / "launcher.lock").read_text(encoding="utf-8"))
            pid = launcher.get("pid") or checkpoint.get("launcher_pid")
        except FileNotFoundError:
            pid = None
        except (OSError, ValueError, TypeError):
            pid = checkpoint.get("launcher_pid")
    alive = False
    if pid:
        try:
            import psutil

            alive = psutil.pid_exists(int(pid))
        except (ImportError, ValueError, OSError):
            alive = False
    result.update(
        {
            "worker_pid": pid,
            "worker_alive": alive,
            "worker_lock_present": (Path(run_dir) / "worker.lock").exists(),
            "logs": str(Path(run_dir) / "logs"),
        }
    )
    if result["state"] in {"starting", "running"} and not alive:
        result["state"] = "interrupted"
        result["recovery_required"] = True
    return result
