from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pyscripts import output_to_clipboard as otc


def test_output_to_clipboard_wrap(monkeypatch):
    # simulate clipboard set success
    monkeypatch.setattr(otc, "set_clipboard", lambda text: None)
    # emulate script invocation through parser
    rc = otc.main(["-w", "echo", "hello"])
    assert rc == 0


def test_build_shell_wrapped_command_pwsh_executes_not_scriptblock_literal():
    wrapped, _ = otc.build_shell_wrapped_command("Write-Output ok", shell_choice="pwsh")
    assert wrapped == 'pwsh -NoProfile -NoLogo -Command "Write-Output ok"'
