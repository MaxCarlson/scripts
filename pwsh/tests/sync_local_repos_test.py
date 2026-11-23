from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "Sync-LocalRepos.ps1"


def _pwsh_exe() -> str:
    exe = shutil.which("pwsh")
    if not exe:
        pytest.skip("pwsh (PowerShell 7) is not available")
    return exe


def _git(cwd: Path, *args: str) -> str:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "Test User")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "Test User")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@example.com")
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return proc.stdout.strip()


def _init_repo_with_remote(base: Path, name: str) -> tuple[Path, Path]:
    bare = base / f"{name}.git"
    bare.mkdir(parents=True)
    _git(bare, "init", "--bare", "--initial-branch=main")

    seed = base / f"{name}-seed"
    subprocess.run(["git", "clone", str(bare), str(seed)], check=True, capture_output=True, text=True)
    _git(seed, "checkout", "-B", "main")
    (seed / "README.md").write_text("initial\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "initial")
    _git(seed, "push", "-u", "origin", "main")

    local = base / "repos" / name
    local.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", str(bare), str(local)], check=True, capture_output=True, text=True)
    _git(local, "checkout", "main")
    return local, seed


def _push_remote_commit(seed: Path, filename: str, content: str, msg: str) -> str:
    (seed / filename).write_text(content, encoding="utf-8")
    _git(seed, "add", filename)
    _git(seed, "commit", "-m", msg)
    _git(seed, "push", "origin", "main")
    return _git(seed, "rev-parse", "HEAD")


def _run_sync(root: Path, repos: list[str], *extra_args: str) -> tuple[int, dict]:
    cmd = [
        _pwsh_exe(),
        "-NoProfile",
        "-File",
        str(SCRIPT_PATH),
        "-r",
        str(root),
        "-p",
        ",".join(repos),
        "-j",
        *extra_args,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    payload = json.loads(proc.stdout)
    return proc.returncode, payload


def test_clean_fast_forward_and_already_current_and_dry_run_non_mutating(tmp_path: Path) -> None:
    local, seed = _init_repo_with_remote(tmp_path, "repo-a")
    head_before = _git(local, "rev-parse", "HEAD")
    new_remote_head = _push_remote_commit(seed, "next.txt", "v2\n", "remote advance")

    # Dry-run must not fetch or advance HEAD
    rc_dry, dry = _run_sync(tmp_path / "repos", ["repo-a"])
    assert rc_dry == 0
    assert dry["mode"] == "dry-run"
    assert _git(local, "rev-parse", "HEAD") == head_before
    assert _git(local, "rev-parse", "origin/main") == head_before

    # Apply fast-forwards cleanly
    rc_apply, res = _run_sync(tmp_path / "repos", ["repo-a"], "-a")
    assert rc_apply == 0
    assert res["updated"] == 1
    rec = res["repositories"][0]
    assert rec["status"] == "updated"
    assert rec["head_before"] == head_before
    assert rec["head_after"] == new_remote_head
    assert _git(local, "rev-parse", "HEAD") == new_remote_head

    # Second apply is already_current
    rc_cur, cur = _run_sync(tmp_path / "repos", ["repo-a"], "-a")
    assert rc_cur == 0
    assert cur["already_current"] == 1
    assert cur["repositories"][0]["status"] == "already_current"


def test_dirty_compatible_and_incompatible_and_untracked_collision(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repos"

    # 1. Dirty-but-compatible fast-forward (modified README.md + untracked scratch.txt, remote adds r.txt)
    compat, seed1 = _init_repo_with_remote(tmp_path, "dirty-compat")
    _git(compat, "fetch", "origin")
    remote_head_1 = _push_remote_commit(seed1, "r.txt", "r\n", "remote adds r.txt")
    (compat / "README.md").write_text("local edit\n", encoding="utf-8")
    (compat / "scratch.txt").write_text("keep me\n", encoding="utf-8")

    # Dry-run distinguishes dirty-pending-git-check when behind locally
    _git(compat, "fetch", "origin")
    rc_dry, dry = _run_sync(repos_dir, ["dirty-compat"])
    assert rc_dry == 0
    assert dry["repositories"][0]["status"] == "would_fast_forward_with_local_changes"

    # Apply succeeds and preserves local tracked + untracked changes
    rc_compat, res_compat = _run_sync(repos_dir, ["dirty-compat"], "-a")
    assert rc_compat == 0
    rec = res_compat["repositories"][0]
    assert rec["status"] == "updated"
    assert rec["head_after"] == remote_head_1
    assert (compat / "README.md").read_text(encoding="utf-8") == "local edit\n"
    assert (compat / "scratch.txt").read_text(encoding="utf-8") == "keep me\n"
    assert len(rec["remaining_changes"]) == 2

    # 2. Untracked-file collision (untracked r.txt collides with remote r.txt)
    collision, seed2 = _init_repo_with_remote(tmp_path, "untracked-collision")
    head_col_before = _git(collision, "rev-parse", "HEAD")
    _push_remote_commit(seed2, "r.txt", "remote\n", "remote adds r.txt")
    (collision / "r.txt").write_text("local untracked\n", encoding="utf-8")

    rc_col, res_col = _run_sync(repos_dir, ["untracked-collision"], "-a")
    assert rc_col == 0
    assert res_col["repositories"][0]["status"] == "skipped"
    assert res_col["repositories"][0]["reason"] == "ff_blocked_by_local_changes"
    assert _git(collision, "rev-parse", "HEAD") == head_col_before
    assert (collision / "r.txt").read_text(encoding="utf-8") == "local untracked\n"

    # 3. Incompatible tracked changes (modified README.md collides with remote README.md)
    incompat, seed3 = _init_repo_with_remote(tmp_path, "incompat-tracked")
    head_inc_before = _git(incompat, "rev-parse", "HEAD")
    _push_remote_commit(seed3, "README.md", "remote overwrite\n", "remote edits README")
    (incompat / "README.md").write_text("local edit\n", encoding="utf-8")

    rc_inc, res_inc = _run_sync(repos_dir, ["incompat-tracked"], "-a")
    assert rc_inc == 0
    assert res_inc["repositories"][0]["status"] == "skipped"
    assert res_inc["repositories"][0]["reason"] == "ff_blocked_by_local_changes"
    assert _git(incompat, "rev-parse", "HEAD") == head_inc_before
    assert (incompat / "README.md").read_text(encoding="utf-8") == "local edit\n"


def test_ahead_diverged_detached_missing_remote_and_invalid(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repos"

    ahead, _seed1 = _init_repo_with_remote(tmp_path, "ahead")
    (ahead / "local.txt").write_text("ahead\n", encoding="utf-8")
    _git(ahead, "add", "local.txt")
    _git(ahead, "commit", "-m", "local ahead")

    diverged, seed2 = _init_repo_with_remote(tmp_path, "diverged")
    _push_remote_commit(seed2, "r.txt", "r\n", "remote")
    (diverged / "l.txt").write_text("l\n", encoding="utf-8")
    _git(diverged, "add", "l.txt")
    _git(diverged, "commit", "-m", "local diverge")

    detached, _seed3 = _init_repo_with_remote(tmp_path, "detached")
    _git(detached, "checkout", "--detach", "HEAD")

    no_remote = repos_dir / "no-remote"
    no_remote.mkdir(parents=True)
    _git(no_remote, "init", "--initial-branch=main")
    (no_remote / "a.txt").write_text("a\n", encoding="utf-8")
    _git(no_remote, "add", "a.txt")
    _git(no_remote, "commit", "-m", "init")

    # Outside any git repo so it's truly not a git repo
    outside_not_repo = tmp_path / "plain-dir"
    outside_not_repo.mkdir(parents=True)

    rc, res = _run_sync(
        repos_dir,
        ["ahead", "diverged", "detached", "no-remote", str(outside_not_repo)],
        "-a",
    )
    assert rc == 1
    by_name = {r["name"]: r for r in res["repositories"]}
    assert by_name["ahead"]["status"] == "skipped"
    assert by_name["ahead"]["reason"] == "local_commits_ahead"
    assert by_name["diverged"]["status"] == "skipped"
    assert by_name["diverged"]["reason"] == "diverged_histories"
    assert by_name["detached"]["status"] == "skipped"
    assert by_name["detached"]["reason"] == "detached_head"
    assert by_name["no-remote"]["status"] == "failed"
    assert by_name["no-remote"]["reason"] == "missing_remote"
    assert by_name["plain-dir"]["status"] == "failed"
    assert by_name["plain-dir"]["reason"] in ("invalid_git_repository", "not_repository_root")


def test_submodule_dirty_fast_forward_preserves_pin_and_untracked_content(tmp_path: Path) -> None:
    sub_bare = tmp_path / "sub.git"
    sub_bare.mkdir()
    _git(sub_bare, "init", "--bare", "--initial-branch=main")
    sub_seed = tmp_path / "sub-seed"
    subprocess.run(["git", "clone", str(sub_bare), str(sub_seed)], check=True, capture_output=True, text=True)
    _git(sub_seed, "checkout", "-B", "main")
    (sub_seed / "sub.txt").write_text("s1\n", encoding="utf-8")
    _git(sub_seed, "add", "sub.txt")
    _git(sub_seed, "commit", "-m", "sub init")
    _git(sub_seed, "push", "-u", "origin", "main")

    parent, seed = _init_repo_with_remote(tmp_path, "parent")
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "-C", str(seed), "submodule", "add", str(sub_bare), "sub"],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(seed, "commit", "-m", "add submodule")
    _git(seed, "push", "origin", "main")

    _git(parent, "pull", "--ff-only")
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "-C", str(parent), "submodule", "update", "--init"],
        check=True,
        capture_output=True,
        text=True,
    )
    new_parent_head = _push_remote_commit(seed, "parent2.txt", "p2\n", "parent advance")

    # Dirty submodule (untracked content inside sub) does NOT block compatible parent fast-forward
    (parent / "sub" / "dirty.txt").write_text("keep submodule untracked\n", encoding="utf-8")
    sub_head_before = _git(parent / "sub", "rev-parse", "HEAD")

    rc, res = _run_sync(tmp_path / "repos", ["parent"], "-a")
    assert rc == 0
    rec = res["repositories"][0]
    assert rec["status"] == "updated"
    assert rec["head_after"] == new_parent_head
    assert rec["submodule_changes"] == ["sub"]
    assert _git(parent / "sub", "rev-parse", "HEAD") == sub_head_before
    assert (parent / "sub" / "dirty.txt").read_text(encoding="utf-8") == "keep submodule untracked\n"
