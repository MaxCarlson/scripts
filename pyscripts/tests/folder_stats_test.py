import os
import sys
import pytest
from folder_stats import gather_stats, print_stats, traverse_and_report, main
from pathlib import Path


def make_file(path: Path, size: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)

@pytest.fixture
def sample_tree(tmp_path):
    # root/
    #   a.txt (3 bytes)
    #   b.TXT (5 bytes)
    #   noext       (2 bytes)
    #   sub/
    #     c.jpg    (4 bytes)
    #     nested/
    #       d.png  (1 byte)
    root = tmp_path / "root"
    make_file(root / "a.txt", 3)
    make_file(root / "b.TXT", 5)
    make_file(root / "noext", 2)
    make_file(root / "sub" / "c.jpg", 4)
    make_file(root / "sub" / "nested" / "d.png", 1)
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


def test_gather_stats_depth_zero(sample_tree):
    stats = gather_stats(sample_tree, maxdepth=0)
    assert set(stats.keys()) == {".txt", "[no extension]"}
    assert stats[".txt"]["count"] == 2
    assert stats[".txt"]["total"] == 8


def test_gather_stats_depth_one(sample_tree):
    stats = gather_stats(sample_tree, maxdepth=1)
    assert ".png" not in stats
    assert ".jpg" in stats


def test_print_stats(capsys):
    stats = {".a": {"count": 2, "total": 10}, "[no extension]": {"count": 1, "total": 3}}
    print_stats(stats, indent=1, dir_name="X")
    out = capsys.readouterr().out
    assert "    X:" in out
    assert "Extension" in out
    assert ".a" in out
    assert "TOTAL" in out


def test_traverse_and_report(capsys, sample_tree):
    traverse_and_report(sample_tree, maxdepth=0)
    out = capsys.readouterr().out.splitlines()
    assert str(sample_tree) + ":" in out[0]
    assert any("TOTAL" in line for line in out)


def test_cli(tmp_path, capsys, monkeypatch):
    root = tmp_path / "d"
    make_file(root / "x.py", 4)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["prog", "d"])
    main()
    out = capsys.readouterr().out
    assert ".py" in out
    assert "TOTAL" in out

    monkeypatch.setattr(sys, "argv", ["prog", "d", "--subdirs", "-d", "0"])
    main()
    out2 = capsys.readouterr().out
    assert str(root) + ":" in out2


if __name__ == "__main__":
    pytest.main()
