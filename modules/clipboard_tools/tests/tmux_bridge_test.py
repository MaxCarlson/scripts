from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from clipboard_tools import tmux_bridge


def _install_monkeypatch(monkeypatch, *, local_ok=True, remote_rc=0):
    calls = SimpleNamespace(local=[], remote=[])

    def fake_read():
        return "sample text"

    def fake_local(text: str, dry_run: bool) -> bool:
        calls.local.append((text, dry_run))
        return local_ok

    def fake_remote(text: str, target: str, verbose: bool, dry_run: bool) -> int:
        calls.remote.append((text, target, verbose, dry_run))
        return remote_rc

    monkeypatch.setattr(tmux_bridge, "_read_tmux_buffer", fake_read)
    monkeypatch.setattr(tmux_bridge, "_copy_to_local_clipboard", fake_local)
    monkeypatch.setattr(tmux_bridge, "_send_to_remote_windows_clipboard", fake_remote)
    return calls


def test_tmuxcp_local_only_skips_remote(monkeypatch):
    calls = _install_monkeypatch(monkeypatch, local_ok=True)

    rc = tmux_bridge.tmux_to_windows_clipboard(
        target="user@host",
        skip_remote=True,
    )

    assert rc == 0
    assert calls.local == [("sample text", False)]
    assert calls.remote == []


def test_tmuxcp_remote_used_when_local_fails(monkeypatch):
    calls = _install_monkeypatch(monkeypatch, local_ok=False, remote_rc=0)

    rc = tmux_bridge.tmux_to_windows_clipboard(
        target="user@host",
        skip_remote=False,
        verbose=True,
    )

    assert rc == 0
    assert calls.local == [("sample text", False)]
    assert calls.remote == [("sample text", "user@host", True, False)]


def test_cli_main_passes_dry_run_flag(monkeypatch):
    invoked = {}

    def fake_tmux_copy(target, *, verbose, dry_run, skip_remote):
        invoked["args"] = (target, verbose, dry_run, skip_remote)
        return 0

    monkeypatch.setattr(tmux_bridge, "tmux_to_windows_clipboard", fake_tmux_copy)
    monkeypatch.setattr(sys, "argv", ["tmuxcp", "-n", "-l"])

    with pytest.raises(SystemExit) as exc:
        tmux_bridge.cli_main()

    assert exc.value.code == 0
    assert invoked["args"] == (None, False, True, True)
