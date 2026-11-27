from __future__ import annotations

from agent_continuity.launch_context import (
    VERIFIED_CAPABILITIES,
    provider_settings_argv,
    resolve_portable_launch_context,
)


def test_unsupported_setting_does_not_discard_portable_context(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = {
        "provider": "codex",
        "repositories": [{"root": str(repo), "worktree": str(repo), "branch": "feature/x"}],
        "working_directory": str(repo),
        "authorized_directories": [str(repo)],
        "semantic_settings": {"reasoning_effort": "high", "mcp": ["local"]},
        "instructions": "Use the project conventions.",
    }
    context, preview = resolve_portable_launch_context(
        source, "claude", capabilities={"claude": {"reasoning_effort"}}
    )
    assert context.repositories[0]["branch"] == "feature/x"
    assert context.authorized_directories == (str(repo),)
    assert context.semantic_settings == source["semantic_settings"]
    assert {item.key: item.status for item in preview}["reasoning_effort"] == "translated"
    assert {item.key: item.status for item in preview}["mcp"] == "unsupported"


def test_missing_worktree_and_runtime_mismatch_are_conflicts(tmp_path):
    missing = tmp_path / "deleted-worktree"
    context, preview = resolve_portable_launch_context({
        "provider": "agy",
        "repositories": [{"worktree": str(missing)}],
        "runtime_identity": {"runtime_kind": "wsl", "distro": "Ubuntu"},
    }, "codex", destination_runtime={"runtime_kind": "windows", "distro": None})
    assert context.repositories[0]["worktree"] == str(missing)
    assert sum(item.status == "conflicting" for item in preview) == 2


def test_permission_broadening_is_conflicting_and_unknown_capabilities_are_unsupported():
    _, preview = resolve_portable_launch_context({
        "provider": "codex",
        "semantic_settings": {"filesystem": "read-only", "network": "restricted"},
        "destination_filesystem": "full-access",
    }, "claude", capabilities={"claude": {"filesystem"}})
    assert {item.key: item.status for item in preview} == {
        "filesystem": "conflicting", "network": "unsupported",
    }


def test_all_six_directional_provider_pairs_preserve_portable_context_and_destination_preferences(tmp_path):
    repo = tmp_path / "nested" / "repo"
    repo.mkdir(parents=True)
    for source_provider, destination in (
        ("codex", "agy"), ("agy", "codex"), ("codex", "claude"),
        ("claude", "codex"), ("agy", "claude"), ("claude", "agy"),
    ):
        context, preview = resolve_portable_launch_context({
            "provider": source_provider,
            "repositories": [{"root": str(repo), "worktree": str(repo), "branch": "feature/portable"}],
            "working_directory": str(repo),
            "explicit_directory_override": str(repo),
            "authorized_directories": [str(repo)],
            "runtime_identity": {"runtime_kind": "windows", "environment_id": "env-1"},
            "workflow_type": "implementation",
            "logical_agent_identity": "agent-4",
            "instructions": "Keep changes focused.",
            "semantic_settings": {"reasoning_effort": "high", "filesystem": "read-only", "approval": "on-request"},
            "destination_preferences": {destination: {"model": f"{destination}-preferred"}},
        }, destination, capabilities=VERIFIED_CAPABILITIES,
            destination_runtime={"runtime_kind": "windows", "environment_id": "env-1"})
        assert context.repositories[0]["branch"] == "feature/portable"
        assert context.explicit_directory_override == str(repo)
        assert context.logical_agent_identity == "agent-4"
        assert context.instructions == "Keep changes focused."
        assert {item.key: item.status for item in preview}["destination_preferences"] == "restored"
        assert {item.key: item.status for item in preview}["reasoning_effort"] == "translated"
        assert {item.key: item.status for item in preview}["approval"] == (
            "translated" if "approval" in VERIFIED_CAPABILITIES[destination] else "unsupported"
        )
    assert provider_settings_argv("codex", {"model": "m", "reasoning_effort": "high"}) == [
        "--model", "m", "--config", "model_reasoning_effort=high",
    ]
    assert provider_settings_argv("agy", {"model": "m", "reasoning_effort": "high"})[0] == "--settings"
    assert provider_settings_argv("claude", {"model": "m", "effort": "high"}) == [
        "--model", "m", "--effort", "high",
    ]
