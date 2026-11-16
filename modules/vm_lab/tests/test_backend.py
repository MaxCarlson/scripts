"""Phase 1 unit tests for BackendAdapter, redaction, error handling, and CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vm_lab import cli
from vm_lab.backend import BackendAdapter, resolve_powershell_exe
from vm_lab.exceptions import (
    EXIT_AUTH_REQUIRED,
    EXIT_ERROR,
    EXIT_INCOMPLETE,
    EXIT_INTERACTION_REQUIRED,
    EXIT_SUCCESS,
    BackendExecutionError,
    PowerShellNotFoundError,
    UnsupportedPlatformError,
)
from vm_lab.results import classify_exit_code, redact_sensitive


def test_unsupported_platform_raises_clear_error() -> None:
    with pytest.raises(UnsupportedPlatformError):
        resolve_powershell_exe(platform_name="posix")


def test_missing_powershell_raises_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vm_lab.backend.os.name", "nt")
    monkeypatch.setattr("vm_lab.backend.shutil.which", lambda _name: None)
    with pytest.raises(PowerShellNotFoundError):
        resolve_powershell_exe(platform_name="nt")


def test_secret_args_are_rejected() -> None:
    be = BackendAdapter(pwsh_exe="pwsh")
    with pytest.raises(BackendExecutionError, match="plaintext password"):
        be.invoke(["-o", "guest-status", "-Password", "hunter2"])


def test_redact_sensitive_masks_secrets() -> None:
    raw = "error password='MySecret123' token=abc123"
    redacted = redact_sensitive(raw)
    assert "MySecret123" not in redacted
    assert "abc123" not in redacted
    assert "password=[REDACTED]" in redacted
    assert "token=[REDACTED]" in redacted


def test_backend_adapter_preserves_unicode_and_spaces_with_shell_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=json.dumps({"status": "PLANNED", "vm_name": "Lab VM 日本語"}),
            stderr="",
        )

    monkeypatch.setattr("vm_lab.backend.subprocess.run", fake_run)
    be = BackendAdapter(pwsh_exe="pwsh.exe")
    res = be.invoke(["-o", "plan", "-n", "Lab VM 日本語", "-r", str(tmp_path / "with space")])

    assert captured["kwargs"]["shell"] is False  # type: ignore[index]
    assert "Lab VM 日本語" in captured["cmd"]  # type: ignore[operator]
    assert res.exit_code == EXIT_SUCCESS
    assert res.data["status"] == "PLANNED"


def test_exit_code_classification_taxonomy() -> None:
    assert classify_exit_code({"status": "SUCCEEDED"}, 0) == EXIT_SUCCESS
    assert classify_exit_code({"status": "AWAITING_INTERACTION"}, 0) == EXIT_INTERACTION_REQUIRED
    assert classify_exit_code({"status": "BLOCKED", "reason_code": "capability_required_vm_lifecycle"}, 1) == EXIT_AUTH_REQUIRED
    assert classify_exit_code({"status": "PARTIAL"}, 1) == EXIT_INCOMPLETE
    assert classify_exit_code({"status": "FAILED"}, 1) == EXIT_ERROR


def test_cli_help_and_version_work_without_hyperv(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["version", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["package"] == "vm_lab"

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0

    with pytest.raises(SystemExit) as exc2:
        cli.main(["-h"])
    assert exc2.value.code == 0


def test_cli_legacy_passthrough_propagates_nonzero_exit() -> None:
    mock_be = MagicMock()
    mock_be.invoke.return_value = MagicMock(stdout='{"status":"FAILED"}\n', stderr="", exit_code=EXIT_ERROR)
    rc = cli.main(["-o", "guest-verify", "-n", "TestVM", "-j"], adapter=mock_be)
    assert rc == EXIT_ERROR
