"""Independent filesystem evidence and verifier boundary regressions."""

from pathlib import Path

import pytest

from agent_benchmark.evidence import capture, changed_paths, load_task, prepare_workspace, verify

TASK = Path(__file__).resolve().parents[1] / "tasks" / "py-grep-smoke"
GOOD = "def grep(pattern, lines, ignore_case=False):\n    return [s for s in lines if (pattern.lower() in s.lower() if ignore_case else pattern in s)]\n"


def test_s1_bytes_survive_later_coordinator_repair(tmp_path):
    worker = tmp_path / "worker"
    prepare_workspace(load_task(TASK), worker)
    s0 = capture(worker, tmp_path / "S0")
    (worker / "grep.py").write_bytes(b"def grep(*args, **kwargs): return []\n")
    s1 = capture(worker, tmp_path / "S1")
    first = verify(s1, TASK / "verifier/check.py", tmp_path / "verify1", timeout_seconds=2)
    (worker / "grep.py").write_text(GOOD, encoding="utf-8")
    s3 = capture(worker, tmp_path / "S3")
    repaired = verify(s3, TASK / "verifier/check.py", tmp_path / "verify3", timeout_seconds=2)
    assert first.status == "failed"
    assert repaired.status == "passed"
    assert s1.files["grep.py"] == b"def grep(*args, **kwargs): return []\n"
    assert changed_paths(s0, s1) == ["grep.py"]
    assert s1.tree_hash != s3.tree_hash
    assert "Traceback" not in first.stdout


def test_snapshot_cannot_be_overwritten_or_modified_through_mapping(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "bytes.bin").write_bytes(b"\xff\x00\r\n")
    snap = capture(worker, tmp_path / "S1")
    assert (snap.path / "bytes.bin").read_bytes() == b"\xff\x00\r\n"
    with pytest.raises(TypeError):
        snap.files["new"] = b"bad"
    with pytest.raises(FileExistsError):
        capture(worker, snap.path)


def test_authoritative_verifier_runs_on_disposable_copy(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "grep.py").write_text("seed")
    snap = capture(worker, tmp_path / "S1")
    verifier = tmp_path / "check.py"
    verifier.write_text("import sys; from pathlib import Path; (Path(sys.argv[1]) / 'grep.py').write_text('modified')")
    result = verify(snap, verifier, tmp_path / "verification", timeout_seconds=2)
    assert result.status == "passed"
    assert (snap.path / "grep.py").read_text() == "seed"


def test_verifier_failures_are_distinct_and_output_retained(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    snap = capture(worker, tmp_path / "S1")
    verifier = tmp_path / "check.py"
    verifier.write_text("import sys; print('diagnostic'); sys.exit(2)")
    result = verify(snap, verifier, tmp_path / "infra", timeout_seconds=2)
    assert result.status == "infrastructure_error"
    assert "diagnostic" in (tmp_path / "infra/stdout.txt").read_text()
    verifier.write_text("import time; time.sleep(5)")
    assert verify(snap, verifier, tmp_path / "timeout", timeout_seconds=0.03).status == "timed_out"


def test_changed_protected_added_and_deleted_files_are_all_auditable(tmp_path):
    worker = tmp_path / "worker"
    prepare_workspace(load_task(TASK), worker)
    s0 = capture(worker, tmp_path / "S0")
    (worker / "grep.py").unlink()
    (worker / "instruction.md").write_text("tampered")
    (worker / "extra.txt").write_text("new")
    assert changed_paths(s0, capture(worker, tmp_path / "S1")) == ["extra.txt", "grep.py", "instruction.md"]


def test_worker_does_not_receive_hidden_verifier(tmp_path):
    task = load_task(TASK)
    prepare_workspace(task, tmp_path / "worker")
    assert sorted(p.name for p in (tmp_path / "worker").iterdir()) == ["grep.py", "instruction.md", "task.json"]


def test_symlink_entry_cannot_escape_snapshot(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    outside = tmp_path / "secret"
    outside.write_text("outside")
    try:
        (worker / "link").symlink_to(outside)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(ValueError, match="link"):
        capture(worker, tmp_path / "S1")
