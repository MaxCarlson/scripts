from pathlib import Path

import types

from vdedup import report_viewer


class _StubSystem:
    def __init__(self, *, win=False, mac=False, termux=False, wsl=False):
        self._win = win
        self._mac = mac
        self._termux = termux
        self._wsl = wsl

    def is_windows(self) -> bool:
        return self._win

    def is_darwin(self) -> bool:
        return self._mac

    def is_termux(self) -> bool:
        return self._termux

    def is_wsl2(self) -> bool:
        return self._wsl


def test_open_media_windows_uses_shell(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_text("x")
    invoked = {}

    def fake_startfile(path):
        invoked["path"] = path

    monkeypatch.setattr(report_viewer.os, "startfile", fake_startfile, raising=False)
    monkeypatch.setattr(report_viewer, "SystemUtils", lambda: _StubSystem(win=True))
    assert report_viewer._open_media(clip)
    assert invoked["path"] == str(Path(clip).resolve())


def test_open_media_linux_prefers_xdg(monkeypatch, tmp_path):
    clip = tmp_path / "clip2.mp4"
    clip.write_text("x")
    invoked = []

    def fake_popen(cmd, **kwargs):
        invoked.append(cmd)
        return types.SimpleNamespace()

    monkeypatch.setattr(report_viewer, "SystemUtils", lambda: _StubSystem())
    monkeypatch.setattr(report_viewer.subprocess, "Popen", fake_popen)
    assert report_viewer._open_media(clip)
    assert invoked[0][0] == "xdg-open"


def test_open_media_termux_falls_back(monkeypatch, tmp_path):
    clip = tmp_path / "clip3.mp4"
    clip.write_text("x")
    attempts = []

    def fake_popen(cmd, **kwargs):
        attempts.append(cmd[0])
        if cmd[0] == "termux-open":
            raise FileNotFoundError("missing")
        return types.SimpleNamespace()

    monkeypatch.setattr(report_viewer, "SystemUtils", lambda: _StubSystem(termux=True))
    monkeypatch.setattr(report_viewer.subprocess, "Popen", fake_popen)
    assert report_viewer._open_media(clip)
    assert attempts == ["termux-open", "xdg-open"]
