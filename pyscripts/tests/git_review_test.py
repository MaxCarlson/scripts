# File: tests/git_review_test.py
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _have_git() -> bool:
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(
    not _have_git(), reason="git is required for these tests"
)


def _import_mod():
    """
    Import the module whether it's placed at 'scripts/git_review.py' or
    at repo root as 'git_review.py'. This keeps tests resilient to layout.
    """
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        import scripts.git_review as mod  # type: ignore

        return mod
    except Exception:
        import importlib.util

        p = root / "git_review.py"
        spec = importlib.util.spec_from_file_location("git_review", str(p))
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["git_review"] = mod
            spec.loader.exec_module(mod)  # type: ignore
            return mod
        raise


def _git(cwd: Path, *args: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), text=True, capture_output=True, env=env
    )


@pytest.fixture()
def repo(tmp_path: Path):
    """Create a tiny repo with a rename and an added file."""
    cwd = tmp_path

    # Init
    r = _git(cwd, "init", "-b", "main")
    assert r.returncode == 0, r.stderr

    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Max",
            "GIT_AUTHOR_EMAIL": "max@example.com",
            "GIT_COMMITTER_NAME": "Max",
            "GIT_COMMITTER_EMAIL": "max@example.com",
        }
    )

    def g(*a):
        return _git(cwd, *a, env=env)

    # 1) add foo.txt = "one\n"
    (cwd / "foo.txt").write_text("one\n", encoding="utf-8")
    assert g("add", "foo.txt").returncode == 0
    assert g("commit", "-m", "add foo=one").returncode == 0

    # 2) rename foo.txt -> bar.txt (no content change)
    assert g("mv", "foo.txt", "bar.txt").returncode == 0
    assert g("commit", "-m", "rename foo->bar").returncode == 0

    # 3) modify bar.txt -> "two\n"
    (cwd / "bar.txt").write_text("two\n", encoding="utf-8")
    assert g("add", "bar.txt").returncode == 0
    assert g("commit", "-m", "chg bar=two").returncode == 0

    # 4) add b.txt
    (cwd / "b.txt").write_text("bee\n", encoding="utf-8")
    assert g("add", "b.txt").returncode == 0
    assert g("commit", "-m", "add b=bee").returncode == 0

    return cwd


def test_show_contents_basic(repo: Path):
    mod = _import_mod()
    out, per_file = mod.show_file_contents_at_rev(
        "HEAD~1", [Path("bar.txt")], repo_root=repo
    )
    # HEAD~1 is commit #3 where bar.txt = "two"
    assert "===== FILE: bar.txt [" in out
    assert out.strip().endswith("two")
    assert per_file[Path("bar.txt")][1] == "two\n"


def test_show_contents_rename_follow(repo: Path):
    mod = _import_mod()
    # Two commits ago (HEAD~2) is the rename commit; name should still be bar.txt at that commit.
    out, mapping = mod.show_file_contents_at_rev(
        "HEAD~2", [Path("bar.txt")], repo_root=repo
    )
    assert "===== FILE: bar.txt [" in out
    # Three commits ago (HEAD~3) predates the rename; content must be "one" via foo.txt.
    out2, mapping2 = mod.show_file_contents_at_rev(
        "HEAD~3", [Path("bar.txt")], repo_root=repo
    )
    resolved, content = mapping2[Path("bar.txt")]
    assert resolved.endswith("foo.txt")
    assert (content or "").strip() == "one"


def test_diff_specific_commit_with_rename_filter(repo: Path):
    mod = _import_mod()
    # HEAD~2 is the rename commit; filtering by "bar.txt" should still show the rename hunk.
    out = mod.diff_specific_commit("HEAD~2", [Path("bar.txt")], repo_root=repo)
    assert "rename from foo.txt" in out
    assert "rename to bar.txt" in out


def test_diff_since_rev_whole_repo(repo: Path):
    mod = _import_mod()
    out = mod.diff_since_rev("HEAD~3", None, repo_root=repo)
    assert "bar.txt" in out
    assert "b.txt" in out


