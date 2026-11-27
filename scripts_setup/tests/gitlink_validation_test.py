from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts_setup.gitlink_validation import GitlinkValidationError, verify_gitlink


@pytest.fixture
def repositories(tmp_path: Path) -> tuple[Path, Path, str]:
    child = tmp_path / "child"
    parent = tmp_path / "parent"
    child.mkdir()
    parent.mkdir()
    _git(child, "init", "--quiet")
    _git(child, "config", "user.name", "Gitlink Test")
    _git(child, "config", "user.email", "gitlink-test@example.invalid")
    (child / "revision.txt").write_text("expected\n", encoding="utf-8")
    _git(child, "add", "revision.txt")
    _git(child, "commit", "--quiet", "-m", "expected submodule revision")
    expected = _git(child, "rev-parse", "HEAD").strip()

    _git(parent, "init", "--quiet")
    _git(parent, "config", "user.name", "Gitlink Test")
    _git(parent, "config", "user.email", "gitlink-test@example.invalid")
    _git(parent, "update-index", "--add", "--cacheinfo", f"160000,{expected},pscripts")
    _git(parent, "commit", "--quiet", "-m", "record pscripts gitlink")
    return parent, child, expected


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


@pytest.mark.parametrize(
    "path_in_parent", ["pscripts", "modules/aebn-vod-downloader-custom"]
)
def test_gitlink_accepts_the_commit_recorded_in_parent_tree(
    repositories: tuple[Path, Path, str], path_in_parent: str
) -> None:
    parent, checkout, expected = repositories
    if path_in_parent != "pscripts":
        _git(parent, "update-index", "--force-remove", "pscripts")
        _git(
            parent,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{expected},{path_in_parent}",
        )
        _git(parent, "commit", "--quiet", "-m", "record nested gitlink")

    assert verify_gitlink(parent, path_in_parent, checkout) == expected


def test_gitlink_rejects_a_mismatched_checkout(
    repositories: tuple[Path, Path, str],
) -> None:
    parent, checkout, _expected = repositories
    (checkout / "revision.txt").write_text("stale\n", encoding="utf-8")
    _git(checkout, "commit", "--quiet", "-am", "stale checkout")

    with pytest.raises(GitlinkValidationError, match="does not match parent Gitlink"):
        verify_gitlink(parent, "pscripts", checkout)


def test_gitlink_validation_fails_closed_when_parent_has_no_gitlink(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent"
    checkout = tmp_path / "checkout"
    parent.mkdir()
    checkout.mkdir()
    _git(parent, "init", "--quiet")
    _git(parent, "config", "user.name", "Gitlink Test")
    _git(parent, "config", "user.email", "gitlink-test@example.invalid")
    _git(parent, "commit", "--quiet", "--allow-empty", "-m", "no submodule")
    _git(checkout, "init", "--quiet")
    _git(checkout, "config", "user.name", "Gitlink Test")
    _git(checkout, "config", "user.email", "gitlink-test@example.invalid")
    (checkout / "revision.txt").write_text("present\n", encoding="utf-8")
    _git(checkout, "add", "revision.txt")
    _git(checkout, "commit", "--quiet", "-m", "checkout")

    with pytest.raises(GitlinkValidationError, match="does not record a Gitlink"):
        verify_gitlink(parent, "pscripts", checkout)
