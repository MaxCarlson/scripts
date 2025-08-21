import io
import os
import sys
import time
from pathlib import Path

import pytest
import file_kit


def make_file(path: Path, size: int, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        if size <= 0:
            return path
        chunk = data * max(1, min(1024, len(data)))
        remaining = size
        while remaining > 0:
            w = min(remaining, len(chunk))
            f.write(chunk[:w])
            remaining -= w
    return path


def test_parse_size():
    assert file_kit.parse_size("0") == 0
    assert file_kit.parse_size("1k") == 1024
    assert file_kit.parse_size("1kb") == 1024
    assert file_kit.parse_size("1.5mb") == int(1.5 * 1024**2)
    assert file_kit.parse_size("2g") == 2 * 1024**3
    with pytest.raises(Exception):
        file_kit.parse_size("notasize")


def test_format_bytes_roundtrip():
    # Sanity spot checks
    assert file_kit.format_bytes(0).endswith("B")
    assert "KB" in file_kit.format_bytes(1024)
    assert "MB" in file_kit.format_bytes(5 * 1024**2)


def test_top_size_unicode_and_absolute(tmp_path: Path, monkeypatch):
    # Create files, including one with unicode that would fail on cp1252
    f1 = make_file(tmp_path / "aaa.bin", 5 * 1024**2)
    f2 = make_file(tmp_path / "café-文件.mp4", 10 * 1024**2)  # unicode-heavy
    f3 = make_file(tmp_path / "bbb.bin", 1 * 1024**2)

    # Capture stdout safely
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)

    args = [
        "top-size",
        "-p",
        str(tmp_path),
        "-t",
        "2",
        "-A",  # absolute
        "-e",
        "utf-8",
    ]
    file_kit.main(args)
    out = buf.getvalue()
    # Should include Unicode filename and not crash
    assert "café-文件.mp4" in out
    # Two results plus header/footer lines
    assert "Searching for the 2 largest" in out


def test_find_recent_and_old(tmp_path: Path, monkeypatch):
    recent = make_file(tmp_path / "recent.bin", 2048)
    old = make_file(tmp_path / "old.bin", 4096)

    # Set times: 'recent' accessed now, 'old' much older
    now = time.time()
    os.utime(recent, (now, now))
    os.utime(old, (now - 60 * 60 * 24 * 90, now - 60 * 60 * 24 * 90))  # 90 days ago

    # ---- find-recent
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    file_kit.main(
        ["find-recent", "-p", str(tmp_path), "-s", "1kb", "-d", "30", "-e", "utf-8"]
    )
    out = buf.getvalue()
    assert "recent.bin" in out

    # ---- find-old (by modified)
    buf2 = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf2)
    file_kit.main(
        [
            "find-old",
            "-p",
            str(tmp_path),
            "-c",
            "60",
            "-t",
            "5",
            "-d",
            "m",
            "-e",
            "utf-8",
        ]
    )
    out2 = buf2.getvalue()
    assert "old.bin" in out2


def test_find_dupes_threaded(tmp_path: Path, monkeypatch):
    a = make_file(tmp_path / "a.txt", 10_000, b"A")
    b = make_file(tmp_path / "sub" / "b.txt", 10_000, b"A")
    c = make_file(tmp_path / "c.txt", 10_000, b"C")

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    file_kit.main(
        [
            "find-dupes",
            "-p",
            str(tmp_path),
            "-m",
            "1kb",
            "-w",
            "4",
            "-H",
            "blake2b",
            "-e",
            "utf-8",
        ]
    )
    out = buf.getvalue()
    # Should find a/b as duplicates; c is different
    assert "--- Found Duplicate Sets ---" in out
    assert str(a.name) in out and str(b.name) in out
    assert str(c.name) not in out


def test_summarize_and_du(tmp_path: Path, monkeypatch):
    make_file(tmp_path / "x.bin", 3 * 1024**2)
    make_file(tmp_path / "y.txt", 1024)
    make_file(tmp_path / "z.TXT", 5 * 1024)

    # summarize
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    file_kit.main(["summarize", "-p", str(tmp_path), "-t", "10", "-r", "-e", "utf-8"])
    out = buf.getvalue()
    assert "Extension" in out and ".txt" in out.lower()

    # du (depth 1)
    buf2 = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf2)
    file_kit.main(
        ["du", "-p", str(tmp_path), "--max-depth", "1", "-t", "10", "-e", "utf-8"]
    )
    out2 = buf2.getvalue()
    assert "Directory" in out2
