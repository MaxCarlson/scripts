import subprocess

from cross_platform.powershell import run_powershell, run_powershell_text


def test_run_powershell_uses_encoded_command(monkeypatch):
    calls = {}

    def fake_which(name):
        if name == "pwsh":
            return "pwsh"
        return None

    def fake_run(cmd, capture_output, text, timeout, encoding, errors):
        calls["cmd"] = cmd
        calls["timeout"] = timeout
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr("cross_platform.powershell.shutil.which", fake_which)
    monkeypatch.setattr("cross_platform.powershell.subprocess.run", fake_run)

    result = run_powershell("Write-Output 'ok'", timeout=7)

    assert result.stdout == "ok"
    assert result.returncode == 0
    assert calls["cmd"][0] == "pwsh"
    assert "-EncodedCommand" in calls["cmd"]
    assert calls["timeout"] == 7


def test_run_powershell_text_returns_stdout(monkeypatch):
    def fake_run_powershell(script, timeout=30, prefer_pwsh=True):
        class Result:
            stdout = "hello"

        return Result()

    monkeypatch.setattr("cross_platform.powershell.run_powershell", fake_run_powershell)

    assert run_powershell_text("Write-Output hello") == "hello"
