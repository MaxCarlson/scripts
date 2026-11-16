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


@pytest.mark.parametrize("group", ["boot", "setup", "guest", "artifact", "evidence", "checkpoint", "workflow"])
def test_nested_group_help_exits_zero(group: str) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([group, "--help"])
    assert exc.value.code == 0
