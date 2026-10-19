"""Offline full pipeline, canonical persistence and persistent dispatch safety."""

import asyncio
from contextlib import asynccontextmanager
import subprocess
import sys

import pytest
from benchmark_core import load_run

from attempt_test import TASK, Worker
from agent_benchmark.runner import run_benchmark, cleanup_trial
from agent_benchmark.state import command_lock, read_pending


@asynccontextmanager
async def worker_connection(**kwargs):
    yield Worker()


def run(tmp_path, connection=worker_connection):
    return asyncio.run(run_benchmark(TASK, reports=tmp_path / "reports", state=tmp_path / "state",
                                    model="test-model", connector=connection, task_seconds=.1,
                                    grace_seconds=.03, request_seconds=.1))


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
                                        model="test-model", connector=worker_connection))
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
