import base64
import json
import subprocess

import pytest
from terminal_launcher import WindowsTerminalBackend, powershell_plan


class CaptureRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_powershell_plan_reuses_named_window_for_each_launch(monkeypatch):
    monkeypatch.setattr("terminal_launcher.backends.windows_terminal.sys.platform", "win32")
    runner = CaptureRunner()
    backend = WindowsTerminalBackend(executable="wt.exe", runner=runner)

    first = backend.launch(powershell_plan(target_window="scripts-work", cwd=r"C:\src\scripts"))
    second = backend.launch(powershell_plan(target_window="scripts-work", cwd=r"C:\src\scripts"))

    assert first.status.value == second.status.value == "submitted"
    assert len(runner.calls) == 2
    for command, _kwargs in runner.calls:
        assert command[:3] == ["wt.exe", "--window", "scripts-work"]
        assert command[3] == "new-tab"
        encoded = command[-1]
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        assert payload == [["pwsh.exe", "-NoLogo", "-NoExit"], r"C:\src\scripts"]


def test_powershell_plan_requires_an_explicit_window_target():
    with pytest.raises(ValueError, match="target_window"):
        powershell_plan(target_window="")
