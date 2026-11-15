"""Unit, Job-Object, stress, redaction, and real-workflow tests for Phase 4 supervisor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time

import psutil  # type: ignore[import-untyped]
import pytest

from procwatch.cli import main
from procwatch.models import ExecutionProfile, RunStatus
from procwatch.runner.supervisor import execute
from procwatch.storage import SCHEMA_VERSION, FlightRecorderStorage


def test_exec_success_nonzero_unicode_env_and_context(tmp_path: Path) -> None:
    db_path = tmp_path / "exec.db"
    storage = FlightRecorderStorage(db_path=db_path)
    try:
        res = execute(
            [
                sys.executable,
                "-c",
                "import os, sys; print('hello café', os.environ.get('PW_CUSTOM'), 'CTX=' + os.environ.get('PROCWATCH_CONTEXT', ''))",
            ],
            cwd=tmp_path,
            env_overrides={"PW_CUSTOM": "val123"},
            context={"agent_kind": "codex", "agent_session": "sess-42", "phase": "phase4_test"},
            storage=storage,
        )
        assert res.status == RunStatus.SUCCESS
        assert res.exit_code == 0
        assert "hello café" in res.stdout_redacted
        assert "val123" in res.stdout_redacted
        assert "sess-42" in res.stdout_redacted
        assert res.db_persisted is True
        if sys.platform == "win32":
            assert res.job_assigned is True

        rows = storage.query_supervised_runs(execution_id=res.execution_id)
        assert len(rows) == 1
        assert rows[0]["status"] == "success"
        assert rows[0]["incomplete"] == 0

        fail_res = execute([sys.executable, "-c", "import sys; sys.stderr.write('oops\\n'); sys.exit(7)"], storage=storage)
        assert fail_res.status == RunStatus.NONZERO_EXIT
        assert fail_res.exit_code == 7
        assert "oops" in fail_res.stderr_redacted
    finally:
        storage.close()


def test_exec_missing_exe_and_invalid_cwd(tmp_path: Path) -> None:
    r1 = execute(["nonexistent_binary_xyz_999.exe"])
    assert r1.status == RunStatus.LAUNCH_FAILED
    assert r1.error_detail

    r2 = execute([sys.executable, "--version"], cwd=tmp_path / "missing_dir")
    assert r2.status == RunStatus.LAUNCH_FAILED
    assert "does not exist" in (r2.error_detail or "")


def test_exec_timeout_terminates_descendant_tree(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows Job Object tree test")

    pid_file = tmp_path / "child_pid.txt"
    # Spawn a parent python process that spawns a long-sleeping child python process.
    parent_code = (
        "import pathlib, subprocess, sys, time; "
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"pathlib.Path(r'{pid_file}').write_text(str(p.pid), encoding='utf-8'); "
        "time.sleep(30)"
    )
    res = execute([sys.executable, "-c", parent_code], timeout_seconds=1.2)
    assert res.status == RunStatus.TIMEOUT
    assert res.job_assigned is True
    assert "job_terminated" in res.job_cleanup_outcome

    # Verify independently that both parent and child descendant are gone.
    if pid_file.exists():
        child_pid = int(pid_file.read_text(encoding="utf-8").strip())
        deadline = time.monotonic() + 2.0
        while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not psutil.pid_exists(child_pid)


def test_exec_cancellation_cleanup(tmp_path: Path) -> None:
    cancel = threading.Event()
    timer = threading.Timer(0.4, cancel.set)
    timer.start()
    try:
        res = execute([sys.executable, "-c", "import time; time.sleep(20)"], cancel_event=cancel)
    finally:
        timer.cancel()
    assert res.status == RunStatus.CANCELLED


def test_exec_dual_stream_stress_and_bounded_truncation() -> None:
    # Emit ~200 KB on stdout and ~200 KB on stderr concurrently with 16 KB per-stream cap.
    code = "\n".join(
        [
            "import sys",
            "chunk = 'X' * 4096 + '\\n'",
            "for _ in range(50):",
            "    sys.stdout.write(chunk)",
            "    sys.stderr.write(chunk)",
            "sys.stdout.flush()",
            "sys.stderr.flush()",
        ]
    )
    res = execute([sys.executable, "-c", code], max_output_bytes=16_384, timeout_seconds=15.0)
    assert res.status == RunStatus.SUCCESS
    assert res.exit_code == 0
    assert res.stdout_bytes > 100_000
    assert res.stderr_bytes > 100_000
    assert res.stdout_truncated is True
    assert res.stderr_truncated is True
    assert res.dropped_bytes > 0
    assert "[truncated " in res.stdout_redacted
    assert len(res.stdout_redacted) < 20_000


def test_exec_redacts_secrets_in_db_and_cli_real_repo_workflows(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "runs.db"
    secret = "ghp_Phase4SuperSecretToken1234567890"
    storage = FlightRecorderStorage(db_path=db_path)
    try:
        assert storage.db_stats()["schema_version"] == SCHEMA_VERSION
        res = execute(
            [sys.executable, "-c", f"print('token={secret}')", "--token", secret],
            storage=storage,
        )
        assert res.status == RunStatus.SUCCESS
        assert secret not in res.stdout_redacted
        assert all(secret not in a for a in res.argv_redacted)
    finally:
        storage.close()

    assert secret.encode("utf-8") not in db_path.read_bytes()

    # Real non-destructive repository workflow: `procwatch exec` running `procwatch doctor -j` and `scripts_help --help`.
    rc = main(["exec", "-j", "-D", str(db_path), "--", sys.executable, "-m", "procwatch", "doctor", "-j", "-d", str(db_path)])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["status"] == "success"
    assert parsed["profile"] == ExecutionProfile.HEADLESS.value
    doctor_out = json.loads(parsed["stdout_redacted"])
    assert doctor_out["storage"]["supervised_runs"] >= 1

    # Also test `scripts_help.cli --help` and `git status` as real non-destructive repo workflows.
    repo_root = Path(__file__).resolve().parents[3]
    scripts_help_src = repo_root / "modules" / "scripts_help"
    if scripts_help_src.exists():
        env_patch = {"PYTHONPATH": str(scripts_help_src) + os.pathsep + os.environ.get("PYTHONPATH", "")}
        sh_res = execute([sys.executable, "-m", "scripts_help.cli", "--help"], env_overrides=env_patch, timeout_seconds=10.0)
        assert sh_res.status == RunStatus.SUCCESS, f"stderr={sh_res.stderr_redacted}"
        assert sh_res.exit_code == 0

    git_res = execute(["git", "-C", str(repo_root), "-c", "submodule.recurse=false", "status", "--short"], timeout_seconds=10.0)
    assert git_res.status == RunStatus.SUCCESS
    assert git_res.exit_code == 0


def test_exec_immediate_exit_and_orphan_descendant_cleanup_on_job_close(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows Job Object test")

    # 1. Immediate exit: child finishes as fast as possible; CREATE_SUSPENDED ensures Job assignment never races.
    fast_ok = execute([sys.executable, "-c", "import sys; sys.exit(0)"])
    assert fast_ok.status == RunStatus.SUCCESS
    assert fast_ok.exit_code == 0
    assert fast_ok.job_assigned is True

    fast_nz = execute([sys.executable, "-c", "import sys; sys.exit(42)"])
    assert fast_nz.status == RunStatus.NONZERO_EXIT
    assert fast_nz.exit_code == 42
    assert fast_nz.job_assigned is True

    # 2. Rapid descendant creation followed by immediate parent exit:
    #    KILL_ON_JOB_CLOSE must terminate the orphaned descendant when execute() closes the job handle.
    pid_file = tmp_path / "orphan_child.pid"
    parent_code = (
        "import pathlib, subprocess, sys; "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"pathlib.Path(r'{pid_file}').write_text(str(p.pid), encoding='utf-8'); "
        "sys.exit(0)"
    )
    res = execute([sys.executable, "-c", parent_code], timeout_seconds=10.0)
    assert res.status == RunStatus.SUCCESS
    assert res.job_assigned is True
    child_pid = int(pid_file.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 2.0
    while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not psutil.pid_exists(child_pid)


def test_exec_job_assignment_failure_aborts_before_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows Job Object test")

    marker = tmp_path / "should_not_exist.txt"
    from procwatch.runner import supervisor

    monkeypatch.setattr(
        supervisor._Win32JobHandle,
        "assign_handle",
        lambda self, _h: (False, "mock_assign_failed"),
    )
    res = execute(
        [
            sys.executable,
            "-c",
            f"import pathlib; pathlib.Path(r'{marker}').write_text('ran', encoding='utf-8')",
        ]
    )
    assert res.status == RunStatus.LAUNCH_FAILED
    assert res.job_assigned is False
    assert res.job_cleanup_outcome == "terminated_before_resume"
    assert "mock_assign_failed" in (res.error_detail or "")
    assert not marker.exists()


def test_exec_cancellation_preserves_unrelated_process(tmp_path: Path) -> None:
    import subprocess as sp

    unrelated = sp.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        pid_file = tmp_path / "owned_descendant.pid"
        cancel = threading.Event()
        timer = threading.Timer(0.5, cancel.set)
        parent_code = (
            "import pathlib, subprocess, sys, time; "
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            f"pathlib.Path(r'{pid_file}').write_text(str(p.pid), encoding='utf-8'); "
            "time.sleep(30)"
        )
        timer.start()
        try:
            res = execute([sys.executable, "-c", parent_code], cancel_event=cancel)
        finally:
            timer.cancel()
        assert res.status == RunStatus.CANCELLED
        assert psutil.pid_exists(unrelated.pid)
        if pid_file.exists():
            owned_child = int(pid_file.read_text(encoding="utf-8").strip())
            deadline = time.monotonic() + 2.0
            while psutil.pid_exists(owned_child) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not psutil.pid_exists(owned_child)
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=3.0)