def test_cli_show_requires_files(repo: Path, capsys):
    mod = _import_mod()
    rc = mod.main(["--show", "-n", "1", "-R", str(repo)])
    assert rc != 0
    captured = capsys.readouterr()
    assert "requires at least one file" in (captured.err or captured.out)


def test_cli_diff_modes(repo: Path):
    mod = _import_mod()
    assert mod.main(["--diff", "-n", "2", "-R", str(repo)]) == 0
    assert mod.main(["--diff", "-n", "2", "--commit", "-R", str(repo)]) == 0


def test_show_write_single_file_to_path(repo: Path, tmp_path: Path):
    mod = _import_mod()
    target = tmp_path / "snap.txt"
    rc = mod.main(["--show", "-n", "3", "-R", str(repo), "-o", str(target), "bar.txt"])
    assert rc == 0
    # At HEAD~3, content was "one\n"
    assert target.read_text(encoding="utf-8") == "one\n"


def test_show_write_multiple_files_to_dir(repo: Path, tmp_path: Path):
    mod = _import_mod()
    # Use -n 0 (HEAD) so both bar.txt and b.txt exist
    rc = mod.main(
        ["--show", "-n", "0", "-R", str(repo), "-o", str(tmp_path), "bar.txt", "b.txt"]
    )
    assert rc == 0
    assert (tmp_path / "HEAD~0" / "bar.txt").exists()
    assert (tmp_path / "HEAD~0" / "b.txt").exists()


def test_clipboard_single_file_raw(monkeypatch, repo: Path):
    mod = _import_mod()

    # Fake clipboard module
    captured = {"text": None}

    class _FakeClipboard:
        @staticmethod
        def set_clipboard(txt: str):
            captured["text"] = txt

    sys.modules["clipboard_utils"] = _FakeClipboard  # type: ignore

    rc = mod.main(["--show", "-n", "3", "-R", str(repo), "-b", "bar.txt"])
    assert rc == 0
    assert (captured["text"] or "").strip() == "one"


def test_clipboard_diff(monkeypatch, repo: Path):
    mod = _import_mod()

    captured = {"text": None}

    class _FakeClipboard:
        @staticmethod
        def set_clipboard(txt: str):
            captured["text"] = txt

    sys.modules["clipboard_utils"] = _FakeClipboard  # type: ignore

    rc = mod.main(["--diff", "-n", "2", "-R", str(repo), "-b"])
    assert rc == 0
    assert captured["text"] and "diff" in captured["text"]


def test_show_asof_deleted_file(tmp_path: Path):
    """
    Verify as-of fallback: file deleted at HEAD but exists earlier;
    --show -n 0 should still print the last version at or before HEAD.
    """
    # Build a small separate repo
    cwd = tmp_path / "r2"
    cwd.mkdir()

    def git(*a, env=None):
        return subprocess.run(
            ["git", *a], cwd=str(cwd), text=True, capture_output=True, env=env
        )

    assert git("init", "-b", "main").returncode == 0

    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Max",
            "GIT_AUTHOR_EMAIL": "max@example.com",
            "GIT_COMMITTER_NAME": "Max",
            "GIT_COMMITTER_EMAIL": "max@example.com",
        }
    )

    def g(*a):
        return git(*a, env=env)

    (cwd / "gone.txt").write_text("first\n", encoding="utf-8")
    assert g("add", "gone.txt").returncode == 0
    assert g("commit", "-m", "add gone").returncode == 0

    # Delete the file
    assert g("rm", "gone.txt").returncode == 0
    assert g("commit", "-m", "delete gone").returncode == 0

    mod = _import_mod()
    out, mapping = mod.show_file_contents_at_rev(
        "HEAD~0", [Path("gone.txt")], repo_root=cwd
    )
    # As-of fallback should surface "first"
    assert out.strip().endswith("first")
