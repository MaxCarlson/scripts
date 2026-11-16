"""Phase 2 CLI subcommand dispatch, help, dry-run, and compatibility tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vm_lab import cli
from vm_lab.exceptions import EXIT_ERROR, EXIT_SUCCESS


def _mock_adapter(exit_code: int = EXIT_SUCCESS) -> MagicMock:
    be = MagicMock()
    be.invoke.return_value = MagicMock(stdout='{"status":"PLANNED"}\n', stderr="", exit_code=exit_code)
    return be


@pytest.mark.parametrize(
    ("argv", "expected_prefix"),
    [
        (["list", "--owned-only", "--json"], ["-o", "list", "-OwnedOnly", "-Json"]),
        (["inspect", "TestVM", "-j"], ["-o", "status", "-Name", "TestVM", "-Json"]),
        (["create", "TestVM", "--template", "windows11-dev"], ["-o", "create", "-Name", "TestVM", "-TemplateName", "windows11-dev"]),
        (["create", "TestVM", "--template", "windows11-dev", "--apply"], ["-o", "create", "-Name", "TestVM", "-TemplateName", "windows11-dev", "-Apply"]),
        (["start", "TestVM", "-a"], ["-o", "start", "-Name", "TestVM", "-Apply"]),
        (["stop", "TestVM", "--shutdown-timeout", "45"], ["-o", "stop", "-Name", "TestVM", "-ShutdownTimeoutSeconds", "45"]),
        (["connect", "TestVM"], ["-o", "connect", "-Name", "TestVM"]),
        (["boot", "inspect", "TestVM", "-j"], ["-o", "boot-diagnostics", "-Name", "TestVM", "-Json"]),
        (["setup", "answer-media", r"C:\Temp\Autounattend.xml", "-a"], ["-o", "unattend-xml", "-OutputPath", r"C:\Temp\Autounattend.xml", "-Locale", "en-US", "-KeyboardLayout", "en-US", "-Apply"]),
        (["guest", "status", "TestVM"], ["-o", "guest-status", "-Name", "TestVM"]),
        (["guest", "bootstrap", "TestVM", "--profile", "python-dev", "-a"], ["-o", "guest-bootstrap", "-Name", "TestVM", "-GuestProfile", "python-dev"]),
        (["guest", "exec", "TestVM", "--executable", r"C:\App\run.exe", "--", "--flag", "val"], ["-o", "guest-exec", "-Name", "TestVM", "-ExecutablePath", r"C:\App\run.exe", "-WorkingDirectory", r"C:\Windows\Temp", "-ArgumentList", "--flag", "val"]),
        (["artifact", "deploy", "TestVM", "--manifest", "m.json", "--authorize-guest-mutation", "-a"], ["-o", "artifact-deploy", "-Name", "TestVM", "-ArtifactManifestPath", "m.json", "-AuthorizeGuestMutation", "-Apply"]),
        (["evidence", "collect", "TestVM", "--guest-roots", r"C:\Ev", "--evidence-root", r"C:\HostEv", "-a"], ["-o", "evidence-collect", "-Name", "TestVM", "-GuestRoots", r"C:\Ev", "-EvidenceRoot", r"C:\HostEv", "-Apply"]),
        (["checkpoint", "list", "TestVM"], ["-o", "checkpoints", "-Name", "TestVM"]),
        (["checkpoint", "create", "TestVM", "cp1", "-a"], ["-o", "checkpoint", "-Name", "TestVM", "-CheckpointName", "cp1", "-Apply"]),
        (["checkpoint", "transaction", "TestVM", "cp-tx", "--restart-after", "--authorize-vm-lifecycle", "-a"], ["-o", "lifecycle-transaction", "-Name", "TestVM", "-CheckpointName", "cp-tx", "-RestartAfter", "-AuthorizeVmLifecycle", "-Apply"]),
        (["workflow", "plan", "wf.json", "-j"], ["-o", "workflow-plan", "-WorkflowPath", "wf.json", "-Json"]),
        (["workflow", "run", "wf.json", "--authorize-host-mutation", "-a"], ["-o", "workflow-apply", "-WorkflowPath", "wf.json", "-AuthorizeHostMutation", "-Apply"]),
        (["workflow", "status", "op-1", "-j"], ["-o", "workflow-status", "-OperationId", "op-1", "-Json"]),
        (["workflow", "resume", "op-1", "--authorize-guest-exec", "-a"], ["-o", "workflow-resume", "-OperationId", "op-1", "-AuthorizeGuestExec", "-Apply"]),
        (["workflow", "doctor", "op-1", "-j"], ["-o", "workflow-doctor", "-OperationId", "op-1", "-Json"]),
    ],
)
def test_cli_subcommands_dispatch_expected_ps_args(argv: list[str], expected_prefix: list[str]) -> None:
    be = _mock_adapter()
    rc = cli.main(argv, adapter=be)
    assert rc == EXIT_SUCCESS
    actual_args = be.invoke.call_args.args[0]
    for token in expected_prefix:
        assert token in actual_args


def test_dry_run_default_omits_apply_flag() -> None:
    be = _mock_adapter()
    cli.main(["create", "DryVM"], adapter=be)
    actual_args = be.invoke.call_args.args[0]
    assert "-Apply" not in actual_args


def test_nonzero_exit_propagated() -> None:
    be = _mock_adapter(exit_code=EXIT_ERROR)
    rc = cli.main(["doctor", "-j"], adapter=be)
    assert rc == EXIT_ERROR


@pytest.mark.parametrize("group", ["boot", "setup", "guest", "artifact", "evidence", "checkpoint", "workflow", "host", "media", "approval"])
def test_nested_group_help_exits_zero(group: str) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([group, "--help"])
    assert exc.value.code == 0


@pytest.mark.parametrize(
    ("argv", "expected_tokens"),
    [
        (["restart", "TestVM", "--authorize-vm-lifecycle", "-a"], ["-o", "guest-reboot", "-Name", "TestVM", "-AuthorizeVmLifecycle", "-Apply"]),
        (["host", "resources", "-j"], ["-o", "host-resources", "-Json"]),
        (["media", "iso", "verify", "win11.iso", "--expected-sha256", "a" * 64, "-j"], ["-o", "iso-verify", "-IsoPath", "win11.iso", "-ExpectedSha256", "a" * 64, "-Json"]),
        (["media", "iso", "attach", "TestVM", "win11.iso", "-a"], ["-o", "iso-attach", "-Name", "TestVM", "-IsoPath", "win11.iso", "-Apply"]),
        (["media", "iso", "detach", "TestVM", "-a"], ["-o", "iso-detach", "-Name", "TestVM", "-Apply"]),
        (["boot", "prepare", "TestVM", "--prefer-dvd", "-a"], ["-o", "boot-prepare", "-Name", "TestVM", "-PreferDvd", "-Apply"]),
        (["boot", "troubleshoot", "TestVM", "-j"], ["-o", "boot-troubleshoot", "-Name", "TestVM", "-Json"]),
        (["setup", "plan", "TestVM", "-j"], ["-o", "setup-report", "-Name", "TestVM", "-Json"]),
        (["setup", "guide", "TestVM", "-j"], ["-o", "setup-report", "-Name", "TestVM", "-Json"]),
        (["guest", "wait", "TestVM", "--timeout-seconds", "45"], ["-o", "guest-wait", "-Name", "TestVM", "-TimeoutSeconds", "45"]),
        (["guest", "identity", "TestVM", "-j"], ["-o", "guest-identity", "-Name", "TestVM", "-Json"]),
        (["guest", "inventory", "TestVM", "--processes", "--services", "--tasks"], ["-o", "guest-inventory", "-Name", "TestVM", "-IncludeProcesses", "-IncludeServices", "-IncludeTasks"]),
        (["guest", "run-script", "TestVM", "--script", "run.ps1", "--authorize-guest-exec", "-a", "--", "--arg1"], ["-o", "guest-run-script", "-Name", "TestVM", "-ScriptPath", "run.ps1", "-ArgumentList", "--arg1", "-AuthorizeGuestExec", "-Apply"]),
        (["guest", "reboot", "TestVM", "--authorize-vm-lifecycle", "-a"], ["-o", "guest-reboot", "-Name", "TestVM", "-AuthorizeVmLifecycle", "-Apply"]),
        (["evidence", "inspect", "op-1", "-j"], ["-o", "evidence-inspect", "-OperationId", "op-1", "-Json"]),
        (["checkpoint", "inspect", "TestVM", "--checkpoint-id", "cp-1", "-j"], ["-o", "checkpoint-inspect", "-Name", "TestVM", "-CheckpointId", "cp-1", "-Json"]),
        (["workflow", "validate", "wf.json", "-j"], ["-o", "workflow-plan", "-WorkflowPath", "wf.json", "-Json"]),
        (["workflow", "results", "op-1", "-j"], ["-o", "workflow-results", "-OperationId", "op-1", "-Json"]),
        (["approval", "request", "wf.json", "--output", "req.json", "-j"], ["-o", "approval-request", "-WorkflowPath", "wf.json", "-OutputPath", "req.json", "-Json"]),
        (["approval", "inspect", "req.json", "--expected-digest", "b" * 64, "-j"], ["-o", "approval-inspect", "-RequestPath", "req.json", "-ExpectedRequestDigest", "b" * 64, "-Json"]),
    ],
)
def test_phase3_to_6_cli_subcommands_dispatch(argv: list[str], expected_tokens: list[str]) -> None:
    be = _mock_adapter()
    rc = cli.main(argv, adapter=be)
    assert rc == EXIT_SUCCESS
    actual_args = be.invoke.call_args.args[0]
    for token in expected_tokens:
        assert token in actual_args


def test_approval_execute_dispatches_to_approved_plan_script() -> None:
    be = _mock_adapter()
    rc = cli.main(["approval", "execute", "req.json", "--expected-digest", "c" * 64, "--operator-consent"], adapter=be)
    assert rc == EXIT_SUCCESS
    assert be.invoke.call_args.kwargs["script_name"] == "Invoke-VmLabApprovedPlan.ps1"
    actual_args = be.invoke.call_args.args[0]
    assert "-RequestPath" in actual_args
    assert "-ExpectedRequestDigest" in actual_args
    assert "-OperatorConsent" in actual_args


def test_real_powershell_end_to_end_cli_dispatch(tmp_path: "Path", capsys: pytest.CaptureFixture[str]) -> None:
    """Exercise real BackendAdapter -> Invoke-VmLab.ps1 PowerShell -File binding without mocking BackendAdapter."""
    import json
    import sys
    from pathlib import Path

    if sys.platform != "win32":
        pytest.skip("PowerShell backend requires Windows")

    # 1. templates -j
    rc_tpl = cli.main(["templates", "-j"])
    assert rc_tpl == EXIT_SUCCESS
    tpls = json.loads(capsys.readouterr().out)
    assert any(t["template_id"] == "windows11-dev" for t in tpls)

    # 2. Legacy -o templates -j compatibility
    rc_leg = cli.main(["-o", "templates", "-j"])
    assert rc_leg == EXIT_SUCCESS
    leg_tpls = json.loads(capsys.readouterr().out)
    assert len(leg_tpls) == len(tpls)

    # 3. Path with spaces: setup answer-media (dry-run)
    space_dir = tmp_path / "dir with spaces"
    space_dir.mkdir()
    xml_out = space_dir / "Autounattend.xml"
    rc_xml = cli.main(["setup", "answer-media", str(xml_out), "-j"])
    assert rc_xml == EXIT_SUCCESS
    xml_res = json.loads(capsys.readouterr().out)
    assert xml_res["status"] == "planned"
    assert not xml_out.exists()

    # 4. media iso verify with invalid file returns nonzero exit
    bad_iso = space_dir / "tiny.iso"
    bad_iso.write_bytes(b"tiny")
    rc_iso = cli.main(["media", "iso", "verify", str(bad_iso), "-j"])
    assert rc_iso == EXIT_ERROR
    iso_res = json.loads(capsys.readouterr().out)
    assert iso_res["status"] == "FAILED"
    assert iso_res["reason_code"] == "iso_too_small"
