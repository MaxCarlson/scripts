"""Focused final-review regressions; no services or inference."""

from contextlib import asynccontextmanager
import json
from pathlib import Path

import pytest
from benchmark_core import load_run
from agent_benchmark import evidence as ev
from agent_benchmark import attempt as flow
from agent_benchmark.scratch import SCOPE_POLICY, SCRATCH_NAME
from agent_benchmark.state import read_pending
from scratch_policy_test import history
from attempt_test import TASK, Worker
from runner_test import run


@pytest.mark.parametrize("target", [SCRATCH_NAME + "/test.py ", " " + SCRATCH_NAME + "/test.py"])
def test_whitespace_targets_do_not_gain_scratch_permission(tmp_path, target):
    task = ev.load_task(TASK)
    worker = tmp_path / "worker"
    ev.prepare_workspace(task, worker, scope_policy=SCOPE_POLICY)
    snap = ev.capture(worker, tmp_path / "S0")
    audit = ev.audit_scope(task, worker, snap, snap, history(target), scope_policy=SCOPE_POLICY)
    assert audit.compliance != "compliant"


@pytest.mark.parametrize("kind", ["file", "total", "entries"])
def test_capture_limits_fail_before_creating_partial_snapshot(tmp_path, kind):
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "unexpected.bin").write_bytes(b"0123456789")
    (worker / "another.bin").write_bytes(b"abcdefghij")
    (worker / "empty-directory").mkdir()
    limits = ev.CaptureLimits(
        max_file_bytes=8 if kind == "file" else 16,
        max_total_bytes=18 if kind == "total" else 32,
        max_entries=2 if kind == "entries" else 8,
    )
    destination = tmp_path / "S1"
    with pytest.raises(ev.EvidenceLimitExceeded) as error:
        ev.capture(worker, destination, limits=limits)
    assert kind in str(error.value)
    assert not destination.exists() and (worker / "unexpected.bin").stat().st_size == 10


def test_limits_preserve_exact_bytes_and_bound_archive_integrity_read(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "odd.bin").write_bytes(bytes(range(100)))
    limits = ev.CaptureLimits(max_file_bytes=100, max_total_bytes=100, max_entries=2)
    snap = ev.capture(worker, tmp_path / "S1", limits=limits)
    snap.check_intact()
    assert snap.files["odd.bin"] == bytes(range(100))
    (snap.path / "odd.bin").write_bytes(b"x" * 101)
    with pytest.raises(ev.EvidenceLimitExceeded):
        snap.check_intact()


def test_patch_bounded_and_scratch_payload_not_duplicated(tmp_path):
    worker = tmp_path / "worker"
    ev.prepare_workspace(ev.load_task(TASK), worker, scope_policy=SCOPE_POLICY)
    s0 = ev.capture(worker, tmp_path / "S0")
    (worker / SCRATCH_NAME / "test.py").write_text("UNIQUE_SCRATCH_PAYLOAD" * 1000)
    (worker / "grep.py").write_text("changed task")
    s1 = ev.capture(worker, tmp_path / "S1")
    patch = flow._patch(s0, s1, max_bytes=128, scope_policy=SCOPE_POLICY)
    assert len(patch.encode()) <= 128
    assert "UNIQUE_SCRATCH_PAYLOAD" not in patch
    assert "snapshot" in patch.lower()


def test_pipeline_limit_failure_preserves_workspace_diagnostic_and_one_result(tmp_path, monkeypatch):
    monkeypatch.setattr(
        flow, "EVIDENCE_LIMITS", ev.CaptureLimits(max_file_bytes=4096, max_total_bytes=16384, max_entries=100)
    )

    class OversizedWorker(Worker):
        async def dispatch(self, workspace, prompt, **kwargs):
            (workspace / SCRATCH_NAME / "huge.bin").write_bytes(b"x" * 4097)
            return await super().dispatch(workspace, prompt, **kwargs)

    @asynccontextmanager
    async def connector(**kwargs):
        yield OversizedWorker()

    directory = run(tmp_path, connector)
    info, trials = load_run(directory)
    assert len(trials) == 1 and trials[0].status == "infrastructure_error"
    data = directory / "evidence/trial-001"
    journal = json.loads((data / "lifecycle.json").read_text())
    assert journal["termination"]["confirmed"] and journal["stage"] == "evidence_limited"
    assert Path(journal["workspace"]["path"]).is_dir()
    assert not (data / "S1").exists() and not (data / "verification").exists()
    diagnostic = json.loads((data / "evidence-limit.json").read_text())
    assert "huge.bin" in diagnostic["path"] and diagnostic["complete_snapshot"] is False
    assert info.metadata["evidence_limits"]["max_file_bytes"] > 0
    assert read_pending(tmp_path / "state") is None


def test_s0_limit_failure_preserves_ownership_and_never_calls_worker_preflight(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "EVIDENCE_LIMITS", ev.CaptureLimits(max_file_bytes=4))

    class NoPreflight(Worker):
        async def preflight(self, *args, **kwargs):
            pytest.fail("S0 resource failure must precede remote preflight")

    @asynccontextmanager
    async def connector(**kwargs):
        yield NoPreflight()

    directory = run(tmp_path, connector)
    _, trials = load_run(directory)
    assert len(trials) == 1 and trials[0].status == "infrastructure_error"
    data = directory / "evidence/trial-001"
    journal = json.loads((data / "lifecycle.json").read_text())
    assert journal["stage"] == "not_submitted"
    assert journal["evidence_capture"]["checkpoint"] == "S0"
    assert Path(journal["workspace"]["path"]).is_dir()
    assert (data / "evidence-limit.json").exists()
    assert read_pending(tmp_path / "state") is None


@pytest.mark.parametrize("workdir", [" " + SCRATCH_NAME, SCRATCH_NAME + " "])
def test_whitespace_workdirs_are_not_silently_normalized_into_permission(tmp_path, workdir):
    task = ev.load_task(TASK)
    worker = tmp_path / "worker"
    ev.prepare_workspace(task, worker, scope_policy=SCOPE_POLICY)
    snap = ev.capture(worker, tmp_path / "S0")
    transcript = history("test.py")
    transcript[0]["parts"][0]["state"]["input"]["workdir"] = workdir
    audit = ev.audit_scope(task, worker, snap, snap, transcript, scope_policy=SCOPE_POLICY)
    assert audit.compliance != "compliant"
