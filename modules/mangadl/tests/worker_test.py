import sys
from argparse import Namespace
from pathlib import Path

import pytest

from mangadl.naming import DIRECTORY_TEMPLATE, FILENAME_TEMPLATE
from mangadl.worker import (
    _classify,
    _command,
    _effective_gallery_returncode,
    _gallery_naming_options,
    _manga18fx_completion,
    _merge_partial,
    _parse_manga18fx_output,
    _tree_stats,
)


def test_tree_stats_and_merge_partial(tmp_path: Path) -> None:
    partial = tmp_path / "partial"
    gallery = partial / "nhentai" / "1 title"
    gallery.mkdir(parents=True)
    (gallery / "001.jpg").write_bytes(b"123")
    (gallery / "002.webp").write_bytes(b"4567")
    assert _tree_stats(partial) == (2, 7)
    destination = tmp_path / "destination"
    _merge_partial(partial, destination)
    assert (destination / "nhentai" / "1 title" / "002.webp").exists()
    assert not partial.exists()


def test_merge_partial_handles_existing_nested_destination(tmp_path: Path) -> None:
    partial = tmp_path / "partial"
    source_chapter = partial / "mangakakalot" / "Series" / "c002"
    source_chapter.mkdir(parents=True)
    (source_chapter / "002.webp").write_bytes(b"new")
    destination_chapter = tmp_path / "destination" / "mangakakalot" / "Series" / "c001"
    destination_chapter.mkdir(parents=True)
    (destination_chapter / "001.webp").write_bytes(b"old")

    _merge_partial(partial, tmp_path / "destination")

    assert (tmp_path / "destination" / "mangakakalot" / "Series" / "c001" / "001.webp").exists()
    assert (tmp_path / "destination" / "mangakakalot" / "Series" / "c002" / "002.webp").exists()
    assert not partial.exists()


def test_tree_stats_counts_active_part_bytes_but_not_complete_images(tmp_path: Path) -> None:
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "0001.jpg.part").write_bytes(b"12345")
    (partial / "0002.jpg").write_bytes(b"123")
    (partial / "ignored.tmp").write_bytes(b"1234567")

    assert _tree_stats(partial) == (1, 8)


def test_failure_classification() -> None:
    assert _classify(1, "HTTP 429 rate limit") == ("rate_limit", True)
    assert _classify(1, "database is locked") == ("archive", True)
    assert _classify(1, "HTTP 404 not found") == ("bad_url", False)
    assert _classify(1, "gallery_dl.exception.ChallengeError: Cloudflare challenge") == (
        "auth_challenge",
        False,
    )
    assert _classify(1, 'GET /manga/title HTTP/1.1" 403') == ("auth_challenge", False)
    assert _classify(1, "downloaded image 403.jpg") == ("backend", True)
    assert _classify(1, "HttpError: '520 <none>' for chapter") == ("http", True)
    assert _classify(1, "downloaded image 520.jpg") == ("backend", True)


def test_gallery_child_errors_override_zero_process_exit() -> None:
    assert _effective_gallery_returncode("gallery-dl", 0, ["[mangakakalot][error] HttpError: 520"]) == 1
    assert _effective_gallery_returncode("gallery-dl", 0, []) == 0
    assert _effective_gallery_returncode("manga18fx", 0, ["error text owned by another backend"]) == 0


def test_manga18fx_output_parser_reads_chapter_and_completion_counts() -> None:
    chapter = _parse_manga18fx_output("chapter=2/215 title='Chapter 2' images=37")
    complete = _parse_manga18fx_output(
        "complete destination=C:\\downloads\\Title downloaded=0 skipped=8123"
    )

    assert chapter == {
        "kind": "chapter",
        "chapter_index": 2,
        "chapters_total": 215,
        "chapter_title": "Chapter 2",
        "chapter_images": 37,
    }
    assert complete == {
        "kind": "complete",
        "downloaded": 0,
        "skipped": 8123,
        "processed": 8123,
        "images_total": 8123,
    }


def test_manga18fx_completion_distinguishes_resume_from_empty_success() -> None:
    assert _manga18fx_completion(0, 8123) == (
        "skipped_archive",
        8123,
        "already complete: 8123 images were present in the library",
    )
    assert _manga18fx_completion(25, 75) == (
        "succeeded",
        100,
        "completed: 25 downloaded, 75 already present",
    )
    assert _manga18fx_completion(100, 0) == ("succeeded", 100, "")

    with pytest.raises(ValueError, match="zero downloaded or existing images"):
        _manga18fx_completion(0, 0)


def test_gallery_command_uses_base_destination_and_nhentai_naming(tmp_path: Path) -> None:
    args = Namespace(
        backend="gallery-dl",
        archive=str(tmp_path / "archive.db"),
        gallery_config=None,
        cookies=None,
        cookies_browser=None,
        gallery_user_agent="Matching Browser UA",
        rate=None,
        url="https://nhentai.net/g/123/",
    )
    command = _command(args, tmp_path / "partial")
    assert "--destination" in command
    assert "--directory" not in command
    assert f'directory=["{DIRECTORY_TEMPLATE}"]' in command
    assert f"filename={FILENAME_TEMPLATE}" in command
    assert command[command.index("--user-agent") + 1] == "Matching Browser UA"


def test_gallery_command_preserves_mangakakalot_native_naming(tmp_path: Path) -> None:
    args = Namespace(
        backend="gallery-dl",
        archive=str(tmp_path / "archive.db"),
        gallery_config=None,
        cookies=None,
        cookies_browser=None,
        gallery_user_agent="Matching Browser UA",
        rate=None,
        url="https://www.mangakakalot.gg/manga/like-no-other",
    )

    command = _command(args, tmp_path / "partial")

    assert _gallery_naming_options(args.url) == []
    assert not any(value.startswith("directory=") for value in command)
    assert not any(value.startswith("filename=") for value in command)


def test_hdporncomics_command_forces_manhwa_and_uses_output_root(tmp_path: Path) -> None:
    executable = tmp_path / "hdporncomics.exe"
    executable.write_text("", encoding="utf-8")
    output = tmp_path / "output root"
    args = Namespace(
        backend="hdporncomics",
        hdporncomics_executable=str(executable),
        hdporncomics_threads=8,
        destination=str(output),
        url="https://hdporncomics.com/manhwa/a title/",
    )
    assert _command(args, tmp_path / "ignored") == [
        str(executable.resolve()),
        "--directory",
        str(output),
        "--threads",
        "8",
        "--force",
        "--manhwa",
        "https://hdporncomics.com/manhwa/a title/",
    ]


def test_manga18fx_command_uses_native_module_and_partial_root(tmp_path: Path) -> None:
    partial = tmp_path / "partial root"
    cookies = tmp_path / "cookies.txt"
    args = Namespace(
        backend="manga18fx",
        cookies=str(cookies),
        url="https://manga18fx.com/manga/example/",
    )

    assert _command(args, partial) == [
        sys.executable,
        "-m",
        "mangadl.manga18fx",
        "--destination",
        str(partial),
        "--cookies",
        str(cookies),
        "https://manga18fx.com/manga/example/",
    ]
