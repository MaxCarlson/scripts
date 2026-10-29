"""Offline contracts for durable task checkpoints and recovery packets."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from local_agent_bridge.context.checkpoint import (
    CheckpointError,
    load_checkpoint,
    recovery_packet,
    save_checkpoint,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "offline@example.invalid")
    _git(root, "config", "user.name", "Offline Test")
    source = root / "src" / "worker.py"
    source.parent.mkdir()
    source.write_text("def run():\n    return 1\n", encoding="utf-8")
    _git(root, "add", "src/worker.py")
    _git(root, "commit", "-qm", "baseline")
    return root


def test_save_and_load_are_project_scoped_and_outside_source_tree(project, tmp_path):
    state = tmp_path / "private-state"
    before = sorted(path.relative_to(project).as_posix() for path in project.rglob("*") if path.is_file())
    saved = save_checkpoint(
        project,
        "task-7",
        "Implement a bounded worker change",
        state_dir=state,
        authorized_scope=["src/worker.py"],
        next_action="Inspect worker.run and add the missing branch.",
        identities={"session_id": "ses-1", "job_id": "job-1", "message_id": "msg-1",
                    "provider_id": "lmstudio", "model_id": "qwen-coder", "worker_agent": "local-worker"},
        confirmed_sources=[{"path": "src/worker.py", "start_line": 1, "end_line": 2}],
        decisions=["Keep the public return shape unchanged."],
        modified_paths=["src/worker.py"],
        completed_verification=["Focused test passed."],
        pending_checks=["Run the module suite."],
        blockers=["None."],
    )
    loaded = load_checkpoint(project, "task-7", state_dir=state)
    assert loaded == saved
    assert saved["schema_version"] == 1
    assert saved["base_revision"]
    assert saved["identities"]["job_id"] == "job-1"
    assert saved["confirmed_sources"][0]["sha256"]
    assert not Path(saved["checkpoint_path"]).is_relative_to(project)
    after = sorted(path.relative_to(project).as_posix() for path in project.rglob("*") if path.is_file())
    assert before == after
    serialized = Path(saved["checkpoint_path"]).read_text(encoding="utf-8")
    assert "return 1" not in serialized
    assert not list(Path(saved["checkpoint_path"]).parent.glob("*.tmp"))


def test_recovery_packet_preserves_identity_and_never_resubmits(project, tmp_path):
    state = tmp_path / "state"
    checkpoint = save_checkpoint(
        project,
        "task-identity",
        "Finish worker changes",
        state_dir=state,
        authorized_scope=["src/worker.py"],
        next_action="Check the existing session for the initiating message.",
        identities={"session_id": "ses-x", "job_id": "job-x", "message_id": "msg-x",
                    "directory": str(project), "provider_id": "local", "model_id": "model-x",
                    "worker_agent": "local-reviewer"},
        confirmed_sources=[{"path": "src/worker.py", "start_line": 1, "end_line": 1}],
    )
    packet = recovery_packet(project, checkpoint)
    assert packet["task_id"] == "task-identity"
    assert packet["identities"] == checkpoint["identities"]
    assert packet["source_evidence"][0]["status"] == "current"
    assert packet["automatic_resubmission"] is False
    assert packet["recovery_rules"][0].startswith("Do not submit a duplicate job")


def test_changed_source_invalidates_confirmed_evidence(project, tmp_path):
    state = tmp_path / "state"
    checkpoint = save_checkpoint(
        project,
        "task-stale-source",
        "Update worker source",
        state_dir=state,
        authorized_scope=["src/worker.py"],
        next_action="Review the new implementation.",
        confirmed_sources=[{"path": "src/worker.py", "start_line": 1, "end_line": 2}],
    )
    (project / "src/worker.py").write_text("def run():\n    return 2\n", encoding="utf-8")
    packet = recovery_packet(project, checkpoint)
    assert packet["status"] == "stale"
    assert packet["source_evidence"][0]["status"] == "stale"


def test_changed_revision_marks_checkpoint_stale_even_when_source_is_unchanged(project, tmp_path):
    state = tmp_path / "state"
    checkpoint = save_checkpoint(
        project, "task-stale-revision", "Inspect the source", state_dir=state,
        authorized_scope=["src/worker.py"], next_action="Review current repository state.",
        confirmed_sources=[{"path": "src/worker.py", "start_line": 1, "end_line": 1}],
    )
    (project / "README.md").write_text("Unrelated change\n", encoding="utf-8")
    _git(project, "add", "README.md")
    _git(project, "commit", "-qm", "advance revision")
    packet = recovery_packet(project, checkpoint)
    assert packet["status"] == "stale"
    assert "base_revision_changed" in packet["stale_reasons"]
    assert packet["source_evidence"][0]["status"] == "current"


@pytest.mark.parametrize("path", ["../outside.py", "C:\\outside.py", "/outside.py"])
def test_confirmed_source_paths_must_be_relative_to_workspace(project, tmp_path, path):
    with pytest.raises(CheckpointError, match="relative workspace path"):
        save_checkpoint(
            project, "task-bad-path", "No traversal", state_dir=tmp_path / "state",
            authorized_scope=[], next_action="Stop.", confirmed_sources=[{"path": path}],
        )


def test_symlink_source_escape_is_rejected(project, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("secret\n", encoding="utf-8")
    link = project / "escape.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    with pytest.raises(CheckpointError, match="escapes the workspace"):
        save_checkpoint(
            project, "task-symlink", "Do not capture outside refs", state_dir=tmp_path / "state",
            authorized_scope=[], next_action="Stop.", confirmed_sources=[{"path": "escape.py"}],
        )


def test_workspace_mismatch_and_invalid_checkpoint_are_explicit(project, tmp_path):
    state = tmp_path / "state"
    saved = save_checkpoint(project, "task-mismatch", "Task", state_dir=state,
                            authorized_scope=[], next_action="Inspect safely.")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(CheckpointError, match="No checkpoint found"):
        load_checkpoint(elsewhere, "task-mismatch", state_dir=state)
    checkpoint_path = Path(saved["checkpoint_path"])
    checkpoint_path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    with pytest.raises(CheckpointError, match="Unsupported checkpoint schema"):
        load_checkpoint(project, "task-mismatch", state_dir=state)


def test_state_directory_must_be_outside_git_worktree(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-q")
    nested_workspace = project / "packages" / "worker"
    nested_workspace.mkdir(parents=True)
    with pytest.raises(CheckpointError, match="outside the working tree"):
        save_checkpoint(
            nested_workspace,
            "task-inside-worktree",
            "Keep checkpoint data external",
            state_dir=project / "state",
            authorized_scope=[],
            next_action="Continue outside the tree.",
        )


def test_unavailable_base_revision_is_reported_as_uncertain(project, tmp_path, monkeypatch):
    from local_agent_bridge.context import checkpoint as checkpoint_module

    checkpoint = save_checkpoint(
        project, "task-revision-unknown", "Inspect safely", state_dir=tmp_path / "state",
        authorized_scope=[], next_action="Recheck the repository state.",
    )
    monkeypatch.setattr(checkpoint_module, "_revision", lambda _root: None)
    packet = recovery_packet(project, checkpoint)
    assert packet["status"] == "stale"
    assert "base_revision_unavailable" in packet["stale_reasons"]


def test_recover_session_selects_latest_matching_checkpoint_and_revalidates_sources(project, tmp_path):
    from local_agent_bridge.context.checkpoint import recover_session

    first = save_checkpoint(
        project, "task-old", "Old task", state_dir=tmp_path / "state", authorized_scope=[],
        next_action="Old next step.", identities={"session_id": "ses-shared"},
    )
    latest = save_checkpoint(
        project, "task-latest", "Latest task", state_dir=tmp_path / "state", authorized_scope=[],
        next_action="Inspect the latest confirmed state.", identities={"session_id": "ses-shared"},
        confirmed_sources=[{"path": "src/worker.py", "start_line": 1, "end_line": 2}],
    )
    assert first["task_id"] != latest["task_id"]
    (project / "src/worker.py").write_text("def run():\n    return 9\n", encoding="utf-8")
    packet = recover_session(project, "ses-shared", state_dir=tmp_path / "state")
    assert packet["task_id"] == "task-latest"
    assert packet["next_action"] == "Inspect the latest confirmed state."
    assert packet["status"] == "stale"
    assert packet["automatic_resubmission"] is False


def test_recover_session_without_matching_identity_is_explicit(project, tmp_path):
    from local_agent_bridge.context.checkpoint import recover_session

    packet = recover_session(project, "ses-unknown", state_dir=tmp_path / "state")
    assert packet["status"] == "missing"
    assert packet["automatic_resubmission"] is False
