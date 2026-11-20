"""Normal-agent integration and security-boundary tests for PrivExec."""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from privexec import cli
from privexec.protocol import ProtocolValidationError, parse_params_json

MODULE_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = MODULE_ROOT / "scripts"
BROKER_DLL = MODULE_ROOT / "broker" / "bin" / "PrivExecBroker.dll"
DESCRIPTORS_DIR = MODULE_ROOT / "descriptors"
DOTNET_EXE = Path(r"C:\Program Files\dotnet\dotnet.exe")


def test_parse_params_json_valid_and_rejects_forbidden_keys() -> None:
    parsed = parse_params_json('{"message": "hello", "count": 2}')
    assert parsed == {"message": "hello", "count": 2}

    with pytest.raises(ProtocolValidationError, match="object"):
        parse_params_json("[1, 2, 3]")

    with pytest.raises(ProtocolValidationError, match="Forbidden property"):
        parse_params_json('{"authorized": true}')


def test_cli_run_rejects_combining_params_file_and_params_json(tmp_path: Path) -> None:
    pfile = tmp_path / "p.json"
    pfile.write_text('{"message": "hi"}', encoding="utf-8")
    rc = cli.main(
        [
            "run",
            "synthetic.echo",
            "-t",
            "synth-target-1",
            "-T",
            "synthetic",
            "-p",
            str(pfile),
            "-J",
            '{"message": "hi"}',
        ]
    )
    assert rc == 1


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows PowerShell 7")
def test_start_privexec_session_dry_run_and_acl_audit(tmp_path: Path) -> None:
    start_ps1 = SCRIPTS_DIR / "Start-PrivExecSession.ps1"
    res = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(start_ps1),
            "-InstallRoot",
            str(tmp_path),
            "-PipeName",
            "privexec-test-dry",
            "-AllowSameUser",
            "-AllowedCapabilities",
            "synthetic.echo",
            "-AllowedTargets",
            "synth-target-1",
            "-TtlSeconds",
            "600",
            "-DryRun",
            "-Json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    plan = json.loads(res.stdout)
    assert plan["action"] == "privexec_session_start"
    assert plan["dry_run"] is True
    assert plan["pipe_name"] == "privexec-test-dry"
    assert plan["allowed_capabilities"] == ["synthetic.echo"]
    assert plan["allowed_targets"] == ["synth-target-1"]
    assert len(plan["allowed_client_sids"]) == 1

    # Verify Test-ProtectedInstallAcls detects non-admin write ACEs on root, client, and staged dirs
    dirty_dir = tmp_path / "acl_test"
    (dirty_dir / "client").mkdir(parents=True)
    subprocess.run(["icacls", str(dirty_dir / "client"), "/grant", "BUILTIN\\Users:(OI)(CI)(M)"], check=True, capture_output=True)
    acl_check_cmd = f"""
    $ErrorActionPreference = 'Stop'
    . '{start_ps1}' -DryRun | Out-Null
    $v = @(Test-ProtectedInstallAcls -RootPath '{dirty_dir}')
    if ($v.Count -eq 0) {{ throw 'Expected ACL violation for BUILTIN\\Users:(M)' }}
    Write-Output ($v -join '|')
    """
    acl_res = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", acl_check_cmd],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "S-1-5-32-545" in acl_res.stdout


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows PowerShell 7")
def test_protected_install_acl_validator_regression(tmp_path: Path) -> None:
    start_ps1 = SCRIPTS_DIR / "Start-PrivExecSession.ps1"

    ps_script = f"""
    $ErrorActionPreference = 'Stop'
    . '{start_ps1}' -DryRun | Out-Null

    function Set-TestAcl([string]$Path, [string]$Account, [System.Security.AccessControl.FileSystemRights]$Rights, [bool]$Protect) {{
        $acl = [System.Security.AccessControl.DirectorySecurity]::new()
        $acl.SetAccessRuleProtection($Protect, $false)
        $inh = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
        $prp = [System.Security.AccessControl.PropagationFlags]'None'
        $alw = [System.Security.AccessControl.AccessControlType]::Allow
        foreach ($adminAcct in @('NT AUTHORITY\\SYSTEM', 'BUILTIN\\Administrators')) {{
            $sid = ([System.Security.Principal.NTAccount]$adminAcct).Translate([System.Security.Principal.SecurityIdentifier])
            $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
                $sid, [System.Security.AccessControl.FileSystemRights]::FullControl, $inh, $prp, $alw))
        }}
        if ($Account) {{
            $sid = ([System.Security.Principal.NTAccount]$Account).Translate([System.Security.Principal.SecurityIdentifier])
            $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new($sid, $Rights, $inh, $prp, $alw))
        }}
        [System.IO.FileSystemAclExtensions]::SetAccessControl([System.IO.DirectoryInfo]::new($Path), $acl)
    }}

    try {{
        # 1. ReadAndExecute + Synchronize + SYSTEM/Administrators FullControl -> ALLOWED (0 violations, no stray booleans)
        $rxRoot = Join-Path '{tmp_path}' 'case_rx'
        New-Item -ItemType Directory -Path (Join-Path $rxRoot 'bin') -Force | Out-Null
        $rxRights = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [System.Security.AccessControl.FileSystemRights]::Synchronize
        Set-TestAcl $rxRoot 'BUILTIN\\Users' $rxRights $true
        Set-TestAcl (Join-Path $rxRoot 'bin') 'BUILTIN\\Users' $rxRights $true
        $vRx = @(Test-ProtectedInstallAcls -RootPath $rxRoot)
        if ($vRx.Count -ne 0) {{ throw "Expected 0 violations for ReadAndExecute+Synchronize, got: $($vRx -join '; ')" }}

        # 2. Write, Modify, FullControl, Delete, ChangePermissions, TakeOwnership -> REJECTED
        foreach ($badRightName in @('Write', 'Modify', 'FullControl', 'Delete', 'ChangePermissions', 'TakeOwnership')) {{
            $badRoot = Join-Path '{tmp_path}' ("case_" + $badRightName)
            New-Item -ItemType Directory -Path (Join-Path $badRoot 'bin') -Force | Out-Null
            Set-TestAcl $badRoot 'BUILTIN\\Users' ([System.Security.AccessControl.FileSystemRights]::ReadAndExecute) $true
            $badRights = [System.Security.AccessControl.FileSystemRights]::$badRightName
            Set-TestAcl (Join-Path $badRoot 'bin') 'BUILTIN\\Users' $badRights $true
            $vBad = @(Test-ProtectedInstallAcls -RootPath $badRoot)
            if ($vBad.Count -ne 1) {{ throw "Expected 1 violation for $badRightName, got $($vBad.Count): $($vBad -join '; ')" }}
        }}

        # 3. Writable inherited ACE -> REJECTED
        $inhRoot = Join-Path '{tmp_path}' 'case_inherited'
        New-Item -ItemType Directory -Path (Join-Path $inhRoot 'adapters') -Force | Out-Null
        Set-TestAcl $inhRoot 'BUILTIN\\Users' ([System.Security.AccessControl.FileSystemRights]::Write -bor [System.Security.AccessControl.FileSystemRights]::ReadAndExecute) $true
        $vInh = @(Test-ProtectedInstallAcls -RootPath $inhRoot)
        if ($vInh.Count -lt 2) {{ throw "Expected violations on both root and inherited adapters dir, got $($vInh.Count)" }}

        Write-Output 'ACL_REGRESSION_PASS'
    }} finally {{
        $me = "$($env:USERDOMAIN)\\$($env:USERNAME)"
        Get-ChildItem -LiteralPath '{tmp_path}' -Recurse -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {{
            & icacls $_.FullName /grant "$me`:(OI)(CI)(F)" /Q 2>$null | Out-Null
        }}
    }}
    """
    res = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "ACL_REGRESSION_PASS" in res.stdout


