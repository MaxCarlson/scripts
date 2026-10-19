"""Trial-local Git identity and source/metadata separation, offline only."""

from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from agent_benchmark.evidence import audit_scope, capture, changed_paths, load_task, prepare_workspace

TASK = Path(__file__).resolve().parents[1] / "agent_benchmark/tasks/py-grep-smoke"


def git(workspace, *args):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    return subprocess.run(["git", "-C", str(workspace), *args], check=True,
                          capture_output=True, text=True, env=env, timeout=10).stdout.strip()


def test_identical_task_bytes_have_distinct_committed_trial_projects(tmp_path):
    one, two = tmp_path / "one/trial", tmp_path / "two/trial"
    a = prepare_workspace(load_task(TASK), one)
    b = prepare_workspace(load_task(TASK), two)
    assert a.root_commit == git(one, "rev-parse", "HEAD")
    assert b.root_commit == git(two, "rev-parse", "HEAD")
    assert a.root_commit != b.root_commit and a.trial_id != b.trial_id
    assert len(a.root_commit) == 40
    assert git(one, "rev-list", "--max-parents=0", "HEAD") == a.root_commit
    assert git(one, "remote") == git(two, "remote") == ""
    assert capture(one, tmp_path / "S0a").tree_hash == capture(two, tmp_path / "S0b").tree_hash
    assert (one / "grep.py").read_bytes() == (TASK / "seed/grep.py").read_bytes()


def test_preparation_stops_ancestor_discovery_and_ignores_inherited_git_environment(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    prepare_workspace(load_task(TASK), parent)
    before = git(parent, "rev-parse", "HEAD")
    monkeypatch.setenv("GIT_DIR", str(parent / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(parent))
    trial = parent / "nested/trial"
    identity = prepare_workspace(load_task(TASK), trial)
    assert Path(git(trial, "rev-parse", "--show-toplevel")).resolve() == trial.resolve()
    assert identity.root_commit != before
    assert git(parent, "rev-parse", "HEAD") == before


def test_empty_repository_has_no_root_until_benchmark_preparation(tmp_path):
    unborn = tmp_path / "unborn"
    unborn.mkdir()
    git(unborn, "init", "--template=")
    result = subprocess.run(["git", "-C", str(unborn), "rev-list", "--max-parents=0", "HEAD"], capture_output=True)
    assert result.returncode != 0
    with pytest.raises(ValueError, match="fresh"):
        prepare_workspace(load_task(TASK), unborn)
    workspace = tmp_path / "prepared"
    identity = prepare_workspace(load_task(TASK), workspace)
    assert git(workspace, "rev-list", "--count", "HEAD") == "1"
    assert git(workspace, "rev-parse", "HEAD") == identity.root_commit


def test_git_bookkeeping_is_excluded_but_worker_git_mutations_are_violations(tmp_path):
    task = load_task(TASK)
    workspace = tmp_path / "worker"
    prepare_workspace(task, workspace)
    s0 = capture(workspace, tmp_path / "S0")
    (workspace / ".git/index").write_bytes(b"modified index")
    s1 = capture(workspace, tmp_path / "S1")
    assert changed_paths(s0, s1) == []
    assert not (s1.path / ".git").exists()
    history = [{"info": {"id": "assistant-1"}, "parts": [{
        "type": "tool", "tool": "write", "callID": "write-index",
        "state": {"status": "completed", "input": {"filePath": ".git/index"}},
    }]}]
    # Even an erroneous task allowlist cannot grant worker control of internal Git state.
    audit = audit_scope(replace(task, allowed_paths=(".git/index",)), workspace, s0, s1, history)
    assert audit.transcript_violations == (".git/index",)
    assert audit.compliance == "violated"


def test_nested_git_named_files_and_archive_tampering_are_not_hidden(tmp_path):
    workspace = tmp_path / "worker"
    prepare_workspace(load_task(TASK), workspace)
    (workspace / "nested/.git").mkdir(parents=True)
    (workspace / "nested/.git/payload").write_text("worker change")
    s1 = capture(workspace, tmp_path / "S1")
    assert "nested/.git/payload" in s1.files
    (s1.path / ".git").mkdir()
    (s1.path / ".git/payload").write_text("archive tampering")
    with pytest.raises(ValueError, match="changed"):
        s1.check_intact()


def test_seed_cannot_supply_git_metadata(tmp_path):
    task_dir = tmp_path / "fixture"
    shutil.copytree(TASK, task_dir)
    (task_dir / "seed/.git").mkdir()
    (task_dir / "seed/.git/config").write_text("seed-controlled git configuration")
    with pytest.raises(ValueError, match="reserved"):
        prepare_workspace(load_task(task_dir), tmp_path / "worker")



def test_initializer_does_not_load_or_change_inherited_git_config(tmp_path, monkeypatch):
    config = tmp_path / "user.gitconfig"
    original = b"[commit]\n gpgSign = true\n[core]\n bare = true\n"
    config.write_bytes(original)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    identity = prepare_workspace(load_task(TASK), tmp_path / "worker")
    assert git(tmp_path / "worker", "rev-parse", "HEAD") == identity.root_commit
    assert config.read_bytes() == original
