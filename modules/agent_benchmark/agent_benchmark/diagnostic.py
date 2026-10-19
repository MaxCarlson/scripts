"""One unscored integration smoke using the production attempt and reservation."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import shutil
import sys
import uuid
from typing import Any

from . import __version__
from .git_workspace import ISOLATION_POLICY
from .attempt import _write_json, run_attempt
from .bridge import OpenCodeBridge, connected_bridge
from .evidence import load_task
from .lifecycle import WorkerHandle
from .scratch import SCOPE_POLICY, SCRATCH_NAME
from .state import journal_at, reserved_trial

TASK_SECONDS = 60
GRACE_SECONDS = 10


def probe_command() -> str:
    executable = sys.executable.replace("'", "''")
    return (
        f"$env:TEMP = Join-Path (Get-Location).Path '{SCRATCH_NAME}'; "
        "$env:TMP = $env:TEMP; $env:TMPDIR = $env:TEMP; "
        f"& '{executable}' -I -B .\\temp_probe.py"
    )


def _fixture(destination: Path) -> Path:
    original = Path(__file__).parent / "tasks/py-grep-smoke"
    shutil.copytree(original, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(Path(__file__).with_name("temp_probe.py"), destination / "seed/temp_probe.py")
    manifest = json.loads((destination / "task.json").read_text(encoding="utf-8"))
    manifest.update(task_id="integration-py-grep-smoke", category="diagnostic", time_budget_seconds=TASK_SECONDS)
    manifest["forbidden_paths"].append("temp_probe.py")
    _write_json(destination / "task.json", manifest)
    instruction = destination / "instruction.md"
    with instruction.open("a", encoding="utf-8") as target:
        target.write(
            "\n\nIntegration diagnostic only: implement grep.py, then execute the unchanged public "
            "temp_probe.py exactly once. Do not edit the probe. Use one shell tool invocation with "
            "workdir set to the workspace root, and this exact PowerShell command (no wrapper or additions):\n\n"
            + probe_command()
            + "\nTemporary test scripts/caches are permitted only in trial scratch. "
            "This grants no additional task deliverables or external writes.\n"
        )
    return destination


def attribute_user_prompt(history: object, session: object, handle: WorkerHandle, prompt: str) -> dict:
    result = {
        "status": "unverified",
        "expected_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "session_id": handle.session_id,
        "message_id": handle.message_id,
    }
    if (
        not isinstance(session, dict)
        or session.get("id") != handle.session_id
        or session.get("projectID") != handle.project_id
        or not OpenCodeBridge._same_directory(session.get("directory"), handle.workspace)
    ):
        return {**result, "status": "failed", "reason": "Fresh session binding mismatch"}
    if not isinstance(history, list):
        return {**result, "reason": "No stored user-message evidence"}
    users = [
        m
        for m in history
        if isinstance(m, dict) and isinstance(m.get("info"), dict) and m["info"].get("role") == "user"
    ]
    if not users:
        return {**result, "reason": "No stored user-message evidence"}
    if len(users) != 1:
        return {**result, "status": "failed", "reason": "Expected exactly one submitted user turn"}
    message = users[0]
    info, parts = message["info"], message.get("parts")
    if info.get("id") != handle.message_id or info.get("sessionID") != handle.session_id:
        return {**result, "status": "failed", "reason": "Stored user turn identifiers mismatch"}
    if (
        not isinstance(parts, list)
        or not parts
        or any(
            not isinstance(p, dict)
            or p.get("type") != "text"
            or not isinstance(p.get("text"), str)
            or p.get("synthetic") is True
            or p.get("sessionID", handle.session_id) != handle.session_id
            or p.get("messageID", handle.message_id) != handle.message_id
            for p in parts
        )
    ):
        return {**result, "reason": "Ambiguous stored user parts"}
    observed = "".join(p["text"] for p in parts)
    return {
        **result,
        "status": "passed" if observed == prompt else "failed",
        "observed_sha256": hashlib.sha256(observed.encode()).hexdigest(),
        "reason": "Exact text comparison; not provider-payload verification",
    }


def _probe_checks(attempt, history: list) -> tuple[dict, dict]:
    artifacts: dict[str, Any] = {"status": "unverified", "reason": "No reliable S1/probe artifacts"}
    execution: dict[str, Any] = {"status": "unverified", "reason": "No attributed successful exact probe command"}
    if attempt.s1 is None:
        return artifacts, execution
    try:
        files = attempt.s1.files
        expected = Path(__file__).with_name("temp_probe.py").read_bytes()
        if attempt.s0.files.get("temp_probe.py") != expected or files.get("temp_probe.py") != expected:
            raise ValueError("Trusted probe bytes changed")
        value = json.loads(files[f"{SCRATCH_NAME}/temp-probe.json"])
        scratch = attempt.workspace.path / SCRATCH_NAME
        if (
            not isinstance(value, dict)
            or not OpenCodeBridge._same_directory(value.get("tempdir"), scratch)
            or not isinstance(value.get("environment"), dict)
            or any(
                not OpenCodeBridge._same_directory(value["environment"].get(k), scratch)
                for k in ("TEMP", "TMP", "TMPDIR")
            )
        ):
            raise ValueError("Probe observed incorrect temp settings")
        marker = value.get("marker_name")
        if (
            not isinstance(marker, str)
            or not marker.startswith("smoke-")
            or PureWindowsPath(marker).name != marker
            or Path(marker).name != marker
        ):
            raise ValueError("Invalid marker path")
        data = files[f"{SCRATCH_NAME}/{marker}"]
        if hashlib.sha256(data).hexdigest() != value.get("marker_sha256"):
            raise ValueError("Marker bytes mismatch")
        artifacts = {
            "status": "passed",
            "observation": value,
            "probe_sha256": hashlib.sha256(expected).hexdigest(),
            "limitation": "Trusted-fixture evidence, not an adversarial sandbox",
        }
        calls = []
        for message in history:
            parts = message.get("parts") if isinstance(message, dict) else None
            for part in parts if isinstance(parts, list) else []:
                if not isinstance(part, dict):
                    continue
                state = part.get("state")
                if not isinstance(state, dict):
                    continue
                inp = state.get("input")
                if not isinstance(inp, dict):
                    continue
                if (
                    part.get("type") == "tool"
                    and part.get("tool") in ("shell", "bash")
                    and inp.get("command") == probe_command()
                ):
                    calls.append(part)
        if len(calls) == 1:
            state = calls[0]["state"]
            workdir = state["input"].get("workdir", str(attempt.workspace.path))
            if (
                state.get("status") == "completed"
                and state.get("metadata", {}).get("exit") == 0
                and OpenCodeBridge._same_directory(workdir, attempt.workspace.path)
                and json.loads(state.get("output", "")) == value
            ):
                execution = {
                    "status": "passed",
                    "call_id": calls[0].get("callID"),
                    "reason": "Completed exact trusted command and matching output/retained marker",
                }
    except (KeyError, TypeError, ValueError, AttributeError):
        artifacts = {"status": "failed", "reason": "Missing, changed or invalid trusted probe evidence"}
    return artifacts, execution


async def run_diagnostic(
    *,
    output: Path,
    state: Path,
    model: str,
    provider: str = "lmstudio",
    agent: str = "local-worker",
    base_url: str = "http://127.0.0.1:4096",
    request_seconds: float = 10,
    connector=connected_bridge,
) -> Path:
    """Exactly one possible submission; provider payload is optional/unverified."""
    if agent != "local-worker":
        raise ValueError("Diagnostic smoke requires local-worker")
    state, output = state.resolve(), output.resolve()
    identifier = datetime.now(timezone.utc).strftime("smoke-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    directory = output / identifier
    evidence_dir = directory / "evidence/trial-001"
    with reserved_trial(state, evidence_dir) as guard:
        directory.mkdir(parents=True, exist_ok=False)
        report: dict[str, Any] = {
            "purpose": "integration_smoke",
            "benchmark_version": __version__,
            "isolation_policy": ISOLATION_POLICY,
            "base_url": base_url,
            "request_seconds": request_seconds,
            "comparison_eligible": False,
            "scope_policy": SCOPE_POLICY,
            "task_seconds": TASK_SECONDS,
            "grace_seconds": GRACE_SECONDS,
            "model": model,
            "provider": provider,
            "agent": agent,
            "termination_confirmed": False,
            "integration_status": "incomplete",
            "checks": {
                "intended_configuration": {"status": "unverified"},
                "submitted_user_prompt": {"status": "unverified"},
                "provider_payload": {
                    "status": "unverified",
                    "optional": True,
                    "reason": "No demonstrated supported complete provider-payload tracing mechanism",
                },
            },
        }
        try:
            task = load_task(_fixture(directory / "fixture"))
            async with connector(base_url=base_url, request_seconds=request_seconds) as bridge:
                attempt = await run_attempt(
                    task,
                    bridge,
                    guard,
                    workspace_root=state / "workspaces",
                    evidence_dir=evidence_dir,
                    provider=provider,
                    model=model,
                    agent=agent,
                    task_seconds=TASK_SECONDS,
                    grace_seconds=GRACE_SECONDS,
                )
                report["checks"]["intended_configuration"] = {
                    "status": "passed",
                    "source": "runtime.json/session-preflight.json",
                    "limitation": "Intended role/model/project/session validated; not inherited provider system/tool schemas",
                }
                prompt = (evidence_dir / "submitted-prompt.txt").read_text(encoding="utf-8")
                history = bridge.last_history
                session = getattr(bridge, "last_session", None)
                _write_json(evidence_dir / "session-identity.json", session)
                handle = attempt.termination.handle
                report["checks"]["submitted_user_prompt"] = attribute_user_prompt(history, session, handle, prompt)
                artifact_check, execution_check = _probe_checks(attempt, history)
                report["checks"].update(scratch_probe_artifacts=artifact_check, scratch_probe_execution=execution_check)
                report.update(
                    job_id=handle.job_id,
                    session_id=handle.session_id,
                    message_id=handle.message_id,
                    workspace=str(attempt.workspace.path),
                    termination_confirmed=attempt.termination.confirmed,
                    termination_diagnostics=list(attempt.termination.diagnostics),
                    task_budget_expired=attempt.task_budget_expired,
                    execution_error=attempt.execution_error,
                    functional_verifier_status=attempt.verification.status if attempt.verification else None,
                    scope_audit=attempt.scope_audit.to_dict() if attempt.scope_audit else None,
                    worker_ms=attempt.worker_ms,
                    wall_ms=attempt.wall_ms,
                    S0=attempt.s0.tree_hash,
                    S1=attempt.s1.tree_hash if attempt.s1 else None,
                )
                required = (
                    "intended_configuration",
                    "submitted_user_prompt",
                    "scratch_probe_artifacts",
                    "scratch_probe_execution",
                )
                if (
                    attempt.termination.confirmed
                    and not attempt.task_budget_expired
                    and not attempt.execution_error
                    and not attempt.scope_violations
                    and all(report["checks"][k]["status"] == "passed" for k in required)
                ):
                    report["integration_status"] = "completed_with_limitations"
                else:
                    report["integration_status"] = "incomplete"
        except asyncio.CancelledError:
            report["execution_error"] = "CallerCancelled"
            raise
        except Exception as error:
            report.update(execution_error=type(error).__name__, integration_status="incomplete")
        finally:
            # Recovery facts come from the shared attempt journal even when the
            # call raises before returning its normal frozen evidence object.
            if (evidence_dir / "lifecycle.json").is_file():
                journal = journal_at(evidence_dir)
                handle = journal.get("handle", {})
                prepared = journal.get("prepared_session", {})
                report.update(
                    job_id=handle.get("job_id"),
                    session_id=handle.get("session_id") or prepared.get("id"),
                    message_id=handle.get("message_id"),
                    workspace=journal["workspace"]["path"],
                    termination_confirmed=journal.get("termination", {}).get("confirmed") is True,
                )
            if (evidence_dir / "runtime.json").is_file():
                report["checks"]["intended_configuration"] = {
                    "status": "passed",
                    "source": "runtime.json/session-preflight.json",
                    "limitation": "Intended configuration only; provider-bound payload remains unverified",
                }
            report["submission_attempted"] = guard.submission_started
            _write_json(directory / "acceptance.json", report)
        return directory
