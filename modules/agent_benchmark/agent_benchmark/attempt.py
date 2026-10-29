"""One first worker attempt, yielding immutable evidence for canonical integration.

No retry, repair, result serialization or report rendering lives here. The core
integration layer must later consume these facts to emit exactly one TrialResult.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass
import difflib
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
from typing import Any

import httpx

from .bridge import ModelConfigurationError, OpenCodeBridge
from .tool_profile import (
    FILE_AGENT,
    FILE_PROFILE,
    FILE_PROMPT,
    RETRIEVAL_AGENT,
    RETRIEVAL_PROFILE,
    STRUCTURAL_AGENT,
    STRUCTURAL_PROFILE,
    validate_execution_profile,
)
from .identity import ModelIdentity, ModelIdentityError, discover_lmstudio_identity
from .evidence import (EVIDENCE_LIMITS, EvidenceLimitExceeded, ScopeAudit, Snapshot, Task, Verification, audit_scope,
                       capture, changed_paths, prepare_workspace, verify)
from .scratch import SCOPE_POLICY, prompt_instructions, provenance, reserved_path
from .lifecycle import DispatchGuard, Observation, OwnedWorkspace, TerminationDecision, WorkerHandle, confirm_termination


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
    scope_policy: str | None = None
    session_tokens: dict[str, Any] | None = None
    tool_telemetry: dict[str, Any] | None = None
    execution_diagnostic: str | None = None
    timings: dict[str, float] | None = None


def extract_timings(history: object) -> dict[str, float]:
    def mapping(value):
        return value if isinstance(value, dict) else {}
    def stamp(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if not isinstance(history, list):
        return {}
    users = [mapping(m).get("info") for m in history if mapping(mapping(m).get("info")).get("role") == "user"]
    if len(users) != 1:
        return {}
    user = users[0]
    start = mapping(user.get("time")).get("created")
    if not stamp(start) or not all(isinstance(user.get(k), str) and user[k] for k in ("id", "sessionID")):
        return {}
    edits, assistants = [], []
    for message in history:
        message = mapping(message)
        info = mapping(message.get("info"))
        if info.get("role") != "assistant" or info.get("parentID") != user["id"] or info.get("sessionID") != user["sessionID"]:
            continue
        assistants.append(info)
        parts = message.get("parts")
        for part in parts if isinstance(parts, list) else []:
            part = mapping(part)
            state = mapping(part.get("state"))
            value = mapping(state.get("time")).get("end")
            if (part.get("type") == "tool" and part.get("tool") in {"edit", "write", "patch"}
                    and state.get("status") == "completed" and stamp(value) and value >= start):
                edits.append(value - start)
    result = {"first_edit_ms": min(edits), "last_edit_ms": max(edits)} if edits else {}
    if assistants:
        final = max(assistants, key=lambda info: mapping(info.get("time")).get("created", -1)
                    if stamp(mapping(info.get("time")).get("created")) else -1)
        value = mapping(final.get("time")).get("completed")
        if final.get("finish") == "stop" and not final.get("error") and stamp(value) and value >= start:
            result["completion_ms"] = value - start
    return result


def extract_telemetry(session: Any, history: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract token and tool efficiency telemetry from session identity and history."""
    tokens_data: dict[str, Any] = {}
    tools_data: dict[str, Any] = {}

    if isinstance(session, dict):
        raw_tokens = session.get("tokens")
        if isinstance(raw_tokens, dict):
            inp = raw_tokens.get("input")
            out = raw_tokens.get("output")
            reasoning = raw_tokens.get("reasoning")
            if isinstance(inp, (int, float)):
                tokens_data["input"] = int(inp)
            out_val = int(out) if isinstance(out, (int, float)) else 0
            reason_val = int(reasoning) if isinstance(reasoning, (int, float)) else 0
            if isinstance(out, (int, float)) or isinstance(reasoning, (int, float)):
                # OpenCode's 'output' field is visible content tokens only.
                # Standard LLM accounting counts total generated tokens (content + reasoning) as output tokens.
                tokens_data["output"] = out_val + reason_val
                tokens_data["content"] = out_val
                tokens_data["reasoning"] = reason_val

    if isinstance(history, list):
        inputs = []
        tool_counts: dict[str, int] = {}
        tool_failures = 0
        total_calls = 0

        for msg in history:
            if not isinstance(msg, dict):
                continue
            info = msg.get("info")
            if isinstance(info, dict) and info.get("role") == "assistant":
                t_info = info.get("tokens")
                if isinstance(t_info, dict) and isinstance(t_info.get("input"), (int, float)):
                    inp_val = int(t_info["input"])
                    if inp_val > 0:
                        inputs.append(inp_val)
            parts = msg.get("parts")
            if isinstance(parts, list):
                for p in parts:
                    if isinstance(p, dict) and p.get("type") == "tool":
                        tname = str(p.get("tool") or "unknown")
                        tool_counts[tname] = tool_counts.get(tname, 0) + 1
                        total_calls += 1
                        st = p.get("state")
                        if isinstance(st, dict):
                            if st.get("status") == "error":
                                tool_failures += 1
                            elif st.get("metadata", {}).get("exit", 0) != 0:
                                tool_failures += 1

        if inputs:
            tokens_data["initial_prompt"] = inputs[0]
            tokens_data["peak_context"] = max(inputs)
            if "input" not in tokens_data:
                tokens_data["input"] = sum(inputs)
        if total_calls > 0:
            tools_data["total_calls"] = total_calls
            tools_data["total_failures"] = tool_failures
            tools_data["tool_counts"] = tool_counts

    return tokens_data, tools_data


