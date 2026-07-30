from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

import mangadl.manga18fx as manga18fx
from mangadl.cli import MANGA18FX_IMAGE_WORKERS_ENV, build_parser, main


def test_public_cli_accepts_image_workers_without_mutating_environment_in_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(MANGA18FX_IMAGE_WORKERS_ENV, raising=False)
    args = build_parser().parse_args(
        [
            "run",
            "-u",
            "https://manga18fx.com/manga/example/",
            "-d",
            str(tmp_path / "downloads"),
            "-a",
            str(tmp_path / "archive.sqlite3"),
            "-I",
            "7",
            "-n",
        ]
    )

    assert args.image_workers == 7
    assert main(
        [
            "run",
            "-u",
            "https://manga18fx.com/manga/example/",
            "-d",
            str(tmp_path / "downloads"),
            "-a",
            str(tmp_path / "archive.sqlite3"),
            "-I",
            "7",
            "-n",
        ]
    ) == 0
    assert MANGA18FX_IMAGE_WORKERS_ENV not in os.environ


def test_public_cli_defaults_to_four_image_workers(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "run",
            "-u",
            "https://manga18fx.com/manga/example/",
            "-d",
            str(tmp_path / "downloads"),
            "-a",
            str(tmp_path / "archive.sqlite3"),
            "-n",
        ]
    )

    assert args.image_workers == 4


def test_download_series_parallelizes_missing_images(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    series_url = "https://manga18fx.com/manga/example/"
    chapter_url = "https://manga18fx.com/chapter/example-1/"
    series_html = f"""
    <div class="post-title"><h1>Example Series</h1></div>
    <div id="chapterlist"><a class="chapter-name" href="{chapter_url}">Chapter 1</a></div>
    """
    chapter_html = """
    <div class="read-content">
      <img src="https://cdn.example/001.jpg">
      <img src="https://cdn.example/002.jpg">
      <img src="https://cdn.example/003.jpg">
      <img src="https://cdn.example/004.jpg">
    </div>
    """

    def fake_read_text(opener: object, url: str, referer: str | None, timeout: float) -> str:
        del opener, referer, timeout
        return series_html if url == series_url else chapter_html

    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def fake_download_image(
        opener: object,
        url: str,
        referer: str,
        target_without_suffix: Path,
        timeout: float,
    ) -> Path:
        nonlocal active, maximum_active
        del opener, url, referer, timeout
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.05)
            target = target_without_suffix.with_suffix(".jpg")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"image")
            return target
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(manga18fx, "_read_text", fake_read_text)
    monkeypatch.setattr(manga18fx, "_download_image", fake_download_image)

    series_directory, downloaded, skipped = manga18fx.download_series(
        series_url,
        tmp_path,
        image_workers=4,
    )

    assert series_directory == tmp_path / "Example Series"
    assert downloaded == 4
    assert skipped == 0
    assert maximum_active >= 2
    assert maximum_active <= 4


def test_download_series_rejects_excessive_image_workers(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 1 and 8"):
        manga18fx.download_series(
            "https://manga18fx.com/manga/example/",
            tmp_path,
            image_workers=9,
        )
