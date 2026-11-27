from __future__ import annotations

from agent_continuity.launch_context import resolve_portable_launch_context


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
