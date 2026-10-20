"""Diagnostic smoke safety and attribution; all execution is mocked/offline."""

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import subprocess
import sys

import pytest
from agent_benchmark.tool_profile import FILE_PROMPT
from agent_benchmark.diagnostic import run_diagnostic, attribute_user_prompt, probe_command
from agent_benchmark.state import read_pending
from agent_benchmark.lifecycle import WorkerHandle
from agent_benchmark.runner import cleanup_trial
from agent_benchmark.scratch import SCRATCH_NAME
from agent_benchmark.identity import ModelIdentity
from attempt_test import Worker


class DiagnosticWorker(Worker):
    def __init__(self, fault=None):
        super().__init__()
        self.fault = fault
        self.calls = []
        self.last_session = {}

    async def preflight(self, directory, **kwargs):
        self.calls.append("preflight")
        assert read_pending(self.state) is not None
        return await super().preflight(directory, **kwargs)

    async def prepare_session(self, directory, **kwargs):
        self.calls.append("session")
        if self.fault == "preflight":
            raise RuntimeError("Binding mismatch before prompt")
        value = await super().prepare_session(directory, **kwargs)
        self.last_session = value
        return value

    async def dispatch(self, workspace, prompt, **kwargs):
        self.calls.append("dispatch")
        pending = read_pending(self.state)
        data = Path(pending["evidence_dir"])
        assert (data / "submitted-prompt.txt").read_bytes() == prompt.encode("utf-8")
        assert "TMPDIR" in prompt and "temp_probe.py" in prompt
        if self.fault == "empty":
            self.last_receipt = {}
            raise ConnectionError("Submission receipt lost")
        if self.fault == "known":
            self.last_receipt = {"jobId": "known-job", "sessionId": "session-1"}
            raise ConnectionError("Known partial receipt")
        if self.fault == "cancel":
            raise asyncio.CancelledError()
        handle = await super().dispatch(workspace, prompt, **kwargs)
        user = {
            "info": {"id": handle.message_id, "sessionID": handle.session_id, "role": "user"},
            "parts": [{"type": "text", "text": prompt if self.fault != "prompt" else "different"}],
        }
        self.last_history.insert(0, user)
        self.last_session = {"id": handle.session_id, "projectID": handle.project_id, "directory": str(workspace)}
        if self.fault != "probe":
            marker = workspace / SCRATCH_NAME / "smoke-marker.txt"
            marker.write_text("trusted probe marker")
            import hashlib

            value = {
                "environment": {k: str(marker.parent) for k in ("TEMP", "TMP", "TMPDIR")},
                "tempdir": str(marker.parent),
                "marker_name": marker.name,
                "marker_sha256": hashlib.sha256(marker.read_bytes()).hexdigest(),
            }
            (marker.parent / "temp-probe.json").write_text(json.dumps(value))
            self.last_history += [
                {
                    "info": {"id": "probe-assistant", "sessionID": handle.session_id},
                    "parts": [
                        {
                            "type": "tool",
                            "tool": "shell",
                            "callID": "probe-call",
                            "state": {
                                "status": "completed",
                                "input": {"command": probe_command(), "workdir": str(workspace)},
                                "metadata": {"exit": 0},
                                "output": json.dumps(value),
                            },
                        }
                    ],
                }
            ]
        return handle


def run(tmp_path, worker=None):
    worker = worker or DiagnosticWorker()
    worker.state = tmp_path / "state"

    @asynccontextmanager
    async def connector(**kwargs):
        yield worker

    directory = asyncio.run(
        run_diagnostic(output=tmp_path / "acceptance", state=worker.state, model="test-model", connector=connector,
                       model_identity=ModelIdentity("test-model", "lmstudio", "test-model", "test-model", "Test Model", "Q4_K_M"))
    )
    return directory, json.loads((directory / "acceptance.json").read_text()), worker


