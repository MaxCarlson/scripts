import sys
from argparse import Namespace
from pathlib import Path

from mangadl.naming import DIRECTORY_TEMPLATE, FILENAME_TEMPLATE
from mangadl.worker import _classify, _command, _merge_partial, _tree_stats


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


def test_failure_classification() -> None:
    assert _classify(1, "HTTP 429 rate limit") == ("rate_limit", True)
    assert _classify(1, "database is locked") == ("archive", True)
    assert _classify(1, "HTTP 404 not found") == ("bad_url", False)


def test_gallery_command_uses_base_destination_and_shared_naming(tmp_path: Path) -> None:
    args = Namespace(
        backend="gallery-dl",
        archive=str(tmp_path / "archive.db"),
        gallery_config=None,
        cookies=None,
        cookies_browser=None,
        rate=None,
        url="https://nhentai.net/g/123/",
    )
    command = _command(args, tmp_path / "partial")
    assert "--destination" in command
    assert "--directory" not in command
    assert f'directory=["{DIRECTORY_TEMPLATE}"]' in command
    assert f"filename={FILENAME_TEMPLATE}" in command


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
