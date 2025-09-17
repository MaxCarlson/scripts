# file: tests/folder_stats_test.py
import os
import sys
import time
import pytest
from pathlib import Path
from folder_stats import (
    gather_stats,
    print_stats,
    traverse,
    main,
    gather_dir_totals,
    _normalize_exts,
    _normalize_exts_raw,
    print_hotspots,
    gather_top_files,
    print_top_files,
)


def make_file(path: Path, size: int, atime: float = None, mtime: float = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if atime or mtime:
        now = time.time()
        os.utime(path, (atime or now, mtime or now))


@pytest.fixture
def sample_tree(tmp_path):
    root = tmp_path / "root"
    make_file(root / "a.txt", 3)
    make_file(root / "b.TXT", 5)
    make_file(root / "noext", 2)
    make_file(root / "sub" / "c.jpg", 4)
    make_file(root / "sub" / "nested" / "d.png", 1)
    # Frag-style names
    make_file(root / "frag_dir" / "clip.mp4-frag123", 10)
    make_file(root / "frag_dir" / "part.part-frag77", 7)
    return root


def test_gather_stats_full(sample_tree):
    stats = gather_stats(sample_tree, maxdepth=-1)
    assert stats[".txt"]["count"] == 2
    assert stats[".txt"]["total"] == 8
    assert stats[".jpg"]["count"] == 1
    assert stats[".jpg"]["total"] == 4
    assert stats[".png"]["count"] == 1
    assert stats[".png"]["total"] == 1
    assert stats["[no extension]"]["count"] == 1
    assert stats["[no extension]"]["total"] == 2
    # collapsed pseudo-extensions present
    assert stats[".mp4-frag*"]["count"] == 1
    assert stats[".part-frag*"]["count"] == 1


def test_gather_stats_depth_zero(sample_tree):
    stats = gather_stats(sample_tree, maxdepth=0)
    assert ".jpg" not in stats and ".png" not in stats
    assert set(stats.keys()) & {".txt", "[no extension]"} == {".txt", "[no extension]"}
    assert stats[".txt"]["count"] == 2
    assert stats[".txt"]["total"] == 8


def test_gather_stats_depth_one(sample_tree):
    stats = gather_stats(sample_tree, maxdepth=1)
    assert ".png" not in stats
    assert ".jpg" in stats


def test_symlink_and_hardlink(tmp_path):
    root = tmp_path / "d"
    make_file(root / "orig.txt", 10)
    try:
        os.symlink(root / "orig.txt", root / "link.txt")
        symlink_ok = True
    except (OSError, NotImplementedError):
        symlink_ok = False
    if hasattr(os, "link"):
        try:
            os.link(root / "orig.txt", root / "hard.txt")
        except OSError:
            pytest.skip("Hard links not supported")
    else:
        pytest.skip("os.link not available")

    stats = gather_stats(root, maxdepth=0)
    if symlink_ok:
        assert stats.get("[symlink]")["count"] == 1
    assert stats.get(".txt")["count"] >= 2
    assert stats.get("[hardlink]")["count"] >= 1


def test_date_flag(sample_tree, capsys):
    old = time.time() - 10000
    os.utime(sample_tree / "a.txt", (old, old))
    stats = gather_stats(sample_tree, maxdepth=-1)

    class Args:
        auto_units = False
        dates = "mtime"
        tree = False
        depth = -1
        sort = "size"
        reverse = False
        # new flags defaults
        exclude = []
        follow_symlinks = False
        skip_empty = False

    print_stats(stats, indent=0, dir_name="X", args=Args(), header_note=None)
    out = capsys.readouterr().out
    assert "Oldest" in out and "Newest" in out


def test_auto_units_and_switch(sample_tree, capsys, monkeypatch):
    big = sample_tree / "big.bin"
    make_file(big, 1)
    orig_stat = Path.stat
    fake_size = 11 * 1024 * 1024 * 1024

    def fake_stat(self, *args, **kwargs):
        st = orig_stat(self, *args, **kwargs)
        try:
            import os as _os

            lst = list(st)
            if hasattr(st, "st_size"):
                idx = lst.index(st.st_size)
            else:
                idx = 6
            lst[idx] = fake_size
            return _os.stat_result(tuple(lst))
        except Exception:

            class _S:
                st_size = fake_size
                st_atime = st.st_atime
                st_mtime = st.st_mtime
                st_ctime = st.st_ctime

            return _S()

    monkeypatch.setattr(Path, "stat", fake_stat)

    class Args1:
        auto_units = False
        dates = None
        tree = False
        depth = 0
        sort = "size"
        reverse = False
        exclude = []
        follow_symlinks = False
        skip_empty = False

    stats = gather_stats(sample_tree, maxdepth=0)
    print_stats(stats, args=Args1())
    out1 = capsys.readouterr().out
    assert "MB" in out1

    class Args2:
        auto_units = False
        dates = None
        tree = True
        depth = 0
        sort = "size"
        reverse = False
        exclude = []
        follow_symlinks = False
        hotspots = 0
        no_frag_collapse = False
        skip_empty = True
        min_size_bytes = 0

    traverse(sample_tree, Args2(), current_depth=0)
    out2 = capsys.readouterr().out.lower()
    assert "switching to auto-units" in out2
    assert any(unit in out2 for unit in ("kb", "mb", "gb", "tb"))


def test_tree_flag_cli(tmp_path, capsys, monkeypatch):
    root = tmp_path / "d"
    make_file(root / "x.py", 4)
    sub = root / "d2"
    make_file(sub / "y.txt", 2)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["prog", "d", "-t"])
    main()
    out = capsys.readouterr().out
    assert root.name in out
    assert sub.name in out


