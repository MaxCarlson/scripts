"""Tests for Scenario I (Windows/WSL boundaries), environments, and provider adapters."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_continuity.environment import (
    assert_sqlite_writer_allowed,
    is_windows_mount_path,
    load_or_create_environment,
    resolve_environment_selector,
)
from agent_continuity.errors import ContinuityError, ErrorCode
from agent_continuity.models import EnvironmentInfo
from agent_continuity.providers.agy import AgyAdapter
from agent_continuity.providers.codex import CodexAdapter
from agent_continuity.service import ContinuityService


def test_wsl_cross_os_sqlite_write_guard(tmp_path: Path) -> None:
    win_mount = Path("/mnt/c/Users/mcarls/.agent_continuity/index.sqlite")
    with (
        patch("agent_continuity.environment.os.name", "posix"),
        patch("agent_continuity.environment.is_wsl2", return_value=True),
    ):
        assert is_windows_mount_path(win_mount) is True
        with pytest.raises(ContinuityError) as exc_info:
            assert_sqlite_writer_allowed(win_mount)
        assert exc_info.value.code == ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE

        # WSL-native ext4 path is allowed
        assert_sqlite_writer_allowed(Path("/home/mcarls/.agent_continuity/index.sqlite"))

    # Local test tmp_path on native OS is allowed
    assert_sqlite_writer_allowed(tmp_path / "index.sqlite")


def test_environment_persistence_and_selector_resolution(tmp_path: Path) -> None:
    home = tmp_path / "state"
    env_preview = load_or_create_environment(home, persist=False)
    assert not (home / "environment.json").exists()

    env_saved = load_or_create_environment(home, persist=True)
    assert (home / "environment.json").exists()
    env_again = load_or_create_environment(home, persist=True)
    assert env_saved.environment_id == env_again.environment_id
    assert env_preview.environment_id != env_saved.environment_id

    ubuntu = EnvironmentInfo("env_wsl_ubuntu_1", "wsl", "Ubuntu", "h", "WSL Ubuntu", "t", "t")
    debian = EnvironmentInfo("env_wsl_debian_2", "wsl", "Debian", "h", "WSL Debian", "t", "t")
    assert resolve_environment_selector("wsl:Ubuntu", [ubuntu, debian], env_saved).environment_id == "env_wsl_ubuntu_1"
    with pytest.raises(ContinuityError) as exc_info:
        resolve_environment_selector("wsl", [ubuntu, debian], env_saved)
    assert exc_info.value.code == ErrorCode.ENVIRONMENT_AMBIGUOUS


def test_provider_adapters_unavailable_and_resume_commands(tmp_path: Path) -> None:
    codex_missing = CodexAdapter(which_fn=lambda _: None, home_dir=tmp_path)
    health_c = codex_missing.get_health_status()
    assert health_c.status == "unavailable"
    assert health_c.error_code == ErrorCode.PROVIDER_UNAVAILABLE

    agy_missing = AgyAdapter(which_fn=lambda _: None, home_dir=tmp_path)
    health_a = agy_missing.get_health_status()
    assert health_a.status == "unavailable"
    assert health_a.capabilities.hook_installation is False
    assert health_a.capabilities.history_scan is False

    plan_c = codex_missing.resolve_resume_command(
        "019a-abc",
        cwd=r"C:\Users\mcarls\src\my repo",
        environment_id="env_win",
        runtime_kind="windows",
    )
    assert plan_c.argv == ["codex", "resume", "-C", r"C:\Users\mcarls\src\my repo", "019a-abc"]
    assert '"C:\\Users\\mcarls\\src\\my repo"' in plan_c.display_command

    plan_a = agy_missing.resolve_resume_command(
        "conv-xyz",
        cwd="/home/mcarls/src/scripts",
        environment_id="env_wsl",
        runtime_kind="wsl",
    )
    assert plan_a.argv == ["agy", "--conversation", "conv-xyz"]
    assert plan_a.display_command == "agy --conversation conv-xyz"


def test_unavailable_providers_still_allow_manual_continuity_and_diagnose(tmp_path: Path) -> None:
    home = tmp_path / "state"
    adapters = {
        "codex": CodexAdapter(which_fn=lambda _: None, home_dir=tmp_path),
        "agy": AgyAdapter(which_fn=lambda _: None, home_dir=tmp_path),
    }
    svc = ContinuityService(home_dir=home, adapters=adapters)
    svc.add_workflow(slug="demo", title="Demo", apply=True)
    svc.link_session(
        workflow_identifier="demo",
        provider="codex",
        native_session_id="manual-1",
        environment_selector="windows",
        apply=True,
    )
    diag = svc.diagnose()
    assert diag["providers"]["codex"]["status"] == "unavailable"
    assert diag["providers"]["agy"]["status"] == "unavailable"
    assert len(svc.find_sessions(workflow_identifier="demo")["sessions"]) == 1