@pytest.mark.skipif(os.name != "nt" or not BROKER_DLL.is_file(), reason="Requires Windows and built PrivExecBroker.dll")
def test_install_stages_agent_wrappers_and_normal_agent_workflow(tmp_path: Path) -> None:
    if not DOTNET_EXE.is_file():
        pytest.skip("dotnet.exe not found")

    install_root = tmp_path / "staged"
    subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(SCRIPTS_DIR / "Install-PrivExec.ps1"),
            "-Apply",
            "-Mode",
            "SameUserDev",
            "-InstallRoot",
            str(install_root),
            "-Json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    staged_cmd = install_root / "client" / "privexec.cmd"
    staged_ps1 = install_root / "client" / "privexec.ps1"
    assert staged_cmd.is_file()
    assert staged_ps1.is_file()

    pipe_name = f"privexec-agent-{uuid.uuid4().hex[:8]}"
    state_dir = tmp_path / "state"
    grant_file = tmp_path / "grant.json"
    grant_file.write_text(
        json.dumps(
            {
                "allowed_capabilities": ["synthetic.echo"],
                "allowed_targets": ["synth-target-1"],
                "allow_mutation": False,
                "ttl_seconds": 120,
            }
        ),
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [
            str(DOTNET_EXE),
            str(BROKER_DLL),
            "--pipe",
            pipe_name,
            "--descriptors-dir",
            str(DESCRIPTORS_DIR),
            "--state-dir",
            str(state_dir),
            "--grant-file",
            str(grant_file),
            "--allow-same-user",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready = False
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            assert proc.stdout is not None
            line = proc.stdout.readline()
            if "PRIVEXEC_BROKER_READY" in line:
                ready = True
                break
            if proc.poll() is not None:
                break
        assert ready, f"Broker failed to start: stderr={proc.stderr.read() if proc.stderr else ''}"

        # Run from an unrelated directory with PYTHONPATH cleared to prove standalone entrypoint works
        clean_env = os.environ.copy()
        clean_env.pop("PYTHONPATH", None)
        agent_cwd = tmp_path / "agent_workspace"
        agent_cwd.mkdir()

        # 1. Status check via staged privexec.ps1
        st = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(staged_ps1), "status", "-P", pipe_name, "-f", "json"],
            cwd=str(agent_cwd),
            env=clean_env,
            check=True,
            capture_output=True,
            text=True,
        )
        st_json = json.loads(st.stdout)
        assert st_json["ok"] is True
        assert st_json["status"] == "active"
        assert st_json["capabilities"] == ["synthetic.echo"]

        # 2. Authorized read-only run via staged privexec.cmd with inline --params-json
        run_ok = subprocess.run(
            [
                "cmd",
                "/c",
                str(staged_cmd),
                "run",
                "synthetic.echo",
                "-t",
                "synth-target-1",
                "-T",
                "synthetic",
                "-J",
                '{"message":"normal-agent-ok"}',
                "-P",
                pipe_name,
            ],
            cwd=str(agent_cwd),
            env=clean_env,
            check=True,
            capture_output=True,
            text=True,
        )
        run_json = json.loads(run_ok.stdout)
        assert run_json["ok"] is True
        assert run_json["authorized"] is True
        assert run_json["state"] == "succeeded"
        assert run_json["exit_code"] == 0
        assert run_json["result"]["echo"] == "normal-agent-ok"

        # 3. Retrieve persisted result by operation_id
        res_lookup = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(staged_ps1),
                "result",
                run_json["operation_id"],
                "-P",
                pipe_name,
            ],
            cwd=str(agent_cwd),
            env=clean_env,
            check=True,
            capture_output=True,
            text=True,
        )
        res_json = json.loads(res_lookup.stdout)
        assert res_json["operation_id"] == run_json["operation_id"]
        assert res_json["result"]["echo"] == "normal-agent-ok"

        # 4. Denied unauthorized capability
        denied_cap = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(staged_ps1),
                "run",
                "synthetic.mutate",
                "-t",
                "synth-target-1",
                "-T",
                "synthetic",
                "-A",
                "-P",
                pipe_name,
            ],
            cwd=str(agent_cwd),
            env=clean_env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert denied_cap.returncode == 1
        denied_cap_json = json.loads(denied_cap.stdout)
        assert denied_cap_json["authorized"] is False
        assert denied_cap_json["state"] == "denied"
        assert denied_cap_json["diagnostic_category"] == "unauthorized_capability"

        # 5. Denied unauthorized target
        denied_tgt = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(staged_ps1),
                "run",
                "synthetic.echo",
                "-t",
                "synth-target-2",
                "-T",
                "synthetic",
                "-P",
                pipe_name,
            ],
            cwd=str(agent_cwd),
            env=clean_env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert denied_tgt.returncode == 1
        denied_tgt_json = json.loads(denied_tgt.stdout)
        assert denied_tgt_json["authorized"] is False
        assert denied_tgt_json["state"] == "denied"
        assert denied_tgt_json["diagnostic_category"] == "unauthorized_target"

        # 6. Clean broker stop
        stop_res = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(staged_ps1), "broker", "stop", "-P", pipe_name, "-f", "json"],
            cwd=str(agent_cwd),
            env=clean_env,
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(stop_res.stdout)["status"] == "revoked_and_stopping"
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
