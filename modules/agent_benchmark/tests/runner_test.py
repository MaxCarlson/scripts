"""Offline full pipeline, canonical persistence and persistent dispatch safety."""

import asyncio
from contextlib import asynccontextmanager
import subprocess
import sys
from pathlib import Path

import pytest
from benchmark_core import load_run

from attempt_test import TASK, Worker
from agent_benchmark.runner import run_benchmark, cleanup_trial, reconcile_pending
from agent_benchmark.identity import ModelIdentity
from agent_benchmark.state import command_lock, read_pending


@asynccontextmanager
async def worker_connection(**kwargs):
    yield Worker()


def run(tmp_path, connection=worker_connection):
    return asyncio.run(run_benchmark(TASK, reports=tmp_path / "reports", state=tmp_path / "state",
                                    model="test-model", connector=connection, task_seconds=.1,
                                    grace_seconds=.03, request_seconds=.1,
                                    model_identity=ModelIdentity("test-model", "lmstudio", "test-model",
                                                                 "test-model", "Test Model", "Q4_K_M")))


def test_full_offline_pipeline_persists_one_canonical_result_and_core_reports(tmp_path):
    run_dir = run(tmp_path)
    info, trials = load_run(run_dir)
    assert info.scoring_basis == "worker_first_attempt_full_success"
    assert info.metadata["cancel_grace_seconds"] == .03
    assert len(trials) == 1 and trials[0].status == "passed"
    assert trials[0].metrics["tokens.worker.output"].value is None
    assert all((run_dir / name).is_file() for name in ["run.json", "trials.jsonl", "summary.json", "summary.csv", "report.md"])
    assert read_pending(tmp_path / "state") is None


def test_unreachable_runtime_is_one_infrastructure_result_with_no_worker(tmp_path):
    @asynccontextmanager
    async def unreachable(**kwargs):
        raise ConnectionError("offline")
        yield
    run_dir = run(tmp_path, unreachable)
    _, trials = load_run(run_dir)
    assert len(trials) == 1 and trials[0].status == "infrastructure_error"
    assert read_pending(tmp_path / "state") is None


def test_unresolved_job_blocks_new_process_before_runtime_connection(tmp_path):
    @asynccontextmanager
    async def unresolved(**kwargs):
        yield Worker(unresolved=True)
    with pytest.warns(RuntimeWarning):
        run_dir = run(tmp_path, unresolved)
    _, trials = load_run(run_dir)
    assert len(trials) == 1 and trials[0].status == "infrastructure_error"
    assert read_pending(tmp_path / "state") is not None
    process = subprocess.run([sys.executable, "-m", "agent_benchmark", "run", "-x", "-m", "other-model",
                              "-o", str(tmp_path / "other-reports"), "-s", str(tmp_path / "state")],
                             capture_output=True, text=True, timeout=10)
    assert process.returncode != 0
    assert "unresolved" in process.stderr.lower()
    assert not (tmp_path / "other-reports").exists()


def test_pending_reconciliation_failure_names_unresolved_worker(tmp_path):
    @asynccontextmanager
    async def unresolved(**kwargs):
        yield Worker(unresolved=True)

    with pytest.warns(RuntimeWarning):
        run_dir = run(tmp_path, unresolved)
    assert read_pending(tmp_path / "state") is not None

    @asynccontextmanager
    async def offline(**kwargs):
        raise ConnectionError("offline reconciliation transport")
        yield

    with pytest.raises(RuntimeError, match="remains unresolved"):
        asyncio.run(reconcile_pending(state=tmp_path / "state", connector=offline))
    assert read_pending(tmp_path / "state") is not None
    assert (run_dir / "evidence/trial-001/lifecycle.json").is_file()


def test_cleanup_requires_fresh_confirmation_and_does_not_rescore(tmp_path):
    @asynccontextmanager
    async def unresolved(**kwargs):
        yield Worker(unresolved=True)
    with pytest.warns(RuntimeWarning):
        run_dir = run(tmp_path, unresolved)
    before = (run_dir / "trials.jsonl").read_bytes()
    result = asyncio.run(cleanup_trial(state=tmp_path / "state", execute=True, connector=worker_connection))
    assert result["termination_confirmed"]
    assert result["removed"]
    assert read_pending(tmp_path / "state") is None
    assert (run_dir / "trials.jsonl").read_bytes() == before


