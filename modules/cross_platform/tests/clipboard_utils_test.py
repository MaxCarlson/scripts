# File: modules/cross_platform/tests/test_clipboard_utils.py
from __future__ import annotations

import io
import sys
import subprocess
import platform
from unittest.mock import patch

import pytest

from cross_platform.clipboard_utils import ClipboardUtils


# ------------ small helpers ------------

def _cp(stdout: str = "", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["X"], rc, stdout, "")

def _which_map(mapping: dict[str, str | None]):
    """Return a function to monkeypatch shutil.which using a fixed map."""
    def _which(name: str) -> str | None:
        return mapping.get(name.lower())
    return _which


class TtyStringIO(io.StringIO):
    """StringIO that reports itself as a TTY for OSC 52 tests."""
    def isatty(self):
        return True


# ------------ fixtures ------------

@pytest.fixture()
def clean_env(monkeypatch):
    # Make tests deterministic regardless of running inside Termux/tmux
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("ANDROID_ROOT", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)

@pytest.fixture()
def linux_utils(monkeypatch, clean_env):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    u = ClipboardUtils()
    # Force off Termux/tmux for tests that don't want them
    monkeypatch.setattr(ClipboardUtils, "is_termux", lambda self: False)
    monkeypatch.setattr(ClipboardUtils, "is_tmux", lambda self: False)
    return u

@pytest.fixture()
def darwin_utils(monkeypatch, clean_env):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    u = ClipboardUtils()
    monkeypatch.setattr(ClipboardUtils, "is_termux", lambda self: False)
    monkeypatch.setattr(ClipboardUtils, "is_tmux", lambda self: False)
    return u

@pytest.fixture()
def windows_utils(monkeypatch, clean_env):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    u = ClipboardUtils()
    monkeypatch.setattr(ClipboardUtils, "is_termux", lambda self: False)
    monkeypatch.setattr(ClipboardUtils, "is_tmux", lambda self: False)
    return u


# ------------ set_clipboard: OSC52 ------------

def test_set_clipboard_emits_osc52_outside_tmux(linux_utils, monkeypatch):
    buf = TtyStringIO()
    monkeypatch.setattr(sys, "stdout", buf)

    with patch("cross_platform.clipboard_utils.shutil.which", _which_map({})), \
         patch("cross_platform.clipboard_utils.subprocess.run") as sub_run:
        linux_utils.set_clipboard("hello osc52")

    out = buf.getvalue()
    # basic OSC52 shape present; nothing else required
    assert "]52;c;" in out and "\a" in out
    sub_run.assert_not_called()

def test_set_clipboard_emits_osc52_inside_tmux(linux_utils, monkeypatch):
    # enable tmux path for just this test
    monkeypatch.setattr(ClipboardUtils, "is_tmux", lambda self: True)
    buf = TtyStringIO()
    monkeypatch.setattr(sys, "stdout", buf)

    with patch("cross_platform.clipboard_utils.shutil.which", _which_map({})), \
         patch("cross_platform.clipboard_utils.subprocess.run") as sub_run:
        linux_utils.set_clipboard("tmux path")

    out = buf.getvalue()
    assert "\x1bPtmux;" in out and "\x1b\\" in out  # passthrough wrapper
    # tmux side buffer should have been fed via stdin
    sub_run.assert_any_call(
        ["tmux", "set-buffer", "-w", "--"],
        input="tmux path",
        text=True,
        capture_output=True,
        check=True,
    )


# ------------ set_clipboard: Linux/macOS/Termux ------------

def test_set_clipboard_linux_chooses_xclip(linux_utils, monkeypatch):
    buf = TtyStringIO(); monkeypatch.setattr(sys, "stdout", buf)
    which = _which_map({"xclip": "/usr/bin/xclip"})

    with patch("cross_platform.clipboard_utils.shutil.which", which), \
         patch("cross_platform.clipboard_utils.subprocess.run") as sub_run:
        linux_utils.set_clipboard("hey linux")

    # native call hit xclip (first element is the resolved path)
    args = sub_run.call_args[0][0]
    assert "xclip" in args[0]
    assert args[1:3] == ["-selection", "clipboard"]
    assert "]52;c;" in buf.getvalue()  # OSC52 also emitted

def test_set_clipboard_macos_uses_pbcopy(darwin_utils, monkeypatch):
    buf = TtyStringIO(); monkeypatch.setattr(sys, "stdout", buf)

    with patch("cross_platform.clipboard_utils.subprocess.run") as sub_run:
        darwin_utils.set_clipboard("hey mac")

    args = sub_run.call_args[0][0]
    assert args[0] == "pbcopy"
    assert "]52;c;" in buf.getvalue()

