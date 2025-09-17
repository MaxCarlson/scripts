import io
import os
import sys
import time
from pathlib import Path

import pytest

import file_kit


def make_file(path: Path, size: int, fill_byte: bytes = b"A") -> Path:
    """
    Fast file creator: writes in large blocks for speed.
    Ensures deterministic content for duplicate testing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    block = fill_byte * 65536  # 64 KiB block
    remaining = size
    with open(path, "wb") as f:
        while remaining > 0:
            w = min(remaining, len(block))
            f.write(block[:w])
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
    assert file_kit.format_bytes(0).endswith("B")
    assert "KB" in file_kit.format_bytes(1024)
    assert "MB" in file_kit.format_bytes(5 * 1024**2)


def test_top_size_unicode_and_absolute(tmp_path: Path, monkeypatch):
    # Create files, including one with unicode-heavy name
    make_file(tmp_path / "aaa.bin", 2 * 1024**2)
    make_file(tmp_path / "café-文件.mp4", 3 * 1024**2)
    make_file(tmp_path / "bbb.bin", 1 * 1024**2)

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)

    args = ["top-size", "-p", str(tmp_path), "-t", "2", "-A", "-e", "utf-8"]
    file_kit.main(args)
    out = buf.getvalue()
    assert "café-文件.mp4" in out
    assert "Searching for the 2 largest" in out


def test_find_recent_and_old(tmp_path: Path, monkeypatch):
    recent = make_file(tmp_path / "recent.bin", 2048)
    old = make_file(tmp_path / "old.bin", 4096)

    # Access times: 'recent' accessed now, 'old' ~90 days ago
    now = time.time()
    os.utime(recent, (now, now))
    old_time = now - 60 * 60 * 24 * 90
    os.utime(old, (old_time, old_time))

    # ---- find-recent (uses just filename in console mode)
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


def test_find_dupes_threaded_quick(tmp_path: Path, monkeypatch):
    # Two duplicates in different dirs + one different
    a = make_file(tmp_path / "a.txt", 4096, b"A")
    b = make_file(tmp_path / "sub" / "b.txt", 4096, b"A")
    c = make_file(tmp_path / "c.txt", 4096, b"C")

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    file_kit.main(
        [
            "find-dupes",
            "-p",
            str(tmp_path),
            "-r",  # include subdir so b.txt is discovered
            "-m",
            "1kb",
            "-w",
            "2",  # few workers is enough and fast
            "-H",
            "blake2b",
            "-e",
            "utf-8",
        ]
    )
    out = buf.getvalue()
    assert "--- Found Duplicate Sets ---" in out
    assert "a.txt" in out and "b.txt" in out
    assert "c.txt" not in out


def test_find_dupes_no_quick(tmp_path: Path, monkeypatch):
    # Same as above, but ensure correctness with --no-quick
    make_file(tmp_path / "x1.bin", 4096, b"Q")
    make_file(tmp_path / "sub" / "x2.bin", 4096, b"Q")
    make_file(tmp_path / "y.bin", 4096, b"Z")

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    file_kit.main(
        [
            "find-dupes",
            "-p",
            str(tmp_path),
            "-r",
            "--no-quick",  # disable prehash path
            "-w",
            "1",
            "-H",
            "sha256",
            "-e",
            "utf-8",
        ]
    )
    out = buf.getvalue()
    assert "--- Found Duplicate Sets ---" in out
    assert "x1.bin" in out and "x2.bin" in out
    assert "y.bin" not in out


def test_output_file_and_encoding(tmp_path: Path):
    # Verify --output writes UTF-8 and preserves full paths
    uni = "naïve-路径.txt"
    target = tmp_path / uni
    make_file(target, 1234, b"Z")
    out_file = tmp_path / "out.txt"

    file_kit.main(
        ["top-size", "-p", str(tmp_path), "-t", "1", "-o", str(out_file), "-e", "utf-8"]
    )
    text = out_file.read_text(encoding="utf-8")
    assert uni in text  # ensure unicode and full path made it into the file


def test_summarize_and_du(tmp_path: Path, monkeypatch):
    # Data
    make_file(tmp_path / "x.bin", 3 * 1024**2)
    make_file(tmp_path / "y.txt", 1024)
    make_file(tmp_path / "z.TXT", 5 * 1024)
    (tmp_path / "dirA").mkdir()
    (tmp_path / "dirB").mkdir()
    make_file(tmp_path / "dirA" / "a.bin", 2048)
    make_file(tmp_path / "dirB" / "b.bin", 4096)

    # summarize
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    file_kit.main(["summarize", "-p", str(tmp_path), "-t", "10", "-r", "-e", "utf-8"])
    out = buf.getvalue()
    assert "Extension" in out and ".txt" in out.lower()

    # du sort by name (ensures --sort=name path works; also fast)
    buf2 = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf2)
    file_kit.main(
        [
            "du",
            "-p",
            str(tmp_path),
            "--max-depth",
            "1",
            "-t",
            "10",
            "--sort",
            "name",
            "-e",
            "utf-8",
        ]
    )
    out2 = buf2.getvalue()
    # Ensure both dirs listed and in name order (dirA before dirB)
    assert "Directory" in out2 and "dirA" in out2 and "dirB" in out2
    assert out2.find("dirA") < out2.find("dirB")


def test_df_text_output(monkeypatch):
    # Just ensure it runs and prints the table headers and at least one row
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    file_kit.main(["df", "--sort", "free"])
    out = buf.getvalue()
    assert "Mount" in out and "Total" in out and "Free" in out
    # There should be at least one line of data under the header separators
    assert out.count("\n") > 4


def test_df_csv_and_filter(tmp_path: Path):
    out_csv = tmp_path / "df.csv"
    # CSV export; filter with a generic slash/root substring so it likely matches on POSIX/WSL/Termux,
    # and on Windows most mounts contain ":" so we skip filter there.
    args = ["df", "--csv", "-o", str(out_csv)]
    file_kit.main(args)
    text = out_csv.read_text(encoding="utf-8")
    assert "mount,type,total,used,free,use_pct" in text
