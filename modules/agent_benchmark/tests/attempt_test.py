"""First-attempt execution evidence with mocked worker I/O and real verification."""

import asyncio
import json
from pathlib import Path

import pytest

from agent_benchmark.attempt import run_attempt
from agent_benchmark.bridge import SubmissionUncertain
from agent_benchmark.evidence import capture, load_task, verify
from agent_benchmark.lifecycle import DispatchGuard, Observation, WorkerHandle

TASK = Path(__file__).resolve().parents[1] / "tasks/py-grep-smoke"
GOOD = "def grep(pattern, lines, ignore_case=False):\n    return [s for s in lines if (pattern.lower() in s.lower() if ignore_case else pattern in s)]\n"


class Worker:
    last_receipt = {}
    last_history = []

    def __init__(self, code=GOOD, *, unresolved=False, uncertain=False, extra=False):
        self.code, self.unresolved, self.uncertain, self.extra = code, unresolved, uncertain, extra

    async def preflight(self, directory, **kwargs):
        return {"opencode_version": "mock", **kwargs}

    async def dispatch(self, workspace, prompt, **kwargs):
        assert not (workspace / "verifier").exists()
        if self.uncertain:
            self.last_receipt = {"status": "unknown", "jobId": "partial-job"}
            raise SubmissionUncertain(self.last_receipt)
        (workspace / "grep.py").write_text(self.code, encoding="utf-8")
        if self.extra:
            (workspace / "instruction.md").write_text("changed")
        self.last_receipt = {"jobId": "job-1", "sessionId": "session-1", "messageId": "user-1"}
        return WorkerHandle("job-1", "session-1", "user-1", workspace)

    async def observe(self, handle):
        if self.unresolved:
            return Observation("cancelled", "busy", False, True, True)
        return Observation("completed", "idle", True, False, True)

    async def cancel(self, handle):
        return {"status": "cancelled"}


def attempt(tmp_path, worker, guard=None, **kwargs):
    return asyncio.run(run_attempt(
        load_task(TASK), worker, guard or DispatchGuard(), workspace_root=tmp_path / "workers",
        evidence_dir=tmp_path / "evidence", provider="lmstudio", model="test-model", agent="local-worker",
        grace_seconds=0.03, poll_seconds=0.001, **kwargs,
    ))


def test_first_attempt_is_independently_verified_and_has_owned_receipts(tmp_path):
    result = attempt(tmp_path, Worker())
    assert result.verification.status == "passed"
    assert result.termination.confirmed
    assert result.changed_paths == ("grep.py",)
    assert result.scope_violations == ()
    assert result.wall_ms >= result.verification.duration_ms
    assert (tmp_path / "evidence/S0/grep.py").read_bytes() != (tmp_path / "evidence/S1/grep.py").read_bytes()
    journal = json.loads((tmp_path / "evidence/lifecycle.json").read_text())
    assert journal["handle"]["job_id"] == "job-1"
    assert journal["workspace"]["path"] == str(result.workspace.path)
    assert journal["grace_seconds"] == 0.03
    assert (tmp_path / "evidence/worker.patch").is_file()


def test_bad_s1_remains_bad_after_coordinator_repairs_worker(tmp_path):
    result = attempt(tmp_path, Worker("def grep(*args, **kwargs): return []\n"))
    assert result.verification.status == "failed"
    (result.workspace.path / "grep.py").write_text(GOOD, encoding="utf-8")
    s3 = capture(result.workspace.path, tmp_path / "S3")
    assert verify(s3, TASK / "verifier/check.py", tmp_path / "verify3").status == "passed"
    assert result.verification.status == "failed"
    assert result.s1.files["grep.py"] != s3.files["grep.py"]


def test_correct_code_with_protected_change_has_scope_violation(tmp_path):
    result = attempt(tmp_path, Worker(extra=True))
    assert result.verification.status == "passed"
    assert result.scope_violations == ("instruction.md",)


def test_unresolved_worker_preserves_workspace_no_s1_and_halts_batch(tmp_path):
    guard = DispatchGuard()
    with pytest.warns(RuntimeWarning, match="Unresolved worker"):
        result = attempt(tmp_path, Worker(unresolved=True), guard, task_seconds=0.01)
    assert result.task_budget_expired
    assert result.s1 is None and result.verification is None
    assert result.workspace.path.exists()
    assert not (tmp_path / "evidence/S1").exists()
    assert result.termination.handle.session_id == "session-1"
    with pytest.raises(RuntimeError, match="Dispatch halted"):
        guard.allocate(tmp_path / "workers")
    assert json.loads((tmp_path / "evidence/lifecycle.json").read_text())["stage"] == "termination_unresolved"


def test_unknown_submission_is_never_retried_or_scored(tmp_path):
    guard = DispatchGuard()
    with pytest.warns(RuntimeWarning):
        result = attempt(tmp_path, Worker(uncertain=True), guard, task_seconds=0.01)
    assert result.verification is None
    assert result.s1 is None
    assert result.termination.handle.job_id == "partial-job"
    assert result.execution_error == "SubmissionUncertain"
    assert result.workspace.path.exists()
    assert json.loads((tmp_path / "evidence/dispatch.json").read_text())["status"] == "unknown"


