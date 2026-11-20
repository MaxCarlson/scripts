from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="Requires Windows PowerShell 7")
def test_pwsh_command_resolution_and_ag_live_inventory():
    repo_root = Path(__file__).resolve().parents[3]
    w11_repo = repo_root.parent / "W11-powershell"
    misc_psm1 = w11_repo / "Config" / "Modules" / "MiscFunctions.psm1"
    clip_psm1 = w11_repo / "Config" / "Modules" / "ClipboardModule.psm1"
    if not misc_psm1.is_file() or not clip_psm1.is_file():
        pytest.skip("W11-powershell repository not present alongside scripts")

    venv_scripts = str(repo_root / ".venv" / "Scripts")
    env = os.environ.copy()
    env["PATH"] = venv_scripts + os.pathsep + env.get("PATH", "")

    ps_script = (
        f"Import-Module '{misc_psm1}'; "
        f"Import-Module '{clip_psm1}'; "
        "Set-Alias -Name testLiveAliasXYZ -Value Get-Location; "
        "$cmds = @('ag','c2c','scb','gcb','pclip','cld','rwc','sfc','apc','otc','cb2c','cb2cf') | ForEach-Object { "
        "  $c = Get-Command $_ -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "  [PSCustomObject]@{ Name = $_; CommandType = [string]$c.CommandType; Source = [string]$c.Source } "
        "}; "
        "$agOut = ag --json testLiveAliasXYZ | Out-String; "
        "[PSCustomObject]@{ Commands = $cmds; AgJson = $agOut } | ConvertTo-Json -Depth 5"
    )
    proc = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", ps_script],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    data = json.loads(proc.stdout)
    by_name = {c["Name"]: c for c in data["Commands"]}

    for exe_cmd in ("pclip", "cld", "rwc", "apc", "otc", "cb2c", "cb2cf"):
        assert by_name[exe_cmd]["CommandType"] == "Application", f"{exe_cmd} should resolve to Application"
        assert ".venv" in by_name[exe_cmd]["Source"]

    assert by_name["sfc"]["CommandType"] == "Application"
    assert "system32" in by_name["sfc"]["Source"].lower()
    assert by_name["c2c"]["CommandType"] == "Alias"
    assert by_name["ag"]["CommandType"] == "Alias"

    ag_data = json.loads(data["AgJson"])
    assert any(m["name"] == "testLiveAliasXYZ" for m in ag_data["matches"])
