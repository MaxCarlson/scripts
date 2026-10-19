"""Single-task serial pipeline using only benchmark_core models/storage/reports."""

import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import uuid

from benchmark_core import (RunInfo, TrialResult, append_result, format_utc_timestamp,
                            generate_reports, load_run, save_run, summarize)

from .attempt import _write_json, run_attempt
from .bridge import connected_bridge
from .evidence import load_task
from .lifecycle import DispatchGuard, OwnedWorkspace, WorkerHandle, cleanup_workspace, confirm_termination
from .results import base_metrics, trial_from_attempt, unavailable
from .state import command_lock, journal_at, read_pending, release, reserve, safely_finished


async def run_benchmark(
    task_dir: Path, *, reports: Path, state: Path, model: str, provider: str = "lmstudio",
    agent: str = "local-worker", base_url: str = "http://127.0.0.1:4096", task_seconds: float | None = None,
    grace_seconds: float = 10, request_seconds: float = 10, verifier_seconds: float = 10,
    connector=connected_bridge,
) -> Path:
    task = load_task(task_dir)
    state, reports = state.resolve(), reports.resolve()
    with command_lock(state):
        if read_pending(state) is not None:
            raise RuntimeError("Unresolved worker blocks dispatch; inspect status/cleanup")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
        run_dir = reports / run_id
        evidence_dir = run_dir / "evidence" / "trial-001"
        receipt = reserve(state, evidence_dir)
        started_attempt = False
        safe = True
        cancelled = False
        try:
            fingerprint = hashlib.sha256()
            for path in sorted(task.path.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    fingerprint.update(path.relative_to(task.path).as_posix().encode())
                    fingerprint.update(hashlib.sha256(path.read_bytes()).digest())
            info = RunInfo(
                run_id, format_utc_timestamp(), "agent-smoke", task.suite_version, [task.task_id],
                {"worker": {"provider": provider, "model": model, "role": agent,
                            "effective_context_length": None, "effective_reasoning": None, "warm_state": "unverified"}},
                1, "worker_first_attempt_full_success",
                {"python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine()},
                {"cancel_grace_seconds": grace_seconds, "task_seconds": task.time_budget_seconds if task_seconds is None else task_seconds,
                 "request_seconds": request_seconds, "verifier_seconds": verifier_seconds,
                 "suite_fingerprint": fingerprint.hexdigest(), "task_order": [task.task_id], "randomization_seed": None},
            )
            save_run(run_dir, info)
            trial = None
            try:
                async with connector(base_url=base_url, request_seconds=request_seconds) as bridge:
                    started_attempt, safe = True, False
                    guard = DispatchGuard()
                    try:
                        evidence = await run_attempt(
                            task, bridge, guard, workspace_root=state / "workspaces", evidence_dir=evidence_dir,
                            provider=provider, model=model, agent=agent, task_seconds=task_seconds,
                            grace_seconds=grace_seconds, verifier_seconds=verifier_seconds,
                        )
                    finally:
                        # Empty/malformed replies say nothing about remote submission.
                        safe = not guard.submission_started
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
                                    {"execution_error": "CallerCancelled" if cancelled else failure,
                                     "evidence_path": "evidence/trial-001"})
            # Exactly one canonical record per attempted repetition; all reports use core.
            append_result(run_dir, trial)
            generate_reports(summarize(*load_run(run_dir)), run_dir, write=True)
            if cancelled:
                raise asyncio.CancelledError()
            return run_dir
        finally:
            if safe or (started_attempt and safely_finished(evidence_dir)):
                release(state, receipt)


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
        handle = WorkerHandle(raw.get("job_id", ""), raw.get("session_id", ""), raw.get("message_id", ""), workspace.path)
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