def test_confirmed_timeout_can_freeze_evidence_without_becoming_a_pass(tmp_path):
    class SlowWorker(Worker):
        async def observe(self, handle):
            if not getattr(self, "aborted", False):
                return Observation("running", "busy", False, True, True)
            return Observation("cancelled", "idle", True, False, True)

        async def cancel(self, handle):
            self.aborted = True

    result = attempt(tmp_path, SlowWorker(), task_seconds=0.01)
    assert result.task_budget_expired
    assert result.termination.confirmed
    assert result.verification.status == "passed"
    # Canonical integration must use the expired budget fact, not simply verifier pass.


def test_external_cancellation_retains_ids_and_sticky_batch_stop(tmp_path):
    class CancelledWorker(Worker):
        async def observe(self, handle):
            raise asyncio.CancelledError()

    guard = DispatchGuard()
    with pytest.warns(RuntimeWarning):
        with pytest.raises(asyncio.CancelledError):
            attempt(tmp_path, CancelledWorker(), guard)
    assert guard.unresolved.handle.job_id == "job-1"
    journal = json.loads((tmp_path / "evidence/lifecycle.json").read_text())
    assert journal["handle"]["session_id"] == "session-1"
    assert journal["stage"] == "termination_unresolved"


def test_transport_timeout_is_not_mistaken_for_task_budget_expiration(tmp_path):
    class FlakyWorker(Worker):
        async def observe(self, handle):
            if not getattr(self, "failed_once", False):
                self.failed_once = True
                raise TimeoutError("HTTP read timed out before benchmark budget")
            return Observation("completed", "idle", True, False, True)

    result = attempt(tmp_path, FlakyWorker(), task_seconds=10)
    assert not result.task_budget_expired
    assert result.execution_error == "TimeoutError"
    assert result.termination.confirmed


def test_disk_failure_after_dispatch_still_latches_unresolved_ownership(tmp_path, monkeypatch):
    import agent_benchmark.attempt as flow
    write = flow._write_json

    def full_disk(path, data):
        if path.name == "dispatch.json":
            raise OSError("disk full after worker dispatch")
        return write(path, data)

    monkeypatch.setattr(flow, "_write_json", full_disk)
    guard = DispatchGuard()
    with pytest.warns(RuntimeWarning):
        with pytest.raises(OSError):
            attempt(tmp_path, Worker(unresolved=True), guard)
    assert guard.unresolved.handle.job_id == "job-1"
    assert guard.unresolved.handle.workspace.exists()
    with pytest.raises(RuntimeError, match="Dispatch halted"):
        guard.allocate(tmp_path / "workers")


def test_null_structured_preserves_text_worker_report(tmp_path):
    worker = Worker()
    worker.last_history = [
        {"info": {"id": "user-1", "sessionID": "session-1", "role": "user", "time": {"created": 1}}, "parts": []},
        {"info": {"id": "assistant-1", "sessionID": "session-1", "parentID": "user-1", "role": "assistant",
                  "time": {"created": 2, "completed": 3}, "finish": "stop", "structured": None},
         "parts": [{"type": "text", "text": "Worker text completion report"}]},
    ]
    result = attempt(tmp_path, worker)
    assert result.termination.confirmed
    assert (tmp_path / "evidence/worker-report.txt").read_text(encoding="utf-8") == "Worker text completion report"
    assert not (tmp_path / "evidence/worker-report.json").exists()


def test_observation_loop_recovers_from_bounded_transient_http_errors(tmp_path):
    import httpx

    class TransientFlakyWorker(Worker):
        def __init__(self):
            super().__init__()
            self.error_count = 0

        async def observe(self, handle):
            if self.error_count < 2:
                self.error_count += 1
                raise httpx.ConnectError("Transient connection drop")
            return Observation("completed", "idle", True, False, True)

    worker = TransientFlakyWorker()
    result = attempt(tmp_path, worker, task_seconds=10)
    assert not result.task_budget_expired
    assert result.execution_error is None
    assert result.termination.confirmed
    assert worker.error_count == 2


def test_observation_loop_halts_after_exceeding_max_consecutive_errors(tmp_path):
    import httpx

    class PersistentlyBrokenWorker(Worker):
        async def observe(self, handle):
            raise httpx.ConnectError("Persistent server failure")

        async def cancel(self, handle):
            return {"status": "cancelled"}

    worker = PersistentlyBrokenWorker()
    result = attempt(tmp_path, worker, task_seconds=10)
    assert result.execution_error == "ConnectError"


def test_malformed_time_in_attempt_history_does_not_crash(tmp_path):
    worker = Worker()
    worker.last_history = [
        {"info": {"id": "user-1", "sessionID": "session-1", "role": "user", "time": None}, "parts": []},
        {"info": {"id": "assistant-1", "sessionID": "session-1", "parentID": "user-1", "role": "assistant",
                  "time": None, "finish": "stop"},
         "parts": [{"type": "text", "text": "Completed successfully"}]},
    ]
    result = attempt(tmp_path, worker)
    assert result.termination.confirmed
    assert (tmp_path / "evidence/worker-report.txt").read_text(encoding="utf-8") == "Completed successfully"

