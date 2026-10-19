"""Offline regressions for the final cancellation/cleanup amendment."""

import asyncio
from collections import deque
from dataclasses import replace
import time

import pytest

from agent_benchmark.lifecycle import (
    DispatchGuard, Observation, WorkerHandle, cleanup_workspace, confirm_termination,
)


class Bridge:
    def __init__(self, observations, *, cancel_delay=0, observation_delay=0, cancel_error=False):
        self.observations = deque(observations)
        self.cancel_delay = cancel_delay
        self.observation_delay = observation_delay
        self.cancel_error = cancel_error

    async def cancel(self, handle):
        await asyncio.sleep(self.cancel_delay)
        if self.cancel_error:
            raise ConnectionError("offline")
        return {"status": "cancelled"}  # An acknowledgement is deliberately untrusted.

    async def observe(self, handle):
        await asyncio.sleep(self.observation_delay)
        if len(self.observations) > 1:
            item = self.observations.popleft()
        else:
            item = self.observations[0]
        if isinstance(item, Exception):
            raise item
        return item


def handle_for(workspace):
    return WorkerHandle("job-1", "session-1", "message-1", workspace.path)


def idle():
    return Observation("completed", "idle", True, False, True)


def decide(bridge, handle, **kwargs):
    return asyncio.run(confirm_termination(bridge, handle, grace_seconds=0.03, poll_seconds=0.001, **kwargs))


def test_observation_timeout_and_cancel_ack_do_not_authorize_deletion(tmp_path):
    workspace = DispatchGuard().allocate(tmp_path)
    marker = workspace.path / "worker.py"
    marker.write_text("still writing")
    bridge = Bridge([Observation("cancelled", "busy", False, True, True)])
    result = decide(bridge, handle_for(workspace))
    assert not result.confirmed
    assert result.cancellation_requested
    assert not cleanup_workspace(workspace, result).removed
    assert marker.read_text() == "still writing"
    assert result.handle == WorkerHandle("job-1", "session-1", "message-1", workspace.path)
    assert result.diagnostics


@pytest.mark.parametrize("observation", [
    Observation("cancelled", None, False, False, False),
    Observation("completed", "idle", True, True, True),
    Observation("failed", "busy", True, False, True),
    Observation("completed", "idle", True, False, False),
    Observation("cancelled", "idle", False, False, True),
])
def test_cached_or_uncorrelated_or_running_tools_cannot_confirm(tmp_path, observation):
    workspace = DispatchGuard().allocate(tmp_path)
    assert not decide(Bridge([observation]), handle_for(workspace)).confirmed


def test_fresh_correlated_idle_finished_turn_can_confirm(tmp_path):
    workspace = DispatchGuard().allocate(tmp_path)
    bridge = Bridge([Observation("running", "busy", False, True, True), idle()])
    result = decide(bridge, handle_for(workspace))
    assert result.confirmed
    assert cleanup_workspace(workspace, result).removed
    assert not workspace.path.exists()


@pytest.mark.parametrize("delay_kind", ["cancel_delay", "observation_delay"])
def test_confirmation_deadline_bounds_slow_remote_calls(tmp_path, delay_kind):
    workspace = DispatchGuard().allocate(tmp_path)
    bridge = Bridge([idle()], **{delay_kind: 1})
    start = time.monotonic()
    result = decide(bridge, handle_for(workspace))
    assert time.monotonic() - start < 0.5
    assert not result.confirmed
    assert result.grace_seconds == 0.03
    assert workspace.path.exists()


def test_transport_failure_preserves_diagnostics_and_halts_next_dispatch(tmp_path):
    guard = DispatchGuard()
    workspace = guard.allocate(tmp_path)
    result = decide(Bridge([ConnectionError("offline")]), handle_for(workspace))
    with pytest.warns(RuntimeWarning, match="Unresolved worker"):
        guard.record(result)
    with pytest.raises(RuntimeError, match="job-1"):
        guard.allocate(tmp_path)
    assert result.handle.session_id == "session-1"
    assert result.handle.message_id == "message-1"
    assert workspace.path.exists()
    assert any("ConnectionError" in item for item in result.diagnostics)
    # A later unrelated result cannot silently unlatch the batch stop.
    guard.record(replace(result, confirmed=True))
    with pytest.raises(RuntimeError):
        guard.allocate(tmp_path)


