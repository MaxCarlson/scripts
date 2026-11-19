"""Phase 3 tests for H4 adapters, descriptors, dry-run installer, and registry integration."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

MODULE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = MODULE_ROOT.parent.parent
ADAPTERS_DIR = MODULE_ROOT / "adapters"
DESCRIPTORS_DIR = MODULE_ROOT / "descriptors"
SCRIPTS_DIR = MODULE_ROOT / "scripts"
H4_VM_ID = "d8483f98-8884-4758-abd1-cd6107c83c03"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().lower()


def test_h4_descriptors_match_checked_in_adapter_hashes() -> None:
    expected_map = {
        "h4.preflight.json": "Invoke-H4PreflightAdapter.ps1",
        "h4.qualify.json": "Invoke-H4QualifyAdapter.ps1",
        "h4.recover.json": "Invoke-H4RecoverAdapter.ps1",
        "synthetic.mutate.json": "Invoke-SyntheticMutationAdapter.ps1",
    }
    for desc_name, adapter_name in expected_map.items():
        desc = json.loads((DESCRIPTORS_DIR / desc_name).read_text(encoding="utf-8"))
        assert desc["script_sha256"].lower() == _sha256(ADAPTERS_DIR / adapter_name)
        if desc_name.startswith("h4."):
            assert desc["requires_guest_credential"] is True
            assert desc["allowed_targets"] == [H4_VM_ID]

    qualify_desc = json.loads((DESCRIPTORS_DIR / "h4.qualify.json").read_text(encoding="utf-8"))
    allowed_stages = qualify_desc["parameter_schema"]["stage"]["allowed_values"]
    assert "All" not in allowed_stages
    assert "Checkpoint" not in allowed_stages
    assert "Install" not in allowed_stages
    assert set(allowed_stages) == {"Preflight", "Setup", "Acceptance"}


@pytest.mark.skipif(os.name != "nt", reason="PowerShell 7 synthetic mutation adapter runs on Windows")
def test_synthetic_mutation_adapter_dry_run_and_apply(tmp_path: Path) -> None:
    adapter = ADAPTERS_DIR / "Invoke-SyntheticMutationAdapter.ps1"
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    r_dry = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(adapter),
            "-OperationId",
            "op-sdry",
            "-TargetId",
            "synth-target-1",
            "-Marker",
            "dry1",
        ],
        cwd=work_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    dry_json = json.loads(r_dry.stdout.strip())
    assert dry_json["mode"] == "dry_run"
    assert dry_json["apply_count"] == 0
    assert not (work_dir / "synthetic-synth-target-1.json").exists()

    r_app = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(adapter),
            "-OperationId",
            "op-sapp",
            "-TargetId",
            "synth-target-1",
            "-Marker",
            "app1",
            "-Apply",
        ],
        cwd=work_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    app_json = json.loads(r_app.stdout.strip())
    assert app_json["mode"] == "apply"
    assert app_json["apply_count"] == 1
    assert (work_dir / "synthetic-synth-target-1.json").is_file()


def test_install_and_uninstall_scripts_dry_run_by_default() -> None:
    install_ps1 = SCRIPTS_DIR / "Install-PrivExec.ps1"
    uninstall_ps1 = SCRIPTS_DIR / "Uninstall-PrivExec.ps1"

    res_install = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(install_ps1), "-Json"],
        capture_output=True,
        text=True,
        check=True,
    )
    install_plan = json.loads(res_install.stdout)
    assert install_plan["apply"] is False
    assert install_plan["creates_service"] is False
    assert install_plan["creates_task"] is False
    assert install_plan["modifies_accounts"] is False
    assert "NOT a security boundary" in install_plan["security_notice"]

    res_cross = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(install_ps1),
            "-Mode",
            "CrossAccountIsolated",
            "-Json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_cross.returncode != 0

    res_uninstall = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(uninstall_ps1), "-Json"],
        capture_output=True,
        text=True,
        check=True,
    )
    uninstall_plan = json.loads(res_uninstall.stdout)
    assert uninstall_plan["apply"] is False
    assert uninstall_plan["purge_state"] is False


@pytest.mark.skipif(os.name != "nt", reason="PowerShell 7 H4 adapter test runs on Windows")
def test_h4_adapters_with_mocked_h4_wrappers_and_stdin_credentials(tmp_path: Path) -> None:
    mock_qual = tmp_path / "Invoke-H4GuestQualification.ps1"
    mock_qual.write_text(
        """