def test_main_max_depth(tmp_path, capsys, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["prog", "empty"])
    main()
    out = capsys.readouterr().out
    assert "Max depth:" in out


# ------------------ NEW: hotspots --------------------------------------------


def test_hotspots_focus_ext(sample_tree, capsys):
    # Focus on .png should point to root/sub/nested as top folder
    focus = _normalize_exts(["png"])
    dir_map, c, b = gather_dir_totals(sample_tree, maxdepth=-1, focus_exts=focus)
    print_hotspots(
        sample_tree,
        dir_map,
        top_n=3,
        base_total=b,
        base_count=c,
        auto_units=True,
        sort="size",
    )
    out = capsys.readouterr().out
    assert "sub" in out and "nested" in out


def test_hotspots_all(sample_tree, capsys):
    dir_map, c, b = gather_dir_totals(sample_tree, maxdepth=-1, focus_exts=None)
    print_hotspots(
        sample_tree,
        dir_map,
        top_n=2,
        base_total=b,
        base_count=c,
        auto_units=False,
        sort="size",
    )
    out = capsys.readouterr().out
    assert "Files" in out and "Size" in out


# ------------------ NEW: focus filtering & wildcard --------------------------


def test_focus_filters_main_table(sample_tree, capsys, monkeypatch):
    # CLI: focus on .txt only; other extensions should not appear.
    monkeypatch.chdir(sample_tree.parent)
    monkeypatch.setattr(sys, "argv", ["prog", "root", "-e", "txt"])
    main()
    out = capsys.readouterr().out
    assert ".txt" in out
    assert ".jpg" not in out
    assert ".png" not in out


def test_wildcard_frag_pattern_matches(sample_tree, capsys, monkeypatch):
    # Focus on wildcard pseudo-extension
    monkeypatch.chdir(sample_tree.parent)
    monkeypatch.setattr(sys, "argv", ["prog", "root", "-e", ".mp4-frag*"])
    main()
    out = capsys.readouterr().out
    assert ".mp4-frag*" in out
    assert ".txt" not in out
    assert ".jpg" not in out


# ------------------ NEW: top files & excludes respected in traverse ----------


def test_top_files_and_exclude_in_tree(tmp_path, capsys, monkeypatch):
    root = tmp_path / "R"
    make_file(root / "keep" / "big.mp4", 5000)
    make_file(root / "keep" / "small.mp4", 10)
    make_file(root / "tmpvids" / "skip.mp4", 999999)  # should be excluded
    monkeypatch.chdir(tmp_path)
    # -t to exercise traverse recursion; -x tmpvids must avoid visiting it
    monkeypatch.setattr(
        sys, "argv", ["prog", "R", "-e", "mp4", "-t", "-x", "tmpvids", "-f", "1"]
    )
    main()
    out = capsys.readouterr().out
    assert "tmpvids" not in out
    assert "big.mp4" in out


# ------------------ NEW: min-size gating in tree mode ------------------------


def test_min_size_gate_in_tree(tmp_path, capsys, monkeypatch):
    root = tmp_path / "R2"
    make_file(root / "small" / "s.bin", 1024)  # 1KB
    make_file(root / "big" / "b.bin", 10 * 1024)  # 10KB
    monkeypatch.chdir(tmp_path)
    # Gate at 5KB: 'small' should not print, 'big' should.
    monkeypatch.setattr(sys, "argv", ["prog", "R2", "-t", "-g", "5KB"])
    main()
    out = capsys.readouterr().out
    assert "small" not in out
    assert "big" in out
