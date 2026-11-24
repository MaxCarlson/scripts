"""Managed and explicitly authorized generic provider argument contracts."""

from __future__ import annotations

import json

import pytest

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import (
    _requested_permission_settings,
    _safe_launch_settings,
    _validated_native_args,
)
from agent_continuity.errors import ContinuityError


def test_common_managed_options_preserve_provider_argv() -> None:
    args = [
        "-s", "workspace-write", "-a", "on-request", "--model", "model name",
        "--profile", "work", "--add-dir", r"C:\work area", "-c", "model_reasoning_effort=high",
    ]
    assert _validated_native_args("codex", args) == args


def test_agy_managed_options_include_final_sandbox_and_json_settings() -> None:
    settings = json.dumps({"model": "gemini", "effort": "high"})
    args = ["--add-dir", "/work area", "--settings", settings, "--sandbox"]
    assert _validated_native_args("agy", args) == args
    assert _requested_permission_settings("agy", args) == {"--sandbox": True}


def test_generic_options_need_explicit_opt_in_and_remain_argv_tokens() -> None:
    with pytest.raises(ContinuityError, match="--allow-native-unknown"):
        _validated_native_args("codex", ["--future-option", "value"])
    args = ["--future-option", "two words", "--future-bool"]
    assert _validated_native_args("codex", args, allow_unknown=True) == args


def test_generic_permission_option_is_visible_as_unclassified() -> None:
    requested = _requested_permission_settings(
        "codex", ["--sandbox-permissions-v2", "workspace-write"], allow_unknown=True
    )
    assert requested["unclassified_permission_options"][0]["option"] == "--sandbox-permissions-v2"
    assert requested["unclassified_permission_options"][0]["value"] == "omitted"


def test_generic_permission_configuration_is_visible_without_its_value() -> None:
    requested = _requested_permission_settings(
        "codex", ["-c", "sandbox_permissions=['disk-full-read-access']"], allow_unknown=True
    )
    item = requested["unclassified_permission_configuration"][0]
    assert item["key"] == "sandbox_permissions"
    assert item["value"] == "omitted"


@pytest.mark.parametrize(
    "args",
    [
        ["resume", "some-session"], ["--last"], ["--exec"], ["--worktree"],
        ["--dangerously-bypass-approvals-and-sandbox"], ["--dangerously-skip-permissions"],
        ["--remote", "ws://example"],
    ],
)
def test_explicit_unknown_opt_in_never_waives_identity_or_execution_guards(args: list[str]) -> None:
    with pytest.raises(ContinuityError):
        _validated_native_args("codex", args, allow_unknown=True)


@pytest.mark.parametrize(
    "provider,args",
    [
        ("codex", ["-c", "session_id=other"]),
        ("codex", ["-c", "sandbox_mode=unsafe"]),
        ("agy", ["--settings", json.dumps({"conversation": "other"})]),
        ("agy", ["--settings", json.dumps({"mode": "plan"})]),
        ("codex", ["--api-key", "hidden"]),
    ],
)
def test_unknown_authorization_does_not_bypass_config_safety(provider: str, args: list[str]) -> None:
    with pytest.raises(ContinuityError):
        _validated_native_args(provider, args, allow_unknown=True)


def test_safe_summary_redacts_configuration_values_and_lists_permission_settings() -> None:
    args = ["--sandbox", "workspace-write", "--approve-for-me", "-c", "model_reasoning_effort=high"]
    summary = _safe_launch_settings("codex", args)
    assert summary["sandbox"] == "workspace-write"
    assert summary["approval_policy"] == "auto-review"
    assert summary["reasoning_effort"] == "high"
    assert _requested_permission_settings("codex", args) == {
        "--sandbox": ["workspace-write"], "--approve-for-me": True,
    }


def test_secrets_and_raw_settings_are_never_managed_or_persisted() -> None:
    with pytest.raises(ContinuityError):
        _validated_native_args("codex", ["-c", "api_key=top-secret"], allow_unknown=True)
    with pytest.raises(ContinuityError):
        _validated_native_args("agy", ["--settings", "C:/private/settings.json"])


def test_managed_additional_directories_are_validated_before_launch(tmp_path) -> None:
    from agent_continuity.dispatcher_cli import _validate_additional_directories

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    environment_id = dispatcher.materializer.list_environments()[0].environment_id
    existing = tmp_path / "shared dir"
    existing.mkdir()
    _validate_additional_directories(dispatcher, "codex", environment_id, ["--add-dir", str(existing)])
    with pytest.raises(ContinuityError, match="does not exist"):
        _validate_additional_directories(dispatcher, "agy", environment_id, ["--add-dir", str(existing / "missing")])


def test_cli_parser_places_unknown_authorization_before_provider_separator() -> None:
    from agent_continuity.dispatcher_cli import build_parser

    args = build_parser().parse_args([
        "continue", "GUI", "Agent", "-U", "-a", "--", "--future-option", "two words"
    ])
    assert args.allow_native_unknown is True
    assert args.native_args == ["--future-option", "two words"]


def test_provider_resume_order_preserves_identity_and_provider_specific_flags() -> None:
    from agent_continuity.providers.agy import AgyAdapter
    from agent_continuity.providers.codex import CodexAdapter

    codex = CodexAdapter(which_fn=lambda _: None, home_dir=None).resolve_resume_command(
        "codex-id", cwd=None, native_args=["--sandbox", "workspace-write", "--model", "model"]
    )
    agy = AgyAdapter(which_fn=lambda _: None, home_dir=None).resolve_resume_command(
        "agy-id", native_args=["--sandbox", "--effort", "high"]
    )
    assert codex.argv == ["codex", "resume", "--sandbox", "workspace-write", "--model", "model", "codex-id"]
    assert agy.argv == ["agy", "--conversation", "agy-id", "--sandbox", "--effort", "high"]
