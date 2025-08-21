# file: tests/test_iter_files_compat.py
from pathlib import Path
import video_dedupe as vd

def make_tree(tmp_path: Path):
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    (a / "f1.mp4").write_bytes(b"hello")
    (b / "f2.mp4").write_bytes(b"world")
    (a / "g1.mkv").write_bytes(b"x")
    (b / "g2.txt").write_text("y")
    return tmp_path

def test_backward_compat_single_pattern_kwarg(tmp_path: Path):
    root = make_tree(tmp_path)
    files = {p.name for p in vd.iter_files(root, pattern="*.mp4", max_depth=None)}
    assert files == {"f1.mp4", "f2.mp4"}

def test_patterns_list_and_normalization(tmp_path: Path):
    root = make_tree(tmp_path)
    # Accept ".mp4" and "mkv" forms; normalize to "*.ext"
    files = {p.name for p in vd.iter_files(root, max_depth=None, patterns=[".mp4", "mkv"])}
    assert files == {"f1.mp4", "f2.mp4", "g1.mkv"}

def test_union_pattern_and_patterns(tmp_path: Path):
    root = make_tree(tmp_path)
    files = {p.name for p in vd.iter_files(root, pattern="*.txt", max_depth=None, patterns=[".mp4"])}
    assert files == {"f1.mp4", "f2.mp4", "g2.txt"}

def test_recursion_depth_zero(tmp_path: Path):
    # Put one file at root, one in a subdir; depth 0 should only see root
    root = tmp_path
    (root / "root.mp4").write_bytes(b"z")
    sub = root / "sub"
    sub.mkdir()
    (sub / "deep.mp4").write_bytes(b"z")
    seen = {p.name for p in vd.iter_files(root, pattern="*.mp4", max_depth=0)}
    assert seen == {"root.mp4"}