def test_preview_cleanup_has_no_effect_and_uncertain_cleanup_keeps_dispatch_blocked(tmp_path):
    @asynccontextmanager
    async def unresolved(**kwargs):
        yield Worker(unresolved=True)
    with pytest.warns(RuntimeWarning):
        run(tmp_path, unresolved)
    preview = asyncio.run(cleanup_trial(state=tmp_path / "state", execute=False))
    assert not preview["removed"]
    assert read_pending(tmp_path / "state") is not None
    with pytest.warns(RuntimeWarning):
        result = asyncio.run(cleanup_trial(state=tmp_path / "state", execute=True, connector=unresolved, grace_seconds=.02))
    assert not result["termination_confirmed"] and not result["removed"]
    assert read_pending(tmp_path / "state") is not None


def test_active_command_lock_prevents_concurrent_dispatch(tmp_path):
    with command_lock(tmp_path / "state"):
        with pytest.raises(RuntimeError, match="active"):
            run(tmp_path)


def test_corrupt_pending_receipt_fails_closed(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "pending.json").write_text("corrupt")
    with pytest.raises(RuntimeError, match="pending|unresolved"):
        run(tmp_path)
    assert not (tmp_path / "reports").exists()


def test_failure_before_dispatch_does_not_leave_unrecoverable_pending_receipt(tmp_path):
    import shutil
    task = tmp_path / "broken-task"
    shutil.copytree(TASK, task)
    shutil.rmtree(task / "seed")
    run_dir = asyncio.run(run_benchmark(task, reports=tmp_path / "reports", state=tmp_path / "state",
                                        model="test-model", connector=worker_connection,
                                        model_identity=ModelIdentity("test-model", "lmstudio", "test-model",
                                                                     "test-model", "Test Model", "Q4_K_M")))
    assert load_run(run_dir)[1][0].status == "infrastructure_error"
    assert read_pending(tmp_path / "state") is None


def test_cleanup_refuses_mismatched_recorded_handle_workspace(tmp_path):
    import json
    run_dir = run(tmp_path)
    path = run_dir / "evidence/trial-001/lifecycle.json"
    journal = json.loads(path.read_text())
    journal["handle"]["workspace"] = str(tmp_path / "unrelated")
    path.write_text(json.dumps(journal))
    with pytest.raises(RuntimeError, match="workspace"):
        asyncio.run(cleanup_trial(state=tmp_path / "state", run_dir=run_dir, execute=True, connector=worker_connection))


def test_external_cancel_persists_one_infrastructure_result_and_pending_receipt(tmp_path):
    class CancelledWorker(Worker):
        async def observe(self, handle):
            raise asyncio.CancelledError()
    @asynccontextmanager
    async def cancelled(**kwargs):
        yield CancelledWorker()
    with pytest.warns(RuntimeWarning):
        with pytest.raises(asyncio.CancelledError):
            run(tmp_path, cancelled)
    directories = list((tmp_path / "reports").iterdir())
    assert len(directories) == 1
    trials = load_run(directories[0])[1]
    assert len(trials) == 1 and trials[0].status == "infrastructure_error"
    assert read_pending(tmp_path / "state") is not None


@pytest.mark.parametrize("response", [{}, None, [], {"jobId": "known-job"}, "transport", "empty_error", "known_error", "lost_receipt",
                                      {"jobId": 17, "sessionId": [], "messageId": None}])
def test_unknown_submission_survives_restart_and_refuses_dispatch(tmp_path, response):
    import json
    import httpx
    from agent_benchmark.bridge import OpenCodeBridge, SubmissionUncertain

    class UncertainBridge(OpenCodeBridge):
        async def dispatch(self, *args, **kwargs):
            if response == "lost_receipt":
                self.last_receipt = {}
                raise ConnectionError("Submission may exist despite missing receipt")
            return await super().dispatch(*args, **kwargs)

        async def preflight(self, directory, **kwargs):
            return {"version": "offline"}

        async def prepare_session(self, directory, *, project_id):
            # Mock empty-session API binding; actual API validation has separate transport tests.
            self.project_context = {"id": project_id, "directory": str(directory)}
            self.prepared_session = {"id": "session-1", "projectID": project_id, "directory": str(directory)}
            return self.prepared_session

    async def fire(name, args):
        if response == "transport":
            raise ConnectionError("Response lost after submission")
        if response == "known_error":
            raise SubmissionUncertain({"jobId": "known-job"})
        if response == "empty_error":
            raise SubmissionUncertain({})
        return response

    @asynccontextmanager
    async def connection(**kwargs):
        async with httpx.AsyncClient() as http:
            yield UncertainBridge(fire, http)

    with pytest.warns(RuntimeWarning, match="Unresolved"):
        run_dir = run(tmp_path, connection)
    assert load_run(run_dir)[1][0].status == "infrastructure_error"
    assert read_pending(tmp_path / "state") is not None
    evidence = run_dir / "evidence/trial-001"
    journal = json.loads((evidence / "lifecycle.json").read_text())
    assert journal["stage"] == "termination_unresolved"
    assert not journal["termination"]["confirmed"]
    assert (evidence / "S0").is_dir() and not (evidence / "S1").exists()
    assert Path(journal["workspace"]["path"]).is_dir()
    if response == "known_error" or (isinstance(response, dict) and response.get("jobId") == "known-job"):
        assert journal["handle"]["job_id"] == "known-job"
        assert json.loads((evidence / "dispatch.json").read_text())["jobId"] == "known-job"
    restarted = subprocess.run(
        [sys.executable, "-m", "agent_benchmark", "run", "-x", "-m", "offline",
         "-s", str(tmp_path / "state"), "-o", str(tmp_path / "second-reports")],
        capture_output=True, text=True, timeout=10,
    )
    assert restarted.returncode != 0 and "unresolved" in restarted.stderr.lower()
    assert not (tmp_path / "second-reports").exists()



