"""Single-task serial pipeline using only benchmark_core models/storage/reports."""

import asyncio
from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import time
from typing import Any
import uuid

from benchmark_core import (RunInfo, TrialResult, append_result, format_utc_timestamp,
                            generate_reports, load_run, save_run, summarize)

from . import __version__
from .git_workspace import ISOLATION_POLICY
from .scratch import SCOPE_POLICY

from .attempt import _write_json, run_attempt, run_cli_attempt
from .bridge import OpenCodeBridge, connected_bridge
from .evidence import EVIDENCE_LIMITS, load_task
from .identity import ModelIdentity, discover_lmstudio_identity
from .lifecycle import (
    DispatchGuard,
    OwnedWorkspace,
    TerminationDecision,
    WorkerHandle,
    cleanup_workspace,
    confirm_termination,
)
from .models_lifecycle import resolve_model_provider_and_key
from .results import base_metrics, trial_from_attempt, unavailable
from .state import command_lock, journal_at, read_pending, release, reserve, reserved_trial


BUDGET_PROFILES: dict[str, dict[str, Any]] = {
    "canonical-120s": {
        "task_seconds": 120.0,
        "grace_seconds": 15.0,
        "comparison_eligible": True,
        "description": "Canonical 120-second observation budget for cross-model multi-turn trials",
    },
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


async def reconcile_pending(
    *,
    state: Path,
    base_url: str = "http://127.0.0.1:4096",
    request_seconds: float = 10,
    connector=connected_bridge,
    lock_held: bool = False,
) -> None:
    """Safely finish an earlier uncertain dispatch before any new work starts.

    This removes only the token-owned pending receipt. Trial evidence and its
    workspace remain available for later inspection.
    """
    state = state.resolve()
    with (nullcontext() if lock_held else command_lock(state)):
        pending = read_pending(state)
        if pending is None:
            return

        evidence_dir = Path(pending["evidence_dir"]).resolve()
        try:
            journal = journal_at(evidence_dir)
            workspace_data = journal.get("workspace")
            if not isinstance(workspace_data, dict):
                raise RuntimeError("lifecycle journal has no owned workspace")
            workspace_root = Path(workspace_data["root"]).resolve()
            workspace_path = Path(workspace_data["path"]).resolve()
            allocation_id = workspace_data["allocation_id"]
            expected_root = (state / "workspaces").resolve()
            if (not isinstance(allocation_id, str) or not allocation_id.startswith("trial-")
                    or workspace_root != expected_root or workspace_path != workspace_root / allocation_id):
                raise RuntimeError("lifecycle workspace is not an exact benchmark-owned allocation")
            termination = journal.get("termination")
            if journal.get("stage") in ("not_submitted", "preflight_failed") or (
                isinstance(termination, dict) and termination.get("confirmed") is True
            ):
                release(state, pending)
                return

            runtime_path = evidence_dir / "runtime.json"
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_provider = runtime.get("provider") if isinstance(runtime, dict) else None
            if not isinstance(runtime_provider, str) or not runtime_provider:
                raise RuntimeError("pending worker provider identity is missing or invalid")
            if runtime_provider in ("gemini", "agy", "codex", "openai", "chatgpt"):
                raise RuntimeError(
                    "pending direct CLI worker has no durable process-start identity; refusing to signal a PID "
                    "that may have been reused"
                )

            git_identity = journal.get("git")
            project_id = git_identity.get("root_commit") if isinstance(git_identity, dict) else None
            raw_handle = journal.get("handle")
            raw_handle = raw_handle if isinstance(raw_handle, dict) else {}
            if (not isinstance(project_id, str) or len(project_id) != 40
                    or any(char not in "0123456789abcdef" for char in project_id)):
                raise RuntimeError("trial Git project identity is missing or invalid")

            stored_workspace = raw_handle.get("workspace")
            if stored_workspace and Path(stored_workspace).resolve() != workspace_path:
                raise RuntimeError("worker handle workspace does not match the owned trial workspace")
            stored_project = raw_handle.get("project_id")
            if stored_project and stored_project != project_id:
                raise RuntimeError("worker handle project does not match the trial Git identity")

            prepared = journal.get("prepared_session")
            prepared = prepared if isinstance(prepared, dict) else {}
            session_id = prepared.get("id") or raw_handle.get("session_id")
            session_directory = prepared.get("directory") or stored_workspace
            prepared_project = prepared.get("projectID") or stored_project or project_id
            if (not isinstance(session_id, str) or not session_id
                    or not isinstance(session_directory, str)
                    or Path(session_directory).resolve() != workspace_path
                    or prepared_project != project_id):
                raise RuntimeError("exact prepared OpenCode session binding is missing")

            prompt_path = evidence_dir / "submitted-prompt.txt"
            prompt = prompt_path.read_text(encoding="utf-8")
            grace_seconds = journal.get("grace_seconds", 10.0)
            if (not isinstance(grace_seconds, (int, float)) or isinstance(grace_seconds, bool)
                    or not math.isfinite(grace_seconds) or grace_seconds <= 0):
                raise RuntimeError("recorded worker confirmation grace period is invalid")

            async with connector(base_url=base_url, request_seconds=request_seconds) as bridge:
                job_id = raw_handle.get("job_id")
                message_id = raw_handle.get("message_id")
                handle_session = raw_handle.get("session_id")
                handle = None
                if (isinstance(job_id, str) and job_id and job_id != "unconfirmed"
                        and isinstance(message_id, str) and message_id
                        and handle_session == session_id):
                    handle = WorkerHandle(job_id, session_id, message_id, workspace_path, project_id)
                    try:
                        decision = await confirm_termination(
                            bridge, handle, grace_seconds=float(grace_seconds), cancel_first=True
                        )
                    except Exception:
                        decision = None
                    if decision is not None and decision.confirmed:
                        recovery_method = "correlated_job_termination"
                        observation_data = asdict(decision.last_observation) if decision.last_observation else None
                        cancellation_requested = decision.cancellation_requested
                    else:
                        # The MCP job receipt can be lost while OpenCode still owns
                        # the exact benchmark-created session. Abort that session
                        # only after bridge validation of its directory/project.
                        await bridge.abort_session(
                            session_id=session_id, workspace=workspace_path, project_id=project_id
                        )
                        _, observation_data = await _confirm_recovered_session(
                            bridge, session_id=session_id, workspace=workspace_path,
                            project_id=project_id, prompt=prompt, handle=handle,
                            grace_seconds=float(grace_seconds),
                        )
                        recovery_method = "session_abort_after_job_reconciliation"
                        cancellation_requested = True
                else:
                    await bridge.abort_session(
                        session_id=session_id, workspace=workspace_path, project_id=project_id
                    )
                    _, observation_data = await _confirm_recovered_session(
                        bridge, session_id=session_id, workspace=workspace_path,
                        project_id=project_id, prompt=prompt, handle=None,
                        grace_seconds=float(grace_seconds),
                    )
                    recovery_method = "prepared_session_abort"
                    cancellation_requested = True

            journal["stage"] = "terminated"
            if not isinstance(termination, dict):
                termination = {}
            termination.update(
                confirmed=True,
                cancellation_requested=cancellation_requested,
                diagnostics=["Prior dispatch safely reconciled before new benchmark work"],
            )
            journal["termination"] = termination
            recovery = {
                "confirmed": True,
                "method": recovery_method,
                "session_id": session_id,
                "project_id": project_id,
                "workspace": str(workspace_path),
                "observation": observation_data,
                "completed_at": format_utc_timestamp(),
            }
            _write_json(evidence_dir / "recovery.json", recovery)
            _write_json(evidence_dir / "lifecycle.json", journal)
            release(state, pending)
        except Exception as error:
            if isinstance(error, RuntimeError) and str(error).startswith("Cannot safely start"):
                raise
            raise RuntimeError(
                "Cannot safely start a new benchmark run because the previous worker dispatch remains unresolved "
                f"and could not be confirmed finished ({type(error).__name__}: {error}). The pending receipt, evidence, "
                f"and workspace are preserved at {evidence_dir}. No new model transition or dispatch was attempted."
            ) from error


async def _confirm_recovered_session(
    bridge: OpenCodeBridge,
    *,
    session_id: str,
    workspace: Path,
    project_id: str,
    prompt: str,
    handle: WorkerHandle | None,
    grace_seconds: float,
) -> tuple[TerminationDecision, dict[str, Any]]:
    deadline = time.monotonic() + grace_seconds
    empty_idle_observations = 0
    last_observation = None
    while True:
        no_submission = False
        if handle is None:
            observation, recovered_handle, attributable, no_submission = await bridge.observe_pending_session(
                session_id=session_id, workspace=workspace, project_id=project_id, prompt=prompt
            )
            if not attributable:
                raise RuntimeError(observation.diagnostic or "prepared session could not be attributed safely")
            if recovered_handle is not None:
                handle = recovered_handle
        else:
            observation = await bridge.observe(handle)
        last_observation = observation
        if no_submission and observation.session_state == "idle":
            empty_idle_observations += 1
        else:
            empty_idle_observations = 0
        if observation.confirms_termination:
            record = asdict(observation)
            return TerminationDecision(
                handle or WorkerHandle("no-submission", session_id, "", workspace, project_id),
                True, True, grace_seconds, grace_seconds - max(0.0, deadline - time.monotonic()),
                observation, ("OpenCode session abort followed by correlated terminal observation",),
            ), record

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if empty_idle_observations >= 3:
                record = asdict(last_observation)
                return TerminationDecision(
                    WorkerHandle("no-submission", session_id, "", workspace, project_id),
                    True, True, grace_seconds, grace_seconds,
                    last_observation, ("Prepared session remained empty and idle through the full confirmation grace",),
                ), record
            detail = last_observation.diagnostic if last_observation else "No fresh session observation"
            raise RuntimeError(f"session abort did not reach confirmed idle termination: {detail}")
        await asyncio.sleep(min(0.25, remaining))


async def run_benchmark(
    task_dir: Path, *, reports: Path, state: Path, model: str, provider: str = "lmstudio",
    agent: str = "local-worker", base_url: str = "http://127.0.0.1:4096", task_seconds: float | None = None,
    budget_profile: str = "canonical-120s",
    grace_seconds: float = 10, request_seconds: float = 10, verifier_seconds: float = 10,
    model_identity: ModelIdentity | None = None,
    inference_profile: dict[str, Any] | None = None,
    connector=connected_bridge,
) -> Path:
    resolved_provider, resolved_model = resolve_model_provider_and_key(model, default_provider=provider)
    task = load_task(task_dir)
    profile_cfg = BUDGET_PROFILES.get(budget_profile, BUDGET_PROFILES["canonical-120s"])
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
    await reconcile_pending(
        state=state, base_url=base_url, request_seconds=request_seconds, connector=connector
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    run_dir = reports / run_id
    evidence_dir = run_dir / "evidence" / "trial-001"
    with reserved_trial(state, evidence_dir) as guard:
        if resolved_provider == "lmstudio" and model_identity is None:
            model_identity = await discover_lmstudio_identity(resolved_model)
        if model_identity is not None and (
            model_identity.provider != resolved_provider or model_identity.runtime_model_id != resolved_model
        ):
            raise ValueError("Resolved model identity does not match the requested provider and runtime model ID")
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
             "evidence_limits": asdict(EVIDENCE_LIMITS),
             "model_identity": model_identity.to_dict() if model_identity else None,
             "requested_inference_profile": inference_profile},
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
                        model_identity=model_identity, inference_profile=inference_profile,
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
