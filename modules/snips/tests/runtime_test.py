import os
import subprocess
from pathlib import Path

import pytest

from snips.backend import find_autohotkey
from snips.config import default_config
from snips import runtime as runtime_module
from snips.runtime import ensure_runtime, generate_script, runtime_status


@pytest.mark.skipif(os.name != "nt", reason="AutoHotkey runtime validation requires Windows")
def test_generated_script_parses_and_registers_hotkeys_with_ahk_v2(tmp_path):
    executable, version = find_autohotkey()
    if executable is None:
        pytest.skip("AutoHotkey v2 is not installed")
    runtime = tmp_path / "snips-runtime"
    data = runtime / "data"
    script_text, build_id, _ = generate_script(default_config(), data, runtime / "status.txt")
    data.mkdir(parents=True)
    script = runtime / "test-dispatcher.ahk"
    script.write_text(script_text, encoding="utf-8", newline="")
    try:
        result = subprocess.run(
            [str(executable), "/ErrorStdOut=UTF-8", str(script), "/validate"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError as exc:
        if getattr(exc, "winerror", None) == 623:
            pytest.skip("Windows process sandbox denied GUI runtime launch (WinError 623)")
        raise
    assert result.returncode == 0, f"AutoHotkey v{version} rejected generated source: {result.stdout}\n{result.stderr}"
    status = (runtime / "status.txt").read_text(encoding="utf-8")
    assert status.startswith("running|")
    assert build_id in status


def test_runtime_status_parses_startup_error_detail(tmp_path):
    tmp_path.joinpath("status.txt").write_text("error|4321|build-id|hotkey registration failed", encoding="utf-8")
    status = runtime_status(tmp_path)
    assert status == {
        "running": False,
        "state": "error",
        "pid": 4321,
        "build_id": "build-id",
        "detail": "hotkey registration failed",
    }


def test_runtime_status_requires_matching_autohotkey_process_identity(tmp_path, monkeypatch):
    tmp_path.joinpath("status.txt").write_text("running|4321|build-id", encoding="utf-8")
    monkeypatch.setattr(
        runtime_module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, '"AutoHotkey64.exe","4321","Console","1","1 K"', ""
        ),
    )
    assert runtime_status(tmp_path)["running"] is True
    monkeypatch.setattr(
        runtime_module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, '"python.exe","4321","Console","1","1 K"', ""),
    )
    assert runtime_status(tmp_path)["running"] is False


def test_ensure_runtime_is_quiet_and_preserves_matching_pid(tmp_path, monkeypatch):
    calls = []

    class FakeMutex:
        def __init__(self, *_args, **_kwargs):
            pass

        def acquire(self):
            return True

        def release(self):
            calls.append("release")

    monkeypatch.setattr(runtime_module, "NamedMutex", FakeMutex)
    monkeypatch.setattr(
        runtime_module,
        "runtime_status",
        lambda _directory: {"running": True, "build_id": "build", "pid": 88},
    )
    monkeypatch.setattr(runtime_module, "start_runtime", lambda *_args, **_kwargs: pytest.fail("healthy PID restarted"))
    result = ensure_runtime(tmp_path / "ahk.exe", tmp_path / "snips.ahk", tmp_path, "build")
    assert result == (True, "AutoHotkey is already running (PID 88)")
    assert calls == ["release"]
    assert not (tmp_path / "lifecycle.log").exists()


def test_ensure_runtime_logs_recovery_and_failure_without_user_data(tmp_path, monkeypatch):
    class FakeMutex:
        def __init__(self, *_args, **_kwargs):
            pass

        def acquire(self):
            return True

        def release(self):
            pass

    monkeypatch.setattr(runtime_module, "NamedMutex", FakeMutex)
    monkeypatch.setattr(
        runtime_module,
        "runtime_status",
        lambda _directory: {"running": False, "build_id": None, "pid": None},
    )
    monkeypatch.setattr(runtime_module, "start_runtime", lambda *_args, **_kwargs: (False, "AutoHotkey launch failed"))
    assert not ensure_runtime(tmp_path / "ahk.exe", tmp_path / "snips.ahk", tmp_path, "build")[0]
    log = (tmp_path / "lifecycle.log").read_text(encoding="utf-8")
    assert "recovery failed: AutoHotkey launch failed" in log
    assert "clipboard" not in log.casefold()
    assert "snippet" not in log.casefold()


def test_generated_script_preserves_reload_and_startup_error_state():
    source, _build, _data = generate_script(default_config(), Path("C:/data"), Path("C:/status.txt"))
    assert "#SingleInstance Force" in source
    assert "OnExit((*) => WriteStatus(EXIT_STATE, EXIT_DETAIL))" in source
    assert 'EXIT_STATE := "error"' in source