def test_cancel_error_can_be_reconciled_by_fresh_finished_state(tmp_path):
    workspace = DispatchGuard().allocate(tmp_path)
    result = decide(Bridge([idle()], cancel_error=True), handle_for(workspace))
    assert result.confirmed
    assert any("ConnectionError" in item for item in result.diagnostics)


def test_each_dispatch_gets_fresh_workspace_even_after_cleanup(tmp_path):
    guard = DispatchGuard()
    first = guard.allocate(tmp_path)
    result = decide(Bridge([idle()]), handle_for(first))
    assert cleanup_workspace(first, result).removed
    second = guard.allocate(tmp_path)
    assert first.path != second.path
    assert second.path.is_dir()


def test_cleanup_failure_does_not_change_verified_result(tmp_path, monkeypatch):
    workspace = DispatchGuard().allocate(tmp_path)
    decision = decide(Bridge([idle()]), handle_for(workspace))
    original_decision = decision

    def locked(path, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr("agent_benchmark.lifecycle.shutil.rmtree", locked)
    outcome = cleanup_workspace(workspace, decision, attempts=2, retry_seconds=0)
    assert not outcome.removed
    assert outcome.attempts == 2
    assert outcome.diagnostic
    assert decision == original_decision
    assert decision.confirmed
    assert workspace.path.exists()
    guard = DispatchGuard()
    guard.record(decision)
    assert guard.allocate(tmp_path).path != workspace.path


def test_transient_windows_lock_retries_then_removes_only_owned_directory(tmp_path, monkeypatch):
    import shutil
    real_remove = shutil.rmtree
    guard = DispatchGuard()
    workspace = guard.allocate(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    calls = []

    def once_locked(path, **kwargs):
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError("temporary Windows lock")
        real_remove(path, **kwargs)

    monkeypatch.setattr("agent_benchmark.lifecycle.shutil.rmtree", once_locked)
    outcome = cleanup_workspace(workspace, decide(Bridge([idle()]), handle_for(workspace)), retry_seconds=0)
    assert outcome.removed and outcome.attempts == 2
    assert unrelated.is_dir()


def test_mismatched_workspace_is_never_deleted(tmp_path):
    guard = DispatchGuard()
    first = guard.allocate(tmp_path)
    second = guard.allocate(tmp_path)
    decision = decide(Bridge([idle()]), handle_for(first))
    assert not cleanup_workspace(second, decision).removed
    assert second.path.is_dir() and first.path.is_dir()


def test_directory_moved_outside_owned_root_is_never_deleted(tmp_path):
    workspace = DispatchGuard().allocate(tmp_path / "owned")
    outside = tmp_path / "outside"
    outside.mkdir()
    forged = replace(workspace, path=outside)
    decision = decide(Bridge([idle()]), handle_for(forged))
    assert not cleanup_workspace(forged, decision).removed
    assert outside.is_dir()


def test_symlink_replacement_is_never_followed(tmp_path):
    workspace = DispatchGuard().allocate(tmp_path / "owned")
    decision = decide(Bridge([idle()]), handle_for(workspace))
    workspace.path.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        workspace.path.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    assert not cleanup_workspace(workspace, decision).removed
    assert outside.is_dir()


def test_no_shared_process_operations_during_cleanup(tmp_path, monkeypatch):
    import os
    import subprocess

    def forbidden(*args, **kwargs):
        pytest.fail("Cleanup must not inspect, start or kill shared processes")

    monkeypatch.setattr(os, "kill", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    workspace = DispatchGuard().allocate(tmp_path)
    result = decide(Bridge([idle()]), handle_for(workspace))
    assert cleanup_workspace(workspace, result).removed


@pytest.mark.parametrize("budget", [0, -1, float("inf"), float("nan")])
def test_invalid_confirmation_budget_rejected_before_remote_work(tmp_path, budget):
    workspace = DispatchGuard().allocate(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(confirm_termination(Bridge([idle()]), handle_for(workspace), grace_seconds=budget))


def test_normal_completion_reconciles_without_sending_abort(tmp_path):
    class FinishedBridge(Bridge):
        async def cancel(self, handle):
            raise AssertionError("Normal completion must not request cancellation")

    workspace = DispatchGuard().allocate(tmp_path)
    result = decide(FinishedBridge([idle()]), handle_for(workspace), cancel_first=False)
    assert result.confirmed
    assert not result.cancellation_requested


def test_non_lock_cleanup_failure_is_not_retried(tmp_path, monkeypatch):
    workspace = DispatchGuard().allocate(tmp_path)
    decision = decide(Bridge([idle()]), handle_for(workspace))

    def failed(path, **kwargs):
        raise OSError("unexpected filesystem failure")

    monkeypatch.setattr("agent_benchmark.lifecycle.shutil.rmtree", failed)
    result = cleanup_workspace(workspace, decision, retry_seconds=0)
    assert not result.removed and result.attempts == 1
    assert workspace.path.exists()


@pytest.mark.parametrize("failure_stage", ["cancel", "observe"])
def test_custom_transport_errors_return_unresolved_decision(tmp_path, failure_stage):
    class TransportFailure(Exception):
        pass

    class BrokenBridge(Bridge):
        async def cancel(self, handle):
            if failure_stage == "cancel":
                raise TransportFailure("submission uncertain")
            return None

        async def observe(self, handle):
            raise TransportFailure("remote state unavailable")

    guard = DispatchGuard()
    workspace = guard.allocate(tmp_path)
    result = decide(BrokenBridge([]), handle_for(workspace))
    assert not result.confirmed
    assert any("TransportFailure" in item for item in result.diagnostics)
    with pytest.warns(RuntimeWarning):
        guard.record(result)
    with pytest.raises(RuntimeError):
        guard.allocate(tmp_path)
    assert workspace.path.exists()


def test_external_cancellation_propagates_without_authorizing_cleanup(tmp_path):
    class CancelledBridge(Bridge):
        async def cancel(self, handle):
            raise asyncio.CancelledError()

    workspace = DispatchGuard().allocate(tmp_path)
    with pytest.raises(asyncio.CancelledError):
        decide(CancelledBridge([]), handle_for(workspace))
    assert workspace.path.exists()



def test_readonly_git_objects_removed_only_after_confirmed_termination(tmp_path):
    from agent_benchmark.evidence import load_task, prepare_workspace
    from attempt_test import TASK
    workspace = DispatchGuard().allocate(tmp_path)
    prepare_workspace(load_task(TASK), workspace.path)
    decision = decide(Bridge([idle()]), handle_for(workspace))
    unconfirmed = replace(decision, confirmed=False)
    assert not cleanup_workspace(workspace, unconfirmed).removed
    assert (workspace.path / ".git/objects").is_dir()
    assert cleanup_workspace(workspace, decision).removed
    assert not workspace.path.exists()


def test_git_readonly_cleanup_handler_never_changes_unrelated_paths(tmp_path, monkeypatch):
    import os
    workspace = DispatchGuard().allocate(tmp_path / "owned")
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("retained")
    decision = decide(Bridge([idle()]), handle_for(workspace))
    chmods = []
    monkeypatch.setattr("agent_benchmark.lifecycle.os.chmod", lambda *args: chmods.append(args))
    def permission_failure(path, *, onexc):
        onexc(os.unlink, unrelated, PermissionError("outside owned Git directory"))
    monkeypatch.setattr("agent_benchmark.lifecycle.shutil.rmtree", permission_failure)
    assert not cleanup_workspace(workspace, decision, attempts=1).removed
    assert not chmods and unrelated.read_text() == "retained"
