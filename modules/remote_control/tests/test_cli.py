"""Tests for remote_control CLI management and enrollment commands."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from remote_control.cli import main


def test_cli_status_unbootstrapped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Status command indicates unbootstrapped state before operator creation."""
    auth_db = tmp_path / "auth.db"
    code = main(["-d", str(auth_db), "status", "-j"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["bootstrapped"] is False
    assert out["operator"] is None


def test_cli_bootstrap_and_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Bootstrap creates single operator identity, second bootstrap fails."""
    auth_db = tmp_path / "auth.db"

    # Bootstrap operator with stdin simulated password
    with patch("sys.stdin", io.StringIO("OperatorPassword123!\n")):
        code = main(["-d", str(auth_db), "bootstrap", "-u", "sysop", "-j"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["username"] == "sysop"
    assert "totp_secret" in out
    assert "otpauth://" in out["provisioning_uri"]

    # Status now shows bootstrapped
    code_stat = main(["-d", str(auth_db), "status", "-j"])
    assert code_stat == 0
    stat_out = json.loads(capsys.readouterr().out)
    assert stat_out["bootstrapped"] is True
    assert stat_out["operator"] == "sysop"

    # Second bootstrap fails
    with patch("sys.stdin", io.StringIO("AnotherPassword123!\n")):
        code_dup = main(["-d", str(auth_db), "bootstrap", "-u", "sysop2", "-j"])
    assert code_dup == 1


def test_cli_serve_rejects_external_binding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Serve command strictly rejects non-loopback host bindings in Phase 06."""
    auth_db = tmp_path / "auth.db"
    code = main(["-d", str(auth_db), "serve", "-H", "0.0.0.0"])
    assert code == 1
    err = capsys.readouterr().err
    assert "Security Error" in err
    assert "0.0.0.0" in err


def test_cli_reset_totp(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Reset-totp regenerates the two-factor secret for the operator."""
    auth_db = tmp_path / "auth.db"

    with patch("sys.stdin", io.StringIO("OperatorPassword123!\n")):
        main(["-d", str(auth_db), "bootstrap", "-u", "sysop", "-j"])
    capsys.readouterr()

    code = main(["-d", str(auth_db), "reset-totp", "-j"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert "totp_secret" in out


def test_cli_revoke_device_and_session(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Revoking non-existent device or session returns non-zero code."""
    auth_db = tmp_path / "auth.db"

    with patch("sys.stdin", io.StringIO("OperatorPassword123!\n")):
        main(["-d", str(auth_db), "bootstrap", "-u", "sysop", "-j"])
    capsys.readouterr()

    # Non-existent device returns 1
    code_dev = main(["-d", str(auth_db), "revoke-device", "--device-id", "non-existent-device"])
    assert code_dev == 1

    # Non-existent session returns 1
    code_sess = main(["-d", str(auth_db), "revoke-session", "--session-id", "non-existent-session"])
    assert code_sess == 1
