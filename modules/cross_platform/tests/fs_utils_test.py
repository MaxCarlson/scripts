# File: scripts/modules/cross_platform/tests/fs_utils_test.py
import sys
from pathlib import Path
import pytest

from cross_platform.fs_utils import (
    normalize_ext,
    matches_ext,
    iter_dirs,
    find_files_by_extension,
    delete_files,
    aggregate_counts_by_parent,
    dir_summary_lines,
    relpath_str,
    safe_relative_to,
    FsSearchResult,
)

def test_normalize_ext_basic():
    assert normalize_ext("jpg") == "jpg"
    assert normalize_ext(".jpg") == "jpg"
    with pytest.raises(ValueError):
        normalize_ext("   ")

def test_matches_ext_insensitive_and_sensitive():
    P = Path
    assert matches_ext(P("a.jpg"), "jpg", case_sensitive=False)
    assert matches_ext(P("b.JPG"), "jpg", case_sensitive=False)
    assert not matches_ext(P("c.jpeg"), "jpg", case_sensitive=False)
    assert matches_ext(P("X.JPG"), "JPG", case_sensitive=True)
    assert not matches_ext(P("X.JPG"), "jpg", case_sensitive=True)

def test_iter_dirs_excludes_and_depth(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "lvl1").mkdir()
    (tmp_path / "lvl1" / "lvl2").mkdir()
    seen = list(iter_dirs(tmp_path, exclude_dir_globs=[".git"], max_depth=1))
    # Should include root and lvl1, but not lvl2
    assert tmp_path in seen
    assert (tmp_path / "lvl1") in seen
    assert (tmp_path / "lvl1" / "lvl2") not in seen

def test_find_files_by_extension_and_counts(tmp_path: Path):
    (tmp_path / "A").mkdir()
    (tmp_path / "B").mkdir()
    (tmp_path / "A" / "one.jpg").write_text("x")
    (tmp_path / "A" / "two.JPG").write_text("x")
    (tmp_path / "B" / "nope.txt").write_text("x")
    (tmp_path / "B" / "yep.jpg").write_text("x")

    res = find_files_by_extension(tmp_path, "jpg")
    assert isinstance(res, FsSearchResult)
    names = sorted(p.name for p in res.matched_files)
    assert names == ["one.jpg", "two.JPG", "yep.jpg"]

    counts = aggregate_counts_by_parent(res.matched_files)
    assert counts[tmp_path / "A"] == 2
    assert counts[tmp_path / "B"] == 1

def test_dir_summary_lines_never_raises_relative_to(tmp_path: Path):
    # Reproduce the crash scenario: use a *relative* root when matched parents are absolute.
    # We'll pass root as relative "stars" while files live under an absolute tmp dir /stars/...
    stars = tmp_path / "stars"
    (stars / "sub").mkdir(parents=True)
    f1 = stars / "sub" / "a.jpg"
    f2 = stars / "sub" / "b.jpg"
    f1.write_text("x"); f2.write_text("x")

    counts = {f1.parent: 2}
    # Make root appear as a relative name (like 'stars') to simulate your CLI usage.
    relative_root = Path("stars")  # not resolved on purpose

    # This should not raise ValueError and should include the folder name
    lines = dir_summary_lines(relative_root, counts, top_n=10, show_all=True, absolute_paths=False)
    joined = "\n".join(lines)
    assert "📁 Folders with matches" in joined
    assert "sub" in joined  # the displayed path should include 'sub'

def test_relpath_str_absolute_toggle(tmp_path: Path):
    A = tmp_path / "A"
    B = tmp_path / "A" / "B"
    B.mkdir(parents=True)
    assert relpath_str(B, A, absolute_paths=False) == "B"
    assert relpath_str(B, A, absolute_paths=True).endswith(str(B.name))

def test_safe_relative_to_falls_back_outside_root(tmp_path: Path):
    A = tmp_path / "A"; C = tmp_path / "C"
    A.mkdir(); C.mkdir()
    out = safe_relative_to(C, A)
    # Since C is not inside A, we expect an absolute path string
    assert isinstance(out, str)
    assert out == str(C.resolve())

def test_delete_files_ok_and_non_files(tmp_path: Path):
    f = tmp_path / "to_delete.txt"
    d = tmp_path / "dir"
    f.write_text("x")
    d.mkdir()
    errs = delete_files([f, d])
    assert errs == []
    assert not f.exists()
    assert d.exists()
