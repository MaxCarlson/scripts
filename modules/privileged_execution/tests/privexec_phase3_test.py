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
    }
    for desc_name, adapter_name in expected_map.items():
        desc = json.loads((DESCRIPTORS_DIR / desc_name).read_text(encoding="utf-8"))
        assert desc["requires_guest_credential"] is True
        assert desc["allowed_targets"] == [H4_VM_ID]
        assert desc["script_sha256"].lower() == _sha256(ADAPTERS_DIR / adapter_name)

    qualify_desc = json.loads((DESCRIPTORS_DIR / "h4.qualify.json").read_text(encoding="utf-8"))
    allowed_stages = qualify_desc["parameter_schema"]["stage"]["allowed_values"]
    assert "All" not in allowed_stages
    assert "Checkpoint" not in allowed_stages
    assert "Install" not in allowed_stages
    assert set(allowed_stages) == {"Preflight", "Setup", "Acceptance"}


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