param(
    [string]$Stage = 'Preflight',
    [switch]$Apply,
    [switch]$AuthorizeGuestMutation,
    [switch]$Json,
    [string]$OperationId,
    [string]$VmId,
    [string]$VmName,
    [string]$ExpectedGuestHost,
    [string]$EvidenceRoot,
    [string]$RunSuffix,
    [pscredential]$Credential
)
$res = [ordered]@{
    mock = $true
    stage = $Stage
    apply = [bool]$Apply
    authorize_guest_mutation = [bool]$AuthorizeGuestMutation
    operation_id = $OperationId
    vm_id = $VmId
    cred_user = if ($Credential) { $Credential.UserName } else { $null }
    has_cred = ($null -ne $Credential)
}
$res | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    mock_qual_sha = _sha256(mock_qual)

    cred_stdin = json.dumps({"username": "DESKTOP-1ITSJV0\\mcarls", "password": "MockSecretPassword!99"}) + "\n"

    # 1. Preflight adapter never passes Apply or AuthorizeGuestMutation
    p_pre = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(ADAPTERS_DIR / "Invoke-H4PreflightAdapter.ps1"),
            "-H4QualificationScript",
            str(mock_qual),
            "-ExpectedH4ScriptSha256",
            mock_qual_sha,
            "-OperationId",
            "op-pre-1",
        ],
        input=cred_stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "MockSecretPassword" not in p_pre.stdout
    pre_json = json.loads(p_pre.stdout.strip())
    assert pre_json["stage"] == "Preflight"
    assert pre_json["apply"] is False
    assert pre_json["authorize_guest_mutation"] is False
    assert pre_json["has_cred"] is True
    assert pre_json["cred_user"] == "DESKTOP-1ITSJV0\\mcarls"

    # 2. Qualify adapter refuses Acceptance + Apply without AuthorizeGuestMutation
    p_acc_denied = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(ADAPTERS_DIR / "Invoke-H4QualifyAdapter.ps1"),
            "-H4QualificationScript",
            str(mock_qual),
            "-ExpectedH4ScriptSha256",
            mock_qual_sha,
            "-Stage",
            "Acceptance",
            "-Apply",
        ],
        input=cred_stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    assert p_acc_denied.returncode != 0

    # 3. Qualify adapter allows Setup + Apply
    p_setup = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(ADAPTERS_DIR / "Invoke-H4QualifyAdapter.ps1"),
            "-H4QualificationScript",
            str(mock_qual),
            "-ExpectedH4ScriptSha256",
            mock_qual_sha,
            "-Stage",
            "Setup",
            "-Apply",
            "-OperationId",
            "op-setup-1",
        ],
        input=cred_stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    setup_json = json.loads(p_setup.stdout.strip())
    assert setup_json["stage"] == "Setup"
    assert setup_json["apply"] is True

    # 4. Recover adapter defaults to dry-run and preserves ProtectedCheckpointId
    mock_rec = tmp_path / "Invoke-H4GuestRecovery.ps1"
    mock_rec.write_text(
        """
param(
    [switch]$Apply,
    [switch]$AuthorizeGuestMutation,
    [switch]$StageBundle,
    [switch]$PostInventory,
    [switch]$Json,
    [string]$OperationId,
    [string]$VmId,
    [string]$VmName,
    [string]$ProtectedCheckpointId,
    [string]$ExpectedGuestHost,
    [string]$EvidenceRoot,
    [pscredential]$Credential
)
[ordered]@{
    mock = $true
    apply = [bool]$Apply
    authorize_guest_mutation = [bool]$AuthorizeGuestMutation
    protected_checkpoint_id = $ProtectedCheckpointId
    has_cred = ($null -ne $Credential)
} | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    p_rec = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(ADAPTERS_DIR / "Invoke-H4RecoverAdapter.ps1"),
            "-H4RecoveryScript",
            str(mock_rec),
            "-ExpectedH4ScriptSha256",
            _sha256(mock_rec),
            "-OperationId",
            "op-rec-1",
        ],
        input=cred_stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    rec_json = json.loads(p_rec.stdout.strip())
    assert rec_json["apply"] is False
    assert rec_json["protected_checkpoint_id"] == "9f45b469-382c-4be0-a50e-7a71384c7922"
    assert rec_json["has_cred"] is True

    # 5. SHA-256 mismatch on H4 script fails closed
    p_tamper = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(ADAPTERS_DIR / "Invoke-H4PreflightAdapter.ps1"),
            "-H4QualificationScript",
            str(mock_qual),
            "-ExpectedH4ScriptSha256",
            "0" * 64,
        ],
        input=cred_stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    assert p_tamper.returncode != 0


def test_scripts_help_registry_contains_privileged_execution() -> None:
    registry_py = REPO_ROOT / "modules" / "scripts_help" / "scripts_help" / "registry" / "registry.py"
    text = registry_py.read_text(encoding="utf-8")
    assert "privileged_execution (module)" in text
    assert '"path": "modules/privileged_execution"' in text


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows and built PrivExecBroker.dll")
def test_broker_rejects_invalid_pipe_name(tmp_path: Path) -> None:
    broker_dll = MODULE_ROOT / "broker" / "bin" / "PrivExecBroker.dll"
    if not broker_dll.is_file():
        pytest.skip("PrivExecBroker.dll not built")
    res = subprocess.run(
        [
            "dotnet",
            str(broker_dll),
            "--pipe",
            r"bad\pipe",
            "--descriptors-dir",
            str(DESCRIPTORS_DIR),
            "--state-dir",
            str(tmp_path / "state"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 2
    assert "Invalid pipe name" in res.stderr


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows and built PrivExecBroker.dll")
def test_gate2_cross_account_script_against_temp_broker(tmp_path: Path) -> None:
    broker_dll = MODULE_ROOT / "broker" / "bin" / "PrivExecBroker.dll"
    if not broker_dll.is_file():
        pytest.skip("PrivExecBroker.dll not built")

    import time
    import uuid

    # Stage synthetic.echo and synthetic.mutate into tmp_path
    staged_root = tmp_path / "staged"
    (staged_root / "bin").mkdir(parents=True)
    (staged_root / "descriptors").mkdir(parents=True)
    (staged_root / "adapters").mkdir(parents=True)
    (staged_root / "state").mkdir(parents=True)
    (staged_root / "work").mkdir(parents=True)

    adapter_src = ADAPTERS_DIR / "Invoke-SyntheticMutationAdapter.ps1"
    adapter_dst = staged_root / "adapters" / adapter_src.name
    adapter_dst.write_text(adapter_src.read_text(encoding="utf-8"), encoding="utf-8")

    (staged_root / "descriptors" / "synthetic.echo.json").write_text(
        (DESCRIPTORS_DIR / "synthetic.echo.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    mut_desc = json.loads((DESCRIPTORS_DIR / "synthetic.mutate.json").read_text(encoding="utf-8"))
    mut_desc["script_path"] = str(adapter_dst)
    mut_desc["script_sha256"] = _sha256(adapter_dst)
    mut_desc["working_directory"] = str(staged_root / "work")
    (staged_root / "descriptors" / "synthetic.mutate.json").write_text(
        json.dumps(mut_desc, indent=2), encoding="utf-8"
    )

    pipe_name = f"privexec-g2-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    grant_file = tmp_path / "grant.json"
    grant_file.write_text(
        json.dumps(
            {
                "allowed_capabilities": ["synthetic.echo", "synthetic.mutate"],
                "allowed_targets": ["synth-target-1"],
                "allow_mutation": True,
                "allowed_mutation_capabilities": ["synthetic.mutate"],
                "ttl_seconds": 120,
            }
        ),
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [
            "dotnet",
            str(broker_dll),
            "--pipe",
            pipe_name,
            "--descriptors-dir",
            str(staged_root / "descriptors"),
            "--state-dir",
            str(staged_root / "state"),
            "--grant-file",
            str(grant_file),
            "--allow-same-user",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert proc.stdout is not None
        deadline = time.monotonic() + 10.0
        ready = False
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line and line.strip().startswith("PRIVEXEC_BROKER_READY"):
                ready = True
                break
        assert ready, "Broker failed to report READY"

        # Verify pipe protocol checks (expect filesystem check to skip/fail only if writable; here test pipe + dry-run/apply)
        # Note: in same-user tmp_path, the user owns staged_root, so Test-PrivExecCrossAccount.ps1 filesystem write test
        # would see write-allowed; we test the cross-account script's pipe protocol & negative checks via a read-only lock or test its pipe checks directly.
        # Make protected targets read-only attribute temporarily? No, File.OpenWrite respects ReadOnly attribute on Windows!
        (staged_root / "bin" / "PrivExecBroker.dll").write_text("x", encoding="utf-8")
        (staged_root / "state" / "privexec.db").write_text("x", encoding="utf-8")
        for ro_target in (
            staged_root / "bin" / "PrivExecBroker.dll",
            staged_root / "descriptors" / "synthetic.echo.json",
            adapter_dst,
            staged_root / "state" / "privexec.db",
        ):
            os.chmod(ro_target, 0o444)

        try:
            res = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(SCRIPTS_DIR / "Test-PrivExecCrossAccount.ps1"),
                    "-PipeName",
                    pipe_name,
                    "-InstallRoot",
                    str(staged_root),
                    "-Role",
                    "AuthorizedAgent",
                    "-ExpectSameUserOperator",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            report = json.loads(res.stdout)
            assert report["passed"] is True
            assert len(report["checks"]) == 9
            assert any(c["check"] == "isolated_temp_environment" for c in report["checks"])
        finally:
            for ro_target in (
                staged_root / "bin" / "PrivExecBroker.dll",
                staged_root / "descriptors" / "synthetic.echo.json",
                adapter_dst,
                staged_root / "state" / "privexec.db",
            ):
                os.chmod(ro_target, 0o666)
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows PowerShell 7")
def test_cross_account_script_detects_mismatched_temp_and_reports_pipe_eof(tmp_path: Path) -> None:
    import threading
    import uuid

    # 1. Wrong ExpectedTempDir fails immediately with actionable diagnostic
    wrong_temp = tmp_path / "expected-other-temp"
    wrong_temp.mkdir()
    res_temp = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(SCRIPTS_DIR / "Test-PrivExecCrossAccount.ps1"),
            "-PipeName",
            "unused-pipe",
            "-ExpectedTempDir",
            str(wrong_temp),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_temp.returncode != 0
    assert "Child temp directory mismatch" in res_temp.stderr

    # 2. Early pipe closure before response header reports pipe name & bytes_read=0
    pipe_name = f"privexec-eof-mock-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    ready_ev = threading.Event()

    def _close_early() -> None:
        import ctypes
        import ctypes.wintypes as wt

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateNamedPipeW.restype = wt.HANDLE
        h = k32.CreateNamedPipeW(rf"\\.\pipe\{pipe_name}", 3, 0, 1, 4096, 4096, 0, None)
        ready_ev.set()
        k32.ConnectNamedPipe(h, None)
        hdr = ctypes.create_string_buffer(4)
        n = wt.DWORD(0)
        k32.ReadFile(h, hdr, 4, ctypes.byref(n), None)
        body_len = int.from_bytes(hdr.raw[:4], "little")
        body = ctypes.create_string_buffer(body_len)
        k32.ReadFile(h, body, body_len, ctypes.byref(n), None)
        k32.DisconnectNamedPipe(h)
        k32.CloseHandle(h)

    t = threading.Thread(target=_close_early, daemon=True)
    t.start()
    ready_ev.wait(timeout=3.0)

    res_eof = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(SCRIPTS_DIR / "Test-PrivExecCrossAccount.ps1"),
            "-PipeName",
            pipe_name,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    t.join(timeout=3.0)
    assert res_eof.returncode != 0
    assert "Unexpected EOF reading pipe response header" in res_eof.stderr
    assert f"pipe='{pipe_name}'" in res_eof.stderr
    assert "bytes_read=0" in res_eof.stderr


def test_gate2_account_description_length_and_cleanup_matching() -> None:
    import uuid
    from datetime import UTC, datetime

    # 1. Verify standard runId and description length constraints
    now_utc = datetime.now(UTC)
    run_id = f"{now_utc.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    assert len(run_id) == 24

    agent_desc = f"PE2:agent:{run_id}"
    unauth_desc = f"PE2:unauth:{run_id}"

    # Windows New-LocalUser -Description has a hard limit of 48 characters
    assert len(agent_desc) <= 48
    assert len(agent_desc) == 34
    assert len(unauth_desc) <= 48
    assert len(unauth_desc) == 35

    # Windows SAM account name has a hard limit of 20 characters
    agent_user = f"PrivExecAg_{uuid.uuid4().hex[:6]}"
    unauth_user = f"PrivExecUn_{uuid.uuid4().hex[:6]}"
    assert len(agent_user) <= 20
    assert len(agent_user) == 17
    assert len(unauth_user) <= 20
    assert len(unauth_user) == 17

    # Old failing description exceeded limit
    old_failing_tag = f"PrivExec Gate 2 temporary test account ({run_id})"
    assert len(old_failing_tag) == 65
    assert len(old_failing_tag) > 48

    # 2. Test ownership matching in PowerShell
    ps_script = f"""
    $runId = '{run_id}'
    $agentDesc = '{agent_desc}'
    $unauthDesc = '{unauth_desc}'
    $oldTag = '{old_failing_tag}'

    function Test-Ownership($desc, $targetRunId) {{
        if ([string]::IsNullOrWhiteSpace($desc) -or $desc.Length -gt 48) {{ return $false }}
        return ($desc -eq "PE2:agent:$targetRunId" -or $desc -eq "PE2:unauth:$targetRunId" -or ($desc -like "PE2:*:$targetRunId"))
    }}

    $checks = @(
        (Test-Ownership $agentDesc $runId),
        (Test-Ownership $unauthDesc $runId),
        (-not (Test-Ownership "PE2:agent:otherRunId" $runId)),
        (-not (Test-Ownership "Built-in account for guest" $runId)),
        (-not (Test-Ownership $oldTag $runId)),
        (-not (Test-Ownership "" $runId))
    )
    if ($checks -contains $false) {{ exit 1 }}
    Write-Output "OWNERSHIP_OK"
    """
    res = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "OWNERSHIP_OK" in res.stdout