def test_set_clipboard_termux_path(monkeypatch, clean_env):
    # Make a Linux instance but force Termux true
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    u = ClipboardUtils()
    monkeypatch.setattr(ClipboardUtils, "is_tmux", lambda self: False)
    monkeypatch.setattr(ClipboardUtils, "is_termux", lambda self: True)

    with patch("cross_platform.clipboard_utils.subprocess.run") as sub_run:
        u.set_clipboard("android!")

    args = sub_run.call_args[0][0]
    assert args[0] == "termux-clipboard-set"


# ------------ set_clipboard: Windows robust + fallback ------------

def test_set_clipboard_windows_robust_success(windows_utils, monkeypatch):
    buf = TtyStringIO(); monkeypatch.setattr(sys, "stdout", buf)
    monkeypatch.setattr(ClipboardUtils, "_pwsh_exe", lambda self: "pwsh")

    with patch.object(ClipboardUtils, "_run", return_value=_cp()) as run_mock:
        windows_utils.set_clipboard("win text")

    run_args = run_mock.call_args[0][0]
    assert run_args[:3] == ["pwsh", "-NoProfile", "-EncodedCommand"]
    assert "]52;c;" in buf.getvalue()

def test_set_clipboard_windows_robust_failure_falls_back_to_clip(windows_utils, monkeypatch):
    buf = TtyStringIO(); monkeypatch.setattr(sys, "stdout", buf)
    monkeypatch.setattr(ClipboardUtils, "_pwsh_exe", lambda self: "pwsh")

    with patch.object(ClipboardUtils, "_run", side_effect=subprocess.CalledProcessError(1, "pwsh")), \
         patch("cross_platform.clipboard_utils.shutil.which",
               _which_map({"clip": "C:\\Windows\\System32\\clip.exe", "clip.exe": "C:\\Windows\\System32\\clip.exe"})), \
         patch("cross_platform.clipboard_utils.subprocess.run") as sub_run:
        sub_run.return_value = _cp(rc=0)
        windows_utils.set_clipboard("fallback!")

    args = sub_run.call_args[0][0]
    # Accept either "clip" or full path ending in clip.exe
    assert "clip" in args[0].lower()
    # Sent as UTF-16LE bytes
    assert sub_run.call_args.kwargs["input"] == "fallback!".encode("utf-16le")
    assert "]52;c;" in buf.getvalue()


# ------------ get_clipboard ------------

def test_get_clipboard_termux(monkeypatch, clean_env):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    u = ClipboardUtils()
    monkeypatch.setattr(ClipboardUtils, "is_termux", lambda self: True)
    with patch.object(ClipboardUtils, "_run", return_value=_cp("T-GET")) as run_mock:
        out = u.get_clipboard()
    assert out == "T-GET"
    assert run_mock.call_args[0][0] == ["termux-clipboard-get"]

def test_get_clipboard_linux_prefers_xclip(linux_utils, monkeypatch):
    monkeypatch.setattr("cross_platform.clipboard_utils.shutil.which",
                        _which_map({"xclip": "/usr/bin/xclip"}))
    with patch.object(ClipboardUtils, "_run", return_value=_cp("L-GET")) as run_mock:
        out = linux_utils.get_clipboard()
    assert out == "L-GET"
    args = run_mock.call_args[0][0]
    assert "xclip" in args[0]
    assert args[1:3] == ["-selection", "clipboard"]

def test_get_clipboard_macos(darwin_utils):
    with patch.object(ClipboardUtils, "_run", return_value=_cp("PB")) as run_mock:
        out = darwin_utils.get_clipboard()
    assert out == "PB"
    assert run_mock.call_args[0][0] == ["pbpaste"]

def test_get_clipboard_windows_encodedcommand(windows_utils, monkeypatch):
    monkeypatch.setattr(ClipboardUtils, "_pwsh_exe", lambda self: "pwsh")
    with patch.object(ClipboardUtils, "_run", return_value=_cp("WIN")) as run_mock:
        out = windows_utils.get_clipboard()
    assert out == "WIN"
    args = run_mock.call_args[0][0]
    assert args[:3] == ["pwsh", "-NoProfile", "-EncodedCommand"]


# ------------ unknown OS fallback ------------

def test_unknown_os_relies_on_osc52_only(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "BeOS")
    u = ClipboardUtils()
    # Force off Termux/tmux so no subprocess paths fire
    monkeypatch.setattr(ClipboardUtils, "is_termux", lambda self: False)
    monkeypatch.setattr(ClipboardUtils, "is_tmux", lambda self: False)

    buf = TtyStringIO(); monkeypatch.setattr(sys, "stdout", buf)
    with patch("cross_platform.clipboard_utils.subprocess.run") as sub_run:
        u.set_clipboard("beos")

    sub_run.assert_not_called()
    assert "]52;c;" in buf.getvalue()
