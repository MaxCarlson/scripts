#!/usr/bin/env python3
import sys
import os
from pathlib import Path
import pytest

# ensure project root (where check_pytests.py lives) is on the import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from check_pytests import strip_test_affixes, collect_py_files

@pytest.mark.parametrize("input_name, expected", [
    ("test_foo",      "foo"),
    ("foo_test",      "foo"),
    ("foo_tests",     "foo"),
    ("already_good",  "already_good"),
])
def test_strip_test_affixes_various(input_name, expected):
    assert strip_test_affixes(input_name) == expected

@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    # root‐level files
    (root / "a.py").write_text("print('a')")
    (root / "__init__.py").write_text("")           # should be ignored
    # __pycache__ should be ignored
    pc = root / "__pycache__"
    pc.mkdir()
    (pc / "ignored.py").write_text("print('x')")
    # subfolders
    s1 = root / "sub1"; s1.mkdir()
    (s1 / "c.py").write_text("print('c')")
    (s1 / "d.txt").write_text("nope")
    s2 = root / "sub2"; s2.mkdir()
    (s2 / "e.py").write_text("print('e')")
    return root

def test_collect_py_files_depth_zero(sample_dir):
    files = collect_py_files(sample_dir, max_depth=0, exclude_abs=set())
    rels = {p.relative_to(sample_dir) for p in files}
    assert rels == {Path("a.py")}

def test_collect_py_files_depth_one(sample_dir):
    files = collect_py_files(sample_dir, max_depth=1, exclude_abs=set())
    rels = {p.relative_to(sample_dir) for p in files}
    assert rels == {
        Path("a.py"),
        Path("sub1/c.py"),
        Path("sub2/e.py"),
    }

def test_collect_py_files_exclude(sample_dir):
    # exclude sub1 entirely
    exclude = {sample_dir / "sub1"}
    files = collect_py_files(sample_dir, max_depth=-1, exclude_abs=exclude)
    rels = {p.relative_to(sample_dir) for p in files}
    assert Path("sub1/c.py") not in rels
    assert Path("sub2/e.py") in rels
    assert Path("a.py") in rels

