from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from agent_continuity.launch_context import (
    VERIFIED_CAPABILITIES,
    provider_settings_argv,
    resolve_portable_launch_context,
)


def test_scripts_repository_ignores_singular_root_worktree_directory():
    repo_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        ["git", "-C", str(repo_root), "check-ignore", "-q", ".worktree/llmd-test"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_unsupported_setting_does_not_discard_portable_context(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = {
        "provider": "codex",
        "repositories": [{"root": str(repo), "worktree": str(repo), "branch": "feature/x"}],
        "working_directory": str(repo),
        "authorized_directories": [str(repo)],
        "semantic_settings": {
            "reasoning_effort": "high",
            "filesystem": "read-only",
            "network": {"outbound": False},
            "search": True,
            "context": {"mcp_servers": ["local"]},
            "mcp": ["local"],
        },
        "instructions": "Use the project conventions.",
    }
    context, preview = resolve_portable_launch_context(
        source, "claude", capabilities={"claude": {"reasoning_effort"}}
    )
    assert context.repositories[0]["branch"] == "feature/x"
    assert context.authorized_directories == (str(repo),)
    assert context.semantic_settings == source["semantic_settings"]
    assert {item.key: item.status for item in preview}["reasoning_effort"] == "translated"
    assert {item.key: item.status for item in preview}["filesystem"] == "unsupported"
    assert {item.key: item.status for item in preview}["network"] == "unsupported"
    assert {item.key: item.status for item in preview}["search"] == "unsupported"
    assert {item.key: item.status for item in preview}["context"] == "unsupported"
    assert {item.key: item.status for item in preview}["mcp"] == "unsupported"


def test_workflow_resource_snapshot_survives_portable_context_resolution():
    snapshot = {
        "schema_version": 1,
        "selection": "hybrid",
        "resources": [{"id": "workflow.handoff", "revision": "abc123", "sha256": "f" * 64}],
    }
    context, _ = resolve_portable_launch_context({
        "provider": "codex",
        "workflow_type": "hybrid",
        "workflow_resource_snapshot": snapshot,
    }, "agy", capabilities=VERIFIED_CAPABILITIES)

    assert context.workflow_type == "hybrid"
    assert context.workflow_resource_snapshot == snapshot


def test_custom_instruction_preview_distinguishes_loaded_changed_and_missing_sources(tmp_path: Path):
    instructions = tmp_path / "AGENTS.md"
    instructions.write_bytes(b"loaded bytes\r\n")
    digest = hashlib.sha256(instructions.read_bytes()).hexdigest()
    source = {
        "provider": "codex",
        "workflow_resource_snapshot": {
            "schema_version": 2,
            "selection": "standard",
            "resources": [{
                "id": "custom:stable-id", "kind": "custom_file", "path": str(instructions.resolve()),
                "revision": digest[:12], "sha256": digest,
            }],
        },
        "workflow_custom_instruction_paths": [str(instructions.resolve())],
    }

    _, loaded_preview = resolve_portable_launch_context(source, "agy")
    loaded = next(item for item in loaded_preview if item.key == "workflow_custom_instruction_path")
    assert loaded.status == "preserved"

    instructions.write_bytes(b"replacement bytes\n")
    _, changed_preview = resolve_portable_launch_context(source, "agy")
    changed = next(item for item in changed_preview if item.key == "workflow_custom_instruction_path")
    assert changed.status == "conflicting"
    assert "changed" in changed.reason

    instructions.unlink()
    _, missing_preview = resolve_portable_launch_context(source, "agy")
    missing = next(item for item in missing_preview if item.key == "workflow_custom_instruction_path")
    assert missing.status == "conflicting"
    assert "missing" in missing.reason


def test_destination_preview_reports_terminal_and_workflow_context_without_wsl_host_path_probe():
    context, preview = resolve_portable_launch_context({
        "provider": "agy",
        "repositories": [{"root": "/home/agent/repo", "worktree": "/home/agent/repo", "branch": "observed"}],
        "working_directory": "/home/agent/repo",
        "explicit_directory_override": "/home/agent/repo",
        "runtime_identity": {"runtime_kind": "wsl", "distro": "Ubuntu", "environment_id": "wsl-ubuntu"},
        "workflow_type": "implementation",
        "logical_agent_identity": "slot-1:Builder",
        "terminal_settings": {"no_alt_screen": True},
        "workflow_resource_snapshot": {
            "schema_version": 1, "selection": "implementation", "resources": [],
        },
    }, "codex", capabilities=VERIFIED_CAPABILITIES,
        destination_runtime={"runtime_kind": "wsl", "distro": "Ubuntu", "environment_id": "wsl-ubuntu"})

    statuses = {item.key: item.status for item in preview}
    assert context.working_directory == "/home/agent/repo"
    assert statuses["working_directory"] == "preserved"
    assert statuses["explicit_directory_override"] == "preserved"
    assert statuses["terminal:no_alt_screen"] == "preserved"
    assert statuses["workflow_resource_snapshot"] == "restored"


def test_wsl_worktree_path_is_not_host_probed_and_runtime_mismatch_is_conflicting(tmp_path):
    missing = tmp_path / "deleted-worktree"
    context, preview = resolve_portable_launch_context({
        "provider": "agy",
        "repositories": [{"worktree": str(missing)}],
        "runtime_identity": {"runtime_kind": "wsl", "distro": "Ubuntu"},
    }, "codex", destination_runtime={"runtime_kind": "windows", "distro": None})
    assert context.repositories[0]["worktree"] == str(missing)
    statuses = {item.key: item.status for item in preview}
    assert statuses["repository"] == "preserved"
    assert statuses["runtime_identity"] == "conflicting"


def test_permission_broadening_is_conflicting_and_unknown_capabilities_are_unsupported():
    _, preview = resolve_portable_launch_context({
        "provider": "codex",
        "semantic_settings": {"filesystem": "read-only", "network": "restricted"},
        "destination_filesystem": "full-access",
    }, "claude", capabilities={"claude": {"filesystem"}})
    assert {item.key: item.status for item in preview} == {
        "filesystem": "conflicting", "network": "unsupported",
    }


def test_codex_danger_full_access_is_ranked_as_broader_than_workspace_write():
    _, preview = resolve_portable_launch_context({
        "provider": "agy",
        "semantic_settings": {"filesystem": "workspace-write"},
        "destination_filesystem": "danger-full-access",
    }, "codex", capabilities=VERIFIED_CAPABILITIES)

    assert {item.key: item.status for item in preview}["filesystem"] == "conflicting"


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
    assert provider_settings_argv("codex", {"search": True}).count("--search") == 1
    assert provider_settings_argv("agy", {"model": "m", "reasoning_effort": "high"})[0] == "--settings"
    assert provider_settings_argv("claude", {"model": "m", "effort": "high"}) == [
        "--model", "m", "--effort", "high",
    ]