def _write_json(path: Path, data: object) -> None:
    # Evidence journaling only: canonical run/trial serialization belongs to core.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    for retry in range(5):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if retry == 4:
                raise
            time.sleep(0.02)


def _capture_checkpoint(workspace: Path, evidence_dir: Path, journal: dict, checkpoint: str) -> Snapshot:
    try:
        return capture(workspace, evidence_dir / checkpoint, limits=EVIDENCE_LIMITS)
    except EvidenceLimitExceeded as error:
        diagnostic = {"checkpoint": checkpoint, "kind": error.kind, "path": error.path,
                      "observed": error.observed, "limit": error.limit, "complete_snapshot": False,
                      "limits": asdict(EVIDENCE_LIMITS)}
        _write_json(evidence_dir / "evidence-limit.json", diagnostic)
        journal["evidence_capture"] = diagnostic
        if checkpoint == "S1":
            journal["stage"] = "evidence_limited"
        _write_json(evidence_dir / "lifecycle.json", journal)
        raise


def _unresolved(handle: WorkerHandle, grace: float, reason: str) -> TerminationDecision:
    return TerminationDecision(handle, False, False, grace, 0, None, (reason,))


def _patch(before: Snapshot, after: Snapshot, *, max_bytes: int = 256 * 1024,
           scope_policy: str | None = None) -> str:
    """A bounded convenience diff; snapshots, not this preview, are authoritative."""
    if max_bytes < 64:
        raise ValueError("Patch preview requires at least 64 bytes")
    chunks: list[str] = []
    used = 0
    notice = "[Patch preview limited; exact bytes retained in snapshots]\n"
    for name in changed_paths(before, after):
        old, new = before.files.get(name, b""), after.files.get(name, b"")
        summary = (f"Snapshot content: {name}; "
                   f"S0={hashlib.sha256(old).hexdigest()} S1={hashlib.sha256(new).hexdigest()}\n")
        # Do not duplicate scratch payloads or run quadratic text comparison on
        # large/line-heavy worker output. Each text diff has fixed small inputs.
        lines: Iterable[str] = [summary]
        if not (scope_policy and reserved_path(name)) and max(len(old), len(new)) <= 16384:
            try:
                left, right = old.decode("utf-8"), new.decode("utf-8")
                if len(left.splitlines()) <= 200 and len(right.splitlines()) <= 200:
                    lines = difflib.unified_diff(left.splitlines(keepends=True), right.splitlines(keepends=True),
                                                fromfile=f"S0/{name}", tofile=f"S1/{name}")
            except UnicodeDecodeError:
                pass
        for line in lines:
            size = len(line.encode("utf-8"))
            if used + size + len(notice) > max_bytes:
                chunks.append(notice)
                return "".join(chunks)
            chunks.append(line)
            used += size
    return "".join(chunks)