def test_diagnostic_is_unscored_optional_payload_absent_and_single_dispatch(tmp_path):
    directory, report, worker = run(tmp_path)
    assert worker.calls == ["preflight", "session", "dispatch"]
    assert report["purpose"] == "integration_smoke" and report["comparison_eligible"] is False
    assert report["checks"]["intended_configuration"]["status"] == "passed"
    assert report["checks"]["submitted_user_prompt"]["status"] == "passed", report["checks"]["submitted_user_prompt"]
    assert report["checks"]["provider_payload"]["status"] == "unverified"
    assert report["checks"]["scratch_probe_artifacts"]["status"] == "passed"
    assert report["checks"]["scratch_probe_execution"]["status"] == "passed"
    assert report["scope_audit"]["compliance"] == "uncertain"
    assert report["task_seconds"] == 60 and report["grace_seconds"] == 10
    assert report["functional_verifier_status"] == "passed"
    assert report["integration_status"] == "completed_with_limitations"
    assert read_pending(worker.state) is None
    assert not any((directory / f).exists() for f in ("run.json", "trials.jsonl", "summary.json", "report.md"))
    assert (directory / "evidence/trial-001/S1" / SCRATCH_NAME / "temp-probe.json").exists()
    assert not (directory / "evidence/trial-001/verification/workspace" / SCRATCH_NAME).exists()


@pytest.mark.parametrize("fault", ["preflight", "prompt", "probe"])
def test_diagnostic_failures_are_attributed_without_extra_submission(tmp_path, fault):
    directory, report, worker = run(tmp_path, DiagnosticWorker(fault))
    assert worker.calls.count("dispatch") == (0 if fault == "preflight" else 1)
    if fault == "prompt":
        assert report["checks"]["submitted_user_prompt"]["status"] == "failed", report
    elif fault == "probe":
        assert report["checks"]["scratch_probe_artifacts"]["status"] != "passed"
    else:
        assert report["execution_error"] == "RuntimeError"
    assert report["integration_status"] not in ("completed", "completed_with_limitations")
    assert read_pending(worker.state) is None