def test_post_submission_evidence_failure_preserves_ids_and_pending_receipt(tmp_path, monkeypatch):
    import json
    import agent_benchmark.attempt as flow
    write = flow._write_json

    def fail_dispatch_evidence(path, data):
        if path.name == "dispatch.json":
            raise OSError("dispatch evidence cannot be persisted")
        return write(path, data)

    monkeypatch.setattr(flow, "_write_json", fail_dispatch_evidence)
    with pytest.warns(RuntimeWarning, match="Unresolved"):
        run_dir = run(tmp_path)
    assert read_pending(tmp_path / "state") is not None
    assert load_run(run_dir)[1][0].status == "infrastructure_error"
    journal = json.loads((run_dir / "evidence/trial-001/lifecycle.json").read_text())
    assert journal["handle"]["job_id"] == "job-1"
    assert journal["handle"]["session_id"] == "session-1"
    assert journal["handle"]["message_id"] == "user-1"



@pytest.mark.parametrize("failure", ["project", "session", None])
def test_real_adapter_project_gate_and_canonical_provenance_offline(tmp_path, failure):
    import json
    import httpx
    from agent_benchmark.bridge import OpenCodeBridge
    from agent_benchmark.git_workspace import ISOLATION_POLICY
    from attempt_test import GOOD
    from bridge_test import messages
    from bridge_isolation_test import remote
    from project_isolation_test import git

    requests, submissions = [], []
    state = {"submitted": False}
    def service(request):
        directory = Path(request.headers["x-opencode-directory"])
        project = git(directory, "rev-parse", "HEAD")
        overrides = {}
        if failure == "project":
            overrides[("GET", "/path")] = {"directory": str(directory), "worktree": str(directory.parent)}
        if failure == "session":
            overrides[("GET", "/session/session-1")] = {"id": "session-1", "directory": str(directory), "projectID": "global"}
        if state["submitted"]:
            overrides[("GET", "/session/session-1/message")] = messages()
        return remote(directory, overrides, requests, project_id=project)(request)
    async def submit(name, args):
        submissions.append(args)
        assert failure is None and args["sessionId"] == "session-1"
        (Path(args["directory"]) / "grep.py").write_text(GOOD, encoding="utf-8")
        state["submitted"] = True
        return {"jobId": "job-1", "sessionId": "session-1", "messageId": "user-1"}
    @asynccontextmanager
    async def connection(**kwargs):
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(service)) as http:
            yield OpenCodeBridge(submit, http)
    run_dir = asyncio.run(run_benchmark(TASK, reports=tmp_path / "reports", state=tmp_path / "state",
                                        model="model-a", connector=connection, task_seconds=2,
                                        model_identity=ModelIdentity("model-a", "lmstudio", "model-a",
                                                                     "model-a", "Model A", "Q4_K_M")))
    info, trials = load_run(run_dir)
    assert len(trials) == 1
    assert read_pending(tmp_path / "state") is None
    assert info.metadata["isolation_policy"] == ISOLATION_POLICY
    journal = json.loads((run_dir / "evidence/trial-001/lifecycle.json").read_text())
    assert journal["git"]["root_commit"]
    if failure:
        assert not submissions and trials[0].status == "infrastructure_error"
        assert journal["stage"] == "preflight_failed"
        assert not (run_dir / "evidence/trial-001/dispatch.json").exists()
        if failure == "session":
            persisted = json.loads((run_dir / "evidence/trial-001/session-preflight.json").read_text())
            assert persisted["persisted"]["projectID"] == "global"
    else:
        assert len(submissions) == 1 and trials[0].status == "passed"
        runtime = info.metadata["runtime"]
        assert runtime["project"]["id"] == runtime["git"]["root_commit"] == trials[0].details["project_id"]
        assert runtime["session"]["projectID"] == trials[0].details["project_id"]
