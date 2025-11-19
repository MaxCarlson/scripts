from __future__ import annotations

from pathlib import Path

from ytaedl.archive_builder import _slug_from_path, cli_main


def _write(url_dir: Path, name: str, urls: str) -> Path:
    path = url_dir / name
    path.write_text(urls, encoding="utf-8")
    return path


def _make_mp4(folder: Path, name: str, size: int = 1024) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"x" * size)
    return path


def test_archive_builder_creates_archive(tmp_path):
    url_dir = tmp_path / "urls"
    download_dir = tmp_path / "dl"
    archive_dir = tmp_path / "archives"
    url_dir.mkdir()
    download_dir.mkdir()

    _write(url_dir, "alpha.txt", "http://a\nhttp://b\n")
    _make_mp4(download_dir / "alpha", "clip.mp4", size=2048)

    args = [
        "-u",
        str(url_dir),
        "-d",
        str(download_dir),
        "-A",
        str(archive_dir),
    ]
    assert cli_main(args) == 0

    prefix = _slug_from_path(url_dir)
    archive_file = archive_dir / f"{prefix}_alpha.txt"
    assert archive_file.exists()
    lines = [line for line in archive_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert "http://a" in lines[0]


def test_archive_builder_writes_rebuild_when_existing_differs(tmp_path):
    url_dir = tmp_path / "urls"
    download_dir = tmp_path / "dl"
    archive_dir = tmp_path / "archives"
    url_dir.mkdir()
    download_dir.mkdir()
    archive_dir.mkdir()

    _write(url_dir, "beta.txt", "http://x\nhttp://y\n")
    _make_mp4(download_dir / "beta", "only.mp4", size=1024)

    prefix = _slug_from_path(url_dir)
    existing = archive_dir / f"{prefix}_beta.txt"
    existing.write_text("FINISH\t0\t1970-01-01T00:00:00Z\t1.00MiB\t\tbad\nother\n", encoding="utf-8")

    args = [
        "-u",
        str(url_dir),
        "-d",
        str(download_dir),
        "-A",
        str(archive_dir),
    ]
    assert cli_main(args) == 0

    rebuild = archive_dir / f"{prefix}_beta.rebuild.txt"
    assert rebuild.exists()
    rebuilt_lines = [line for line in rebuild.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rebuilt_lines) == 1
    assert "http://x" in rebuilt_lines[0]
