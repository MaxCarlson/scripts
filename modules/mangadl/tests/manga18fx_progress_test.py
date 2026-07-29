from pathlib import Path

import pytest

from mangadl.manga18fx import download_series
from mangadl.worker import _manga18fx_completion, _parse_manga18fx_output


def test_parse_manga18fx_cumulative_progress() -> None:
    parsed = _parse_manga18fx_output(
        "progress chapter=39/273 title='Chapter 39' chapter_images=21 "
        "downloaded=17 skipped=801 processed=818 discovered=818"
    )

    assert parsed == {
        "kind": "progress",
        "chapter_index": 39,
        "chapters_total": 273,
        "chapter_title": "Chapter 39",
        "chapter_images": 21,
        "downloaded": 17,
        "skipped": 801,
        "processed": 818,
        "discovered": 818,
    }


def test_download_series_emits_progress_for_existing_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    series_html = """
    <div class="post-title"><h1>Example Series</h1></div>
    <a class="chapter-name" href="/chapter/example-1/">Chapter 1</a>
    """
    chapter_html = """
    <div class="read-content">
      <img data-src="/images/001.jpg">
      <img data-src="/images/002.jpg">
    </div>
    """
    responses = iter((series_html, chapter_html))
    monkeypatch.setattr(
        "mangadl.manga18fx._read_text",
        lambda *_args, **_kwargs: next(responses),
    )

    existing_root = tmp_path / "library"
    existing_chapter = existing_root / "Example Series" / "0001 - Chapter 1"
    existing_chapter.mkdir(parents=True)
    (existing_chapter / "0001.jpg").write_bytes(b"one")
    (existing_chapter / "0002.jpg").write_bytes(b"two")

    destination = tmp_path / "_partial" / "job-1"
    series_directory, downloaded, skipped = download_series(
        "https://manga18fx.com/manga/example/",
        destination,
        existing_root=existing_root,
        image_workers=2,
    )

    output = capsys.readouterr().out
    assert series_directory == destination / "Example Series"
    assert downloaded == 0
    assert skipped == 2
    assert "progress chapter=1/1" in output
    assert "downloaded=0 skipped=2 processed=2 discovered=2" in output
    assert _manga18fx_completion(downloaded, skipped) == (
        "skipped_archive",
        2,
        "already complete: 2 images were present in the library",
    )