def test_ambiguous_dispatch_persists_and_blocks_restart_and_cleanup(tmp_path):
    with pytest.warns(RuntimeWarning, match="Unresolved"):
        directory, report, worker = run(tmp_path, DiagnosticWorker("empty"))
    assert report["termination_confirmed"] is False
    assert read_pending(worker.state) is not None
    assert worker.calls.count("dispatch") == 1
    restarted = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_benchmark",
            "smoke",
            "-x",
            "-m",
            "offline",
            "-s",
            str(worker.state),
            "-o",
            str(tmp_path / "second"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert restarted.returncode != 0 and "unresolved" in restarted.stderr.lower()
    assert not (tmp_path / "second").exists()
    with pytest.raises(RuntimeError, match="unknown"):
        asyncio.run(cleanup_trial(state=worker.state, run_dir=directory, execute=True))
    assert read_pending(worker.state) is not None


def test_caller_cancel_does_not_release_unknown_dispatch(tmp_path):
    worker = DiagnosticWorker("cancel")
    with pytest.warns(RuntimeWarning, match="Unresolved"):
        with pytest.raises(asyncio.CancelledError):
            run(tmp_path, worker)
    assert read_pending(worker.state) is not None
    report_path = next((tmp_path / "acceptance").glob("*/acceptance.json"))
    assert json.loads(report_path.read_text())["execution_error"] == "CallerCancelled"


def test_user_message_attribution_checks_exact_text_id_and_directory(tmp_path):
    handle = WorkerHandle("job", "session", "message", tmp_path, "a" * 40)
    session = {"id": "session", "directory": str(tmp_path), "projectID": "a" * 40}
    history = [
        {
            "info": {"id": "message", "sessionID": "session", "role": "user"},
            "parts": [{"type": "text", "text": "expected"}],
        }
    ]
    assert attribute_user_prompt(history, session, handle, "expected")["status"] == "passed"
    assert attribute_user_prompt(history, session, handle, "different")["status"] == "failed"
    assert (
        attribute_user_prompt(history, {**session, "directory": str(tmp_path.parent)}, handle, "expected")["status"]
        == "failed"
    )
    assert attribute_user_prompt(history + history, session, handle, "expected")["status"] == "failed"
    assert attribute_user_prompt([], session, handle, "expected")["status"] == "unverified"


def test_cli_smoke_requires_execute_without_connecting(tmp_path):
    from agent_benchmark.cli import main

    assert main(["smoke", "-m", "offline", "-s", str(tmp_path / "state")]) == 2
    assert not (tmp_path / "state").exists()


def test_trusted_probe_runs_locally_with_exact_documented_command(tmp_path):
    import shutil
    from agent_benchmark.diagnostic import _fixture
    from agent_benchmark.evidence import prepare_workspace, load_task

    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell unavailable")
    task = load_task(_fixture(tmp_path / "fixture"))
    workspace = tmp_path / "workspace with spaces"
    prepare_workspace(task, workspace, scope_policy="trial-local-scratch-v1")
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", probe_command()],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    value = json.loads(result.stdout)
    assert Path(value["tempdir"]).resolve() == workspace / SCRATCH_NAME
    assert (workspace / SCRATCH_NAME / value["marker_name"]).is_file()
    assert json.loads((workspace / SCRATCH_NAME / "temp-probe.json").read_text()) == value


@pytest.mark.parametrize("failure", [None, "project", "session", "receipt"])
def test_real_adapter_preflight_precedes_dispatch_and_attributes_user_message(tmp_path, failure):
    import hashlib
    import httpx
    from agent_benchmark.bridge import OpenCodeBridge
    from bridge_isolation_test import remote
    from bridge_test import messages
    from attempt_test import GOOD

    state = tmp_path / "state"
    submitted = []
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path))
        workspace = Path(request.headers["x-opencode-directory"])
        root = subprocess.check_output(["git", "-C", str(workspace), "rev-parse", "HEAD"], text=True).strip()
        pending = read_pending(state)
        evidence = Path(pending["evidence_dir"])
        prompt = (evidence / "submitted-prompt.txt").read_text(encoding="utf-8")
        if request.method == "POST":
            assert not submitted
            assert requests.index(("GET", "/path")) < len(requests) - 1
        override = {}
        if submitted:
            assert any(method == "POST" and path == "/session" for method, path in requests)
            transcript = messages()
            transcript[0]["parts"] = [{"type": "text", "text": prompt}]
            override[("GET", "/session/session-1/message")] = transcript
        if failure == "project":
            override[("GET", "/path")] = {"directory": str(workspace), "worktree": str(workspace.parent)}
        if failure == "session":
            override[("GET", "/session/session-1")] = {
                "id": "session-1",
                "directory": str(workspace),
                "projectID": "global",
            }
        role = {
            "name": "local-worker",
            "mode": "subagent",
            "permission": [],
            "tools": {"shell": True},
            "prompt": "global role",
        }
        from agent_benchmark.tool_profile import FILE_AGENT, FILE_PROMPT
        file_role = {**role, "name": FILE_AGENT, "mode": "primary", "prompt": FILE_PROMPT, "permission": [
            {"permission": "*", "pattern": "*", "action": "deny"},
            {"permission": "read", "pattern": "*", "action": "allow"},
            {"permission": "edit", "pattern": "*", "action": "allow"}]}
        override[("GET", "/agent")] = [role, file_role]
        return remote(workspace, override, project_id=root)(request)

    async def fire(name, args):
        assert name == "opencode_fire" and args["sessionId"] == "session-1"
        assert requests[-1] == ("GET", "/session/status")
        assert not submitted
        submitted.append(args)
        (Path(args["directory"]) / "grep.py").write_text(GOOD)
        return {} if failure == "receipt" else {"jobId": "job-1", "sessionId": "session-1", "messageId": "user-1"}

    @asynccontextmanager
    async def connector(**kwargs):
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(handler)) as http:
            yield OpenCodeBridge(fire, http)

    if failure == "receipt":
        with pytest.warns(RuntimeWarning, match="Unresolved"):
            directory = asyncio.run(
                run_diagnostic(output=tmp_path / "acceptance", state=state, model="model-a", connector=connector,
                               model_identity=ModelIdentity("model-a", "lmstudio", "model-a", "model-a", "Model A", "Q4_K_M"))
            )
    else:
        directory = asyncio.run(
            run_diagnostic(output=tmp_path / "acceptance", state=state, model="model-a", connector=connector,
                           model_identity=ModelIdentity("model-a", "lmstudio", "model-a", "model-a", "Model A", "Q4_K_M"))
        )
    report = json.loads((directory / "acceptance.json").read_text())
    if failure:
        assert report["integration_status"] == "incomplete"
        assert len(submitted) == (1 if failure == "receipt" else 0)
        assert (read_pending(state) is not None) == (failure == "receipt")
        if failure == "receipt":
            assert report["session_id"] == "session-1"
        return
    assert report["checks"]["submitted_user_prompt"]["status"] == "passed", report
    assert len(submitted) == 1 and report["termination_confirmed"]
    runtime = json.loads((directory / "evidence/trial-001/runtime.json").read_text())
    assert runtime["tool_metadata"]["availability"] == "available"
    assert runtime["agent_configuration"]["prompt_sha256"] == hashlib.sha256(FILE_PROMPT.encode()).hexdigest()
    assert read_pending(state) is None


