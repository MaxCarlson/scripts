def test_headless_task_logs_output_and_preserves_exit_code(tmp_path, monkeypatch):
    from notifications import cli, headless_task

    def fake_main(argv):
        print("dispatch checked")
        return 3

    monkeypatch.setattr(cli, "main", fake_main)
    result = headless_task.run(["outbox", "run"], log_directory=tmp_path)
    assert result == 3
    assert "dispatch checked" in (tmp_path / "outbox.log").read_text(encoding="utf-8")


def test_headless_task_logs_uncaught_exception_and_returns_failure(
    tmp_path, monkeypatch
):
    from notifications import cli, headless_task

    def fake_main(argv):
        raise RuntimeError("scheduled job failed")

    monkeypatch.setattr(cli, "main", fake_main)
    assert headless_task.run(["coordinator", "poll"], log_directory=tmp_path) == 1
    assert "scheduled job failed" in (tmp_path / "coordinator.log").read_text(
        encoding="utf-8"
    )


def test_scheduled_runner_prefers_windowless_python_when_available(tmp_path):
    from notifications.headless_task import scheduled_runner

    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.touch()
    pythonw.touch()
    assert scheduled_runner(python, windows=True) == (
        pythonw,
        "notifications.headless_task",
    )


def test_scheduled_runner_preserves_non_windows_and_missing_pythonw(tmp_path):
    from notifications.headless_task import scheduled_runner

    python = tmp_path / "python.exe"
    assert scheduled_runner(python, windows=False) == (python, "notifications.cli")
    assert scheduled_runner(python, windows=True) == (python, "notifications.cli")


def test_headless_task_handles_missing_standard_streams(tmp_path, monkeypatch):
    import sys

    from notifications import cli, headless_task

    def fake_main(argv):
        print("headless output")
        return 0

    monkeypatch.setattr(cli, "main", fake_main)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert headless_task.run(["outbox", "run"], log_directory=tmp_path) == 0
    assert "headless output" in (tmp_path / "outbox.log").read_text(encoding="utf-8")


def test_task_installers_choose_headless_defaults_and_honor_override(
    tmp_path, monkeypatch
):
    import sys

    from notifications.integrations.resource_coordinator import install_coordinator_task
    from notifications.outbox import install_outbox_task

    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.touch()
    pythonw.touch()
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "platform", "win32")
    for install in (install_outbox_task, install_coordinator_task):
        default = install(apply=False)
        assert default["executable"] == str(pythonw)
        assert "notifications.headless_task" in default["arguments"]
        explicit = install(apply=False, executable=str(python))
        assert explicit["executable"] == str(python)
        assert "notifications.cli" in explicit["arguments"]


def test_windows_permission_helpers_do_not_open_consoles(tmp_path, monkeypatch):
    import subprocess

    from notifications import config

    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args, 0, stdout='"test","S-1-5-21-12345"', stderr=""
        )

    monkeypatch.setattr(config.subprocess, "run", fake_run)
    assert config._windows_user_sid() == "S-1-5-21-12345"
    monkeypatch.setattr(config.os, "name", "nt")
    config._secure_path(tmp_path)
    assert len(calls) == 4  # SID lookup, then another SID lookup and two ACL calls.
    assert all(
        kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
        for _, kwargs in calls
    )
