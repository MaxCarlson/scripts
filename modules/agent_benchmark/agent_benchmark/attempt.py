"""One first worker attempt, yielding immutable evidence for canonical integration.

No retry, repair, result serialization or report rendering lives here. The core
integration layer must later consume these facts to emit exactly one TrialResult.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import difflib
import json
import math
from pathlib import Path
import time

import httpx

from .bridge import OpenCodeBridge
from .evidence import (ScopeAudit, Snapshot, Task, Verification, audit_scope,
                       capture, changed_paths, prepare_workspace, verify)
from .lifecycle import DispatchGuard, OwnedWorkspace, TerminationDecision, WorkerHandle, confirm_termination


@dataclass(frozen=True)
class AttemptEvidence:
    """Internal evidence references, deliberately not a benchmark result contract."""

    workspace: OwnedWorkspace
    termination: TerminationDecision
    s0: Snapshot
    s1: Snapshot | None
    verification: Verification | None
    changed_paths: tuple[str, ...]
    scope_violations: tuple[str, ...]
    task_budget_expired: bool
    execution_error: str | None
    worker_ms: float
    wall_ms: float
    scope_audit: ScopeAudit | None = None


def _write_json(path: Path, data: object) -> None:
    # Evidence journaling only: canonical run/trial serialization belongs to core.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _unresolved(handle: WorkerHandle, grace: float, reason: str) -> TerminationDecision:
    return TerminationDecision(handle, False, False, grace, 0, None, (reason,))


def _patch(before: Snapshot, after: Snapshot) -> str:
    chunks: list[str] = []
    for name in changed_paths(before, after):
        old, new = before.files.get(name, b""), after.files.get(name, b"")
        try:
            left, right = old.decode("utf-8"), new.decode("utf-8")
            chunks.extend(difflib.unified_diff(left.splitlines(keepends=True), right.splitlines(keepends=True),
                                             fromfile=f"S0/{name}", tofile=f"S1/{name}"))
        except UnicodeDecodeError:
            chunks.append(f"Binary file differs: {name}; exact bytes retained in checkpoints\n")
    return "".join(chunks)


async def run_attempt(
    task: Task,
    bridge: OpenCodeBridge,
    guard: DispatchGuard,
    *,
    workspace_root: Path,
    evidence_dir: Path,
    provider: str,
    model: str,
    agent: str,
    task_seconds: float | None = None,
    grace_seconds: float = 10,
    poll_seconds: float = 0.1,
    verifier_seconds: float = 10,
) -> AttemptEvidence:
    """Dispatch once and freeze S1 only after fresh termination confirmation.

    An unresolved submission/worker returns no S1 or verification. DispatchGuard
    then stops subsequent attempts. Keep this guard for the whole batch. Cleanup
    is a separate explicit operation; this function always retains the workspace.
    Preflight errors occur before dispatch and propagate with diagnostic evidence.
    """
    budget = task.time_budget_seconds if task_seconds is None else task_seconds
    for name, value in (("task_seconds", budget), ("grace_seconds", grace_seconds),
                        ("poll_seconds", poll_seconds), ("verifier_seconds", verifier_seconds)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    # Reserve evidence first; refuse to reuse old trial directories before creating resources.
    evidence_dir.mkdir(parents=True, exist_ok=False)
    workspace = guard.allocate(workspace_root)
    git_identity = prepare_workspace(task, workspace.path)
    s0 = capture(workspace.path, evidence_dir / "S0")
    # Worker processes belong to OpenCode's shared process tree, not local subprocess
    # supervision; owned_pids is intentionally empty.
    journal = {"stage": "not_submitted", "workspace": asdict(workspace), "task_seconds": budget,
               "grace_seconds": grace_seconds, "verifier_seconds": verifier_seconds, "owned_pids": [],
               "git": asdict(git_identity)}
    _write_json(evidence_dir / "lifecycle.json", journal)
    try:
        configuration = await bridge.preflight(workspace.path, provider=provider, model=model, agent=agent,
                                               project_id=git_identity.root_commit)
        prepared_session = await bridge.prepare_session(workspace.path, project_id=git_identity.root_commit)
        configuration.update(git=asdict(git_identity), session=prepared_session)
        journal["prepared_session"] = prepared_session
        _write_json(evidence_dir / "session-preflight.json", getattr(bridge, "session_evidence", prepared_session))
        _write_json(evidence_dir / "lifecycle.json", journal)
    except Exception as error:
        journal.update(stage="preflight_failed", diagnostic=type(error).__name__)
        session_evidence = getattr(bridge, "session_evidence", {})
        if session_evidence:
            _write_json(evidence_dir / "session-preflight.json", session_evidence)
        _write_json(evidence_dir / "lifecycle.json", journal)
        raise
    _write_json(evidence_dir / "runtime.json", configuration)
    handle = None
    task_budget_expired = False
    execution_error = None
    start = time.monotonic()
    journal["stage"] = "dispatching"
    _write_json(evidence_dir / "lifecycle.json", journal)
    prompt = (task.instruction + "\n\nWorkspace: " + str(workspace.path)
              + "\nUse only the allowed paths. Do not spawn background processes or install packages. "
              "For Python checks, disable bytecode writes (-B or PYTHONDONTWRITEBYTECODE=1). "
              "Return a JSON completion report with outcome, summary, changed_paths, checks, evidence and blockers. "
              "Report only checks you actually ran. Stop after your first attempt; do not request a retry.")
    decision = None
    dispatch_started = False
    try:
        observation_budget = asyncio.timeout(budget)
        try:
            async with observation_budget:
                dispatch_started = True
                guard.submission_started = True
                handle = await bridge.dispatch(workspace.path, prompt, provider=provider, model=model, agent=agent)
                journal.update(stage="observing", handle=asdict(handle))
                # Persist recovery ownership before writing secondary receipt evidence.
                _write_json(evidence_dir / "lifecycle.json", journal)
                _write_json(evidence_dir / "dispatch.json", bridge.last_receipt)
                consecutive_errors = 0
                max_consecutive_errors = 3
                while True:
                    try:
                        observation = await bridge.observe(handle)
                        consecutive_errors = 0
                    except httpx.HTTPError:
                        consecutive_errors += 1
                        if consecutive_errors > max_consecutive_errors:
                            raise
                        await asyncio.sleep(poll_seconds)
                        continue
                    if observation.confirms_termination:
                        break
                    await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            receipt = bridge.last_receipt
            handle = handle or WorkerHandle(receipt.get("jobId", "unconfirmed"), receipt.get("sessionId", ""),
                                            receipt.get("messageId", ""), workspace.path, git_identity.root_commit)
            decision = _unresolved(handle, grace_seconds, "Caller cancelled observation; remote worker may still be active")
            _write_json(evidence_dir / "dispatch.json", receipt)
            journal.update(stage="termination_unresolved", handle=asdict(handle), termination=asdict(decision))
            _write_json(evidence_dir / "lifecycle.json", journal)
            guard.record(decision)
            raise
        except TimeoutError:
            if observation_budget.expired():
                task_budget_expired = True
            else:
                execution_error = "TimeoutError"
        except Exception as error:  # Execution/transport boundary, not a model-failure verdict.
            execution_error = type(error).__name__
        receipt = bridge.last_receipt
        _write_json(evidence_dir / "dispatch.json", receipt)
        handle = handle or WorkerHandle(receipt.get("jobId", "unconfirmed"), receipt.get("sessionId", ""),
                                        receipt.get("messageId", ""), workspace.path, git_identity.root_commit)
        if handle.session_id and handle.message_id and handle.job_id:
            try:
                decision = await confirm_termination(
                    bridge, handle, grace_seconds=grace_seconds, poll_seconds=poll_seconds,
                    cancel_first=task_budget_expired or execution_error is not None,
                )
            except asyncio.CancelledError:
                decision = _unresolved(handle, grace_seconds, "Caller cancelled termination confirmation")
                journal.update(stage="termination_unresolved", handle=asdict(handle), termination=asdict(decision))
                _write_json(evidence_dir / "lifecycle.json", journal)
                guard.record(decision)
                raise
        else:
            decision = _unresolved(handle, grace_seconds, "Submission outcome unknown; no safe cancellation target")
        worker_ms = (time.monotonic() - start) * 1000
        journal.update(stage="terminated" if decision.confirmed else "termination_unresolved", handle=asdict(handle),
                       termination=asdict(decision), task_budget_expired=task_budget_expired, execution_error=execution_error)
        _write_json(evidence_dir / "lifecycle.json", journal)
        guard.record(decision)
        _write_json(evidence_dir / "session.json", bridge.last_history)
        assistants = [message for message in bridge.last_history
                      if isinstance(message.get("info"), dict)
                      and message["info"].get("parentID") == handle.message_id
                      and message["info"].get("sessionID") == handle.session_id
                      and message["info"].get("role") == "assistant"]
        if assistants:
            def _msg_sort_key(m: object) -> tuple[float, str]:
                if not isinstance(m, dict):
                    return (0.0, "")
                info = m.get("info")
                if not isinstance(info, dict):
                    return (0.0, "")
                time_info = info.get("time")
                created = time_info.get("created") if isinstance(time_info, dict) else 0
                if not isinstance(created, (int, float)) or isinstance(created, bool) or not math.isfinite(created):
                    created = 0.0
                return (float(created), str(info.get("id") or ""))

            final = max(assistants, key=_msg_sort_key)
            final_info = final.get("info") if isinstance(final.get("info"), dict) else {}
            if final_info.get("structured") is not None:
                _write_json(evidence_dir / "worker-report.json", final_info["structured"])
            else:
                parts = final.get("parts") if isinstance(final.get("parts"), list) else []
                text = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict) and part.get("type") == "text")
                (evidence_dir / "worker-report.txt").write_text(text, encoding="utf-8")
        s1 = verification = None
        changed: tuple[str, ...] = ()
        scope: tuple[str, ...] = ()
        audit = None
        if decision.confirmed:
            s1 = capture(workspace.path, evidence_dir / "S1")
            changed = tuple(changed_paths(s0, s1))
            audit = audit_scope(task, workspace.path, s0, s1, bridge.last_history)
            scope = audit.all_violations
            (evidence_dir / "worker.patch").write_text(_patch(s0, s1), encoding="utf-8")
            _write_json(evidence_dir / "checkpoints.json", {
                "S0": {"tree_hash": s0.tree_hash},
                "S1": {"tree_hash": s1.tree_hash, "diff_path": "worker.patch"},
                "changed_paths": changed,
                "snapshot_scope_violations": list(audit.snapshot_violations),
                "transcript_scope_violations": list(audit.transcript_violations),
                "scope_violations": list(scope),
            })
            _write_json(evidence_dir / "scope-audit.json", audit.to_dict())
            # Verification runs in its own owned process, after S1 has been archived.
            verification = verify(s1, task.verifier, evidence_dir / "verification", timeout_seconds=verifier_seconds)
            journal["stage"] = "verified"
            _write_json(evidence_dir / "lifecycle.json", journal)
        return AttemptEvidence(workspace, decision, s0, s1, verification, changed, scope, task_budget_expired,
                               execution_error, worker_ms, (time.monotonic() - start) * 1000, scope_audit=audit)
    finally:
        # Persistence can fail after remote submission (disk full/permissions).
        # Safety cannot depend on a successful journal write or its exception path.
        if dispatch_started and (decision is None or not decision.confirmed) and guard.unresolved is None:
            receipt = bridge.last_receipt
            pending_handle = handle or WorkerHandle(receipt.get("jobId", "unconfirmed"), receipt.get("sessionId", ""),
                                                    receipt.get("messageId", ""), workspace.path, git_identity.root_commit)
            guard.record(decision or _unresolved(pending_handle, grace_seconds,
                         "Execution/evidence failure prevented confirmation; preserve workspace and halt dispatch"))