def build_prompt(task: Task, workspace: Path, *, file_tools: bool | None = None) -> str:
    """Deterministic user prompt; not a claim about provider system/tool schemas."""
    use_file_tools = (task.opencode_tool_profile in {FILE_PROFILE, RETRIEVAL_PROFILE, STRUCTURAL_PROFILE}
                      if file_tools is None else file_tools)
    if use_file_tools:
        return (task.instruction + "\n\nWorkspace: " + str(workspace) + "\n" + FILE_PROMPT
                + "\ncompletion reports belong in your final response or StructuredOutput. "
                "Do not create status or completion files. For edit tools, newString is literal replacement text; "
                "leading `+` characters are literal source, not diff markers."
                " Return your completion report; do not claim to have run checks.")
    return (task.instruction + "\n\nWorkspace: " + str(workspace)
              + prompt_instructions(workspace)
              + f"\nEvidence capture limits (including scratch): {asdict(EVIDENCE_LIMITS)}. Keep temporary output small."
              + "\nUse only the task-allowed paths and the designated trial scratch directory. Do not spawn background processes or install packages. "
              "For Python checks, disable bytecode writes (-B or PYTHONDONTWRITEBYTECODE=1). "
              "Return a JSON completion report with outcome, summary, changed_paths, checks, evidence and blockers. "
              "completion reports belong in your final response or StructuredOutput. Do not create status or completion files. "
              "For edit tools, newString is literal replacement text; leading `+` characters are literal source, not diff markers. "
              "Report only checks you actually ran. Stop after your first attempt; do not request a retry.")