def test_known_partial_receipt_identifiers_survive_diagnostic_failure(tmp_path):
    with pytest.warns(RuntimeWarning, match="Unresolved"):
        directory, report, worker = run(tmp_path, DiagnosticWorker("known"))
    assert report["job_id"] == "known-job" and report["session_id"] == "session-1"
    assert read_pending(worker.state) is not None
    assert (directory / "evidence/trial-001/lifecycle.json").is_file()


def test_confirmed_timeout_does_not_become_diagnostic_success(tmp_path, monkeypatch):
    from agent_benchmark import diagnostic

    monkeypatch.setattr(diagnostic, "TASK_SECONDS", 0.01)

    class SlowObservation(DiagnosticWorker):
        first = True

        async def observe(self, handle):
            if self.first:
                self.first = False
                await asyncio.sleep(0.1)
            return await super().observe(handle)

    directory, report, worker = run(tmp_path, SlowObservation())
    assert report["task_budget_expired"] and report["termination_confirmed"]
    assert report["integration_status"] == "incomplete"
    assert report["functional_verifier_status"] == "passed"
    assert read_pending(worker.state) is None
    assert worker.calls.count("dispatch") == 1


def test_completed_diagnostic_cleanup_uses_existing_reconciliation(tmp_path):
    directory, report, worker = run(tmp_path)
    before = (directory / "acceptance.json").read_bytes()

    @asynccontextmanager
    async def connector(**kwargs):
        yield Worker()

    preview = asyncio.run(cleanup_trial(state=worker.state, run_dir=directory, execute=False))
    assert preview["execute_required"] and Path(report["workspace"]).is_dir()
    outcome = asyncio.run(cleanup_trial(state=worker.state, run_dir=directory, execute=True, connector=connector))
    assert outcome["termination_confirmed"] and outcome["removed"]
    assert (directory / "acceptance.json").read_bytes() == before
    assert read_pending(worker.state) is None


@pytest.mark.parametrize("fault", [None, "empty"])
def test_acceptance_write_failure_does_not_release_potentially_active_worker(tmp_path, monkeypatch, fault):
    from agent_benchmark import diagnostic

    write = diagnostic._write_json

    def failing(path, value):
        if path.name == "acceptance.json":
            raise OSError("Cannot persist diagnostic report")
        return write(path, value)

    monkeypatch.setattr(diagnostic, "_write_json", failing)
    if fault:
        with pytest.warns(RuntimeWarning, match="Unresolved"):
            with pytest.raises(OSError):
                run(tmp_path, DiagnosticWorker(fault))
    else:
        with pytest.raises(OSError):
            run(tmp_path)
    assert (read_pending(tmp_path / "state") is not None) == bool(fault)