async def _monitored_call(operation: Awaitable, resource_check: Callable[[], None] | None):
    """Check host safety while dispatch/observation is pending, including slow HTTP calls."""
    if resource_check is None:
        return await operation
    pending = asyncio.ensure_future(operation)
    try:
        while True:
            resource_check()
            done, _ = await asyncio.wait({pending}, timeout=0.5)
            if done:
                resource_check()
                return await pending
    finally:
        if not pending.done():
            pending.cancel()
        # Retrieve exceptions and finish cancellation before remote termination reconciliation.
        await asyncio.gather(pending, return_exceptions=True)


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
    model_identity: ModelIdentity | None = None,
    resource_check: Callable[[], None] | None = None,
) -> AttemptEvidence:
    """Dispatch once and freeze S1 only after fresh termination confirmation.

    An unresolved submission/worker returns no S1 or verification. DispatchGuard
    then stops subsequent attempts. Keep this guard for the whole batch. Cleanup
    is a separate explicit operation; this function always retains the workspace.
    Preflight errors occur before dispatch and propagate with diagnostic evidence.
    """
    validate_execution_profile(task.opencode_tool_profile)
    budget = task.time_budget_seconds if task_seconds is None else task_seconds
    for name, value in (("task_seconds", budget), ("grace_seconds", grace_seconds),
                        ("poll_seconds", poll_seconds), ("verifier_seconds", verifier_seconds)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if provider == "lmstudio" and model_identity is None:
        model_identity = await discover_lmstudio_identity(model)
    if model_identity is not None and (model_identity.provider != provider or model_identity.runtime_model_id != model):
        raise ModelIdentityError(
            f"Resolved model identity does not match requested runtime model '{provider}/{model}'"
        )
    if provider == "lmstudio" and task.opencode_tool_profile in {FILE_PROFILE, RETRIEVAL_PROFILE, STRUCTURAL_PROFILE}:
        if agent != "local-worker":
            raise ValueError("The file-tools task profile requires the default worker role")
        agent = (STRUCTURAL_AGENT if task.opencode_tool_profile == STRUCTURAL_PROFILE else
                 RETRIEVAL_AGENT if task.opencode_tool_profile == RETRIEVAL_PROFILE else FILE_AGENT)
    # Reserve evidence first; refuse to reuse old trial directories before creating resources.
    evidence_dir.mkdir(parents=True, exist_ok=False)
    workspace = guard.allocate(workspace_root)
    git_identity = prepare_workspace(
        task, workspace.path, scope_policy=SCOPE_POLICY, model_identity=model_identity
    )
    # Worker processes belong to OpenCode's shared process tree, not local subprocess
    # supervision; owned_pids is intentionally empty.
    journal = {"stage": "not_submitted", "workspace": asdict(workspace), "task_seconds": budget,
               "grace_seconds": grace_seconds, "verifier_seconds": verifier_seconds, "owned_pids": [],
               "git": asdict(git_identity), "scope_policy": SCOPE_POLICY,
               "opencode_tool_profile": task.opencode_tool_profile, "scratch": provenance(workspace.path),
               "evidence_limits": asdict(EVIDENCE_LIMITS),
               "model_identity": model_identity.to_dict() if model_identity else None}
    _write_json(evidence_dir / "lifecycle.json", journal)
    s0 = _capture_checkpoint(workspace.path, evidence_dir, journal, "S0")
    prompt = build_prompt(task, workspace.path)
    (evidence_dir / "submitted-prompt.txt").write_bytes(prompt.encode("utf-8"))
    _write_json(evidence_dir / "prompt.json", {"sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                                             "scope_policy": SCOPE_POLICY, "kind": "intended_user_prompt"})
    try:
        configuration = await bridge.preflight(workspace.path, provider=provider, model=model, agent=agent,
                                               project_id=git_identity.root_commit,
                                               tool_profile=task.opencode_tool_profile)
        configuration["opencode_tool_profile"] = task.opencode_tool_profile
        if model_identity is not None:
            configuration["model_identity"] = model_identity.to_dict()
        prepared_session = await bridge.prepare_session(workspace.path, project_id=git_identity.root_commit)
        configuration.update(git=asdict(git_identity), session=prepared_session,
                             scope_policy=SCOPE_POLICY, scratch=provenance(workspace.path),
                             evidence_limits=asdict(EVIDENCE_LIMITS))
        journal["prepared_session"] = prepared_session
        _write_json(evidence_dir / "session-preflight.json", getattr(bridge, "session_evidence", prepared_session))
        _write_json(evidence_dir / "lifecycle.json", journal)
    except Exception as error:
        journal.update(stage="preflight_failed", diagnostic=type(error).__name__)
        if isinstance(error, ModelConfigurationError):
            journal["diagnostic_message"] = str(error)
        session_evidence = getattr(bridge, "session_evidence", {})
        if session_evidence:
            _write_json(evidence_dir / "session-preflight.json", session_evidence)
        _write_json(evidence_dir / "lifecycle.json", journal)
        raise
    _write_json(evidence_dir / "runtime.json", configuration)
    handle = None
    task_budget_expired = False
    execution_error = None
    execution_diagnostic = None
    start = time.monotonic()
    journal["stage"] = "dispatching"
    _write_json(evidence_dir / "lifecycle.json", journal)

    decision = None
    dispatch_started = False
    try:
        observation_budget = asyncio.timeout(budget)
        try:
            async with observation_budget:
                dispatch_started = True
                guard.submission_started = True
                handle = await _monitored_call(
                    bridge.dispatch(workspace.path, prompt, provider=provider, model=model, agent=agent), resource_check
                )
                journal.update(stage="observing", handle=asdict(handle))
                # Persist recovery ownership before writing secondary receipt evidence.
                _write_json(evidence_dir / "lifecycle.json", journal)
                _write_json(evidence_dir / "dispatch.json", bridge.last_receipt)
                consecutive_errors = 0
                max_consecutive_errors = 3
                while True:
                    try:
                        observation = await _monitored_call(bridge.observe(handle), resource_check)
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
            execution_diagnostic = f"{type(error).__name__}: {error}"[:2000]
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
        journal["execution_diagnostic"] = execution_diagnostic
        _write_json(evidence_dir / "lifecycle.json", journal)
        guard.record(decision)
        _write_json(evidence_dir / "session.json", bridge.last_history)
        session_tokens, tool_telemetry = extract_telemetry(
            getattr(bridge, "last_session", None),
            bridge.last_history,
        )
        if getattr(bridge, "last_session", None) is not None:
            _write_json(evidence_dir / "session-identity.json", bridge.last_session)
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
            s1 = _capture_checkpoint(workspace.path, evidence_dir, journal, "S1")
            changed = tuple(changed_paths(s0, s1))
            audit = audit_scope(task, workspace.path, s0, s1, bridge.last_history, scope_policy=SCOPE_POLICY,
                                opencode_version=configuration.get("opencode_version"))
            scope = audit.all_violations
            (evidence_dir / "worker.patch").write_text(_patch(s0, s1, max_bytes=EVIDENCE_LIMITS.max_patch_bytes,
                                                           scope_policy=SCOPE_POLICY), encoding="utf-8")
            _write_json(evidence_dir / "checkpoints.json", {
                "S0": {"tree_hash": s0.tree_hash},
                "S1": {"tree_hash": s1.tree_hash, "diff_path": "worker.patch"},
                "changed_paths": changed,
                "scope_policy": SCOPE_POLICY,
                "task_changed_paths": audit.task_changed_paths,
                "scratch_changed_paths": audit.scratch_changed_paths,
                "snapshot_scope_violations": list(audit.snapshot_violations),
                "transcript_scope_violations": list(audit.transcript_violations),
                "scope_violations": list(scope),
            })
            _write_json(evidence_dir / "scope-audit.json", audit.to_dict())
            # Verification runs in its own owned process, after S1 has been archived.
            verification = verify(s1, task.verifier, evidence_dir / "verification", timeout_seconds=verifier_seconds,
                                  scope_policy=SCOPE_POLICY)
            journal["stage"] = "verified"
            _write_json(evidence_dir / "lifecycle.json", journal)
        return AttemptEvidence(
            workspace, decision, s0, s1, verification, changed, scope, task_budget_expired,
            execution_error, worker_ms, (time.monotonic() - start) * 1000, scope_audit=audit, scope_policy=SCOPE_POLICY,
            session_tokens=session_tokens if session_tokens else None,
            tool_telemetry=tool_telemetry if tool_telemetry else None,
            execution_diagnostic=execution_diagnostic, timings=extract_timings(bridge.last_history),
        )
    finally:
        # Persistence can fail after remote submission (disk full/permissions).
        # Safety cannot depend on a successful journal write or its exception path.
        if dispatch_started and (decision is None or not decision.confirmed) and guard.unresolved is None:
            receipt = bridge.last_receipt
            pending_handle = handle or WorkerHandle(receipt.get("jobId", "unconfirmed"), receipt.get("sessionId", ""),
                                                    receipt.get("messageId", ""), workspace.path, git_identity.root_commit)
            guard.record(decision or _unresolved(pending_handle, grace_seconds,
                         "Execution/evidence failure prevented confirmation; preserve workspace and halt dispatch"))


async def run_cli_attempt(
    task: Task,
    guard: DispatchGuard,
    *,
    workspace_root: Path,
    evidence_dir: Path,
    provider: str,
    model: str,
    task_seconds: float | None = None,
    grace_seconds: float = 10,
    verifier_seconds: float = 10,
    cli_runner: Any = None,
) -> AttemptEvidence:
    """Execute a benchmark trial directly via local CLI agent (`agy` for gemini, `codex` for codex)."""
    validate_execution_profile(task.opencode_tool_profile)
    budget = task.time_budget_seconds if task_seconds is None else task_seconds
    for name, value in (("task_seconds", budget), ("grace_seconds", grace_seconds), ("verifier_seconds", verifier_seconds)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")

    evidence_dir.mkdir(parents=True, exist_ok=False)
    workspace = guard.allocate(workspace_root)
    git_identity = prepare_workspace(task, workspace.path, scope_policy=SCOPE_POLICY)

    journal: dict[str, Any] = {
        "stage": "not_submitted",
        "workspace": asdict(workspace),
        "task_seconds": budget,
        "grace_seconds": grace_seconds,
        "verifier_seconds": verifier_seconds,
        "owned_pids": [],
        "git": asdict(git_identity),
        "scope_policy": SCOPE_POLICY,
        "scratch": provenance(workspace.path),
        "evidence_limits": asdict(EVIDENCE_LIMITS),
    }
    _write_json(evidence_dir / "lifecycle.json", journal)
    s0 = _capture_checkpoint(workspace.path, evidence_dir, journal, "S0")
    prompt = build_prompt(task, workspace.path, file_tools=False)
    (evidence_dir / "submitted-prompt.txt").write_bytes(prompt.encode("utf-8"))
    _write_json(
        evidence_dir / "prompt.json",
        {"sha256": hashlib.sha256(prompt.encode()).hexdigest(), "scope_policy": SCOPE_POLICY, "kind": "intended_user_prompt"},
    )

    prov_low = provider.lower().strip()
    if prov_low in ("gemini", "agy"):
        exe = shutil.which("agy") or "agy"
        cmd = [exe, "--model", model, "--mode", "accept-edits", "--dangerously-skip-permissions", "-p", prompt]
    elif prov_low in ("codex", "openai", "chatgpt"):
        exe = shutil.which("codex") or "codex"
        cmd = [
            exe,
            "exec",
            "-C",
            str(workspace.path),
            "-m",
            model,
            "--dangerously-bypass-approvals-and-sandbox",
            "--ephemeral",
            prompt,
        ]
    else:
        raise ValueError(f"Unsupported CLI agent provider: {provider!r}")

    configuration = {
        "provider": prov_low,
        "model": model,
        "cli_executable": exe,
        "git": asdict(git_identity),
        "scope_policy": SCOPE_POLICY,
        "scratch": provenance(workspace.path),
        "evidence_limits": asdict(EVIDENCE_LIMITS),
    }
    _write_json(evidence_dir / "runtime.json", configuration)

    handle = WorkerHandle(f"cli-{prov_low}", f"session-{prov_low}", "msg-001", workspace.path, git_identity.root_commit)
    task_budget_expired = False
    execution_error: str | None = None
    start = time.monotonic()
    journal["stage"] = "dispatching"
    _write_json(evidence_dir / "lifecycle.json", journal)

    stdout_str = ""
    stderr_str = ""
    proc: asyncio.subprocess.Process | None = None
    terminated_cleanly = False

    try:
        guard.submission_started = True
        if cli_runner is not None:
            async with asyncio.timeout(budget):
                code, stdout_str, stderr_str = await cli_runner(cmd, workspace.path)
                terminated_cleanly = True
                if code != 0:
                    execution_error = f"CLIExitCode_{code}"
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workspace.path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            journal.update(stage="observing", handle=asdict(handle), owned_pids=[proc.pid])
            _write_json(evidence_dir / "lifecycle.json", journal)
            try:
                async with asyncio.timeout(budget):
                    out_b, err_b = await proc.communicate()
                    stdout_str = out_b.decode("utf-8", errors="replace")
                    stderr_str = err_b.decode("utf-8", errors="replace")
                    terminated_cleanly = True
                    if (proc.returncode or 0) != 0:
                        execution_error = f"CLIExitCode_{proc.returncode}"
            except TimeoutError:
                task_budget_expired = True
                if proc.returncode is None:
                    try:
                        proc.kill()
                        await asyncio.wait_for(proc.wait(), timeout=grace_seconds)
                        terminated_cleanly = True
                    except Exception:
                        terminated_cleanly = False
    except TimeoutError:
        task_budget_expired = True
        execution_error = "CLIObservationTimeout"
        if proc is None:
            # The built-in path has not created a child yet. Injected runners
            # own their process lifecycle, so a timeout from one is unresolved.
            terminated_cleanly = cli_runner is None
        elif proc.returncode is not None:
            terminated_cleanly = True
        else:
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=grace_seconds)
                terminated_cleanly = proc.returncode is not None
            except Exception:
                terminated_cleanly = False
    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=grace_seconds)
            except Exception:
                pass
        decision = _unresolved(handle, grace_seconds, "Caller cancelled CLI worker execution")
        journal.update(stage="termination_unresolved", handle=asdict(handle), termination=asdict(decision))
        _write_json(evidence_dir / "lifecycle.json", journal)
        guard.record(decision)
        raise
    except Exception as exc:
        execution_error = type(exc).__name__
        if proc is None:
            # No child was created by this function, so there is no worker to
            # prove terminated. A custom runner owns its own child lifecycle.
            terminated_cleanly = cli_runner is None
        elif proc.returncode is not None:
            terminated_cleanly = True
        else:
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=grace_seconds)
                terminated_cleanly = proc.returncode is not None
            except Exception:
                terminated_cleanly = False

    worker_ms = (time.monotonic() - start) * 1000
    decision = TerminationDecision(
        handle=handle,
        confirmed=terminated_cleanly,
        cancellation_requested=task_budget_expired,
        grace_seconds=grace_seconds,
        elapsed_seconds=worker_ms / 1000.0,
        last_observation=Observation(
            "cancelled" if task_budget_expired else "failed" if execution_error else "completed",
            "idle" if terminated_cleanly else "unknown", terminated_cleanly, not terminated_cleanly,
            terminated_cleanly, "CLI child exit observed; no execution transcript or containment proof",
        ),
        diagnostics=() if terminated_cleanly else ("CLI subprocess did not terminate within grace period",),
    )
    journal.update(
        stage="terminated" if decision.confirmed else "termination_unresolved",
        handle=asdict(handle),
        termination=asdict(decision),
        task_budget_expired=task_budget_expired,
        execution_error=execution_error,
    )
    _write_json(evidence_dir / "lifecycle.json", journal)
    guard.record(decision)

    if stdout_str:
        (evidence_dir / "worker-report.txt").write_text(stdout_str, encoding="utf-8")
    if stderr_str:
        (evidence_dir / "worker-stderr.txt").write_text(stderr_str, encoding="utf-8")

    s1 = verification = None
    changed: tuple[str, ...] = ()
    scope: tuple[str, ...] = ()
    audit = None
    if decision.confirmed:
        s1 = _capture_checkpoint(workspace.path, evidence_dir, journal, "S1")
        changed = tuple(changed_paths(s0, s1))
        audit = audit_scope(task, workspace.path, s0, s1, [], scope_policy=SCOPE_POLICY)
        scope = audit.all_violations
        (evidence_dir / "worker.patch").write_text(
            _patch(s0, s1, max_bytes=EVIDENCE_LIMITS.max_patch_bytes, scope_policy=SCOPE_POLICY),
            encoding="utf-8",
        )
        _write_json(
            evidence_dir / "checkpoints.json",
            {
                "S0": {"tree_hash": s0.tree_hash},
                "S1": {"tree_hash": s1.tree_hash, "diff_path": "worker.patch"},
                "changed_paths": changed,
                "scope_policy": SCOPE_POLICY,
                "task_changed_paths": audit.task_changed_paths,
                "scratch_changed_paths": audit.scratch_changed_paths,
                "snapshot_scope_violations": list(audit.snapshot_violations),
                "transcript_scope_violations": list(audit.transcript_violations),
                "scope_violations": list(scope),
            },
        )
        _write_json(evidence_dir / "scope-audit.json", audit.to_dict())
        verification = verify(
            s1,
            task.verifier,
            evidence_dir / "verification",
            timeout_seconds=verifier_seconds,
            scope_policy=SCOPE_POLICY,
        )
        journal["stage"] = "verified"
        _write_json(evidence_dir / "lifecycle.json", journal)

    return AttemptEvidence(
        workspace=workspace,
        termination=decision,
        s0=s0,
        s1=s1,
        verification=verification,
        changed_paths=changed,
        scope_violations=scope,
        task_budget_expired=task_budget_expired,
        execution_error=execution_error,
        worker_ms=worker_ms,
        wall_ms=(time.monotonic() - start) * 1000,
        scope_audit=audit,
        scope_policy=SCOPE_POLICY,
        session_tokens=None,
        tool_telemetry=None,
    )

