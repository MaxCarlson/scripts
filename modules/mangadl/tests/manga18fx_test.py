from pathlib import Path

import pytest

from mangadl.manga18fx import Chapter, parse_chapter_images, parse_series, sanitize_component


def test_parse_series_title_chapters_and_natural_order() -> None:
    html = """
    <div class="post-title"><h1>  Example   Series </h1></div>
    <div id="chapterlist"><ul>
      <li><a class="chapter-name" href="/chapter/example-10/">Chapter 10</a></li>
      <li><a class="chapter-name extra" href="https://manga18fx.com/chapter/example-2/">Chapter 2</a></li>
      <li><a class="chapter-name" href="/chapter/example-2/">Duplicate Chapter 2</a></li>
    </ul></div>
    """

    title, chapters = parse_series(html, "https://manga18fx.com/manga/example/")

    assert title == "Example Series"
    assert chapters == [
        Chapter("Chapter 2", "https://manga18fx.com/chapter/example-2/"),
        Chapter("Chapter 10", "https://manga18fx.com/chapter/example-10/"),
    ]


def test_parse_chapter_images_uses_lazy_sources_and_deduplicates() -> None:
    html = """
    <div class="read-manga"><div class="read-content">
      <source data-src="/images/001.webp">
      <div class="page-break"><source srcset="/images/002.jpg 1x, /images/002@2x.jpg 2x"></div>
      <img src="data:image/gif;base64,placeholder" data-lazy-src="https://cdn.example/003.png">
      <source data-src="/images/001.webp">
    </div></div>
    <source src="/outside.jpg">
    """

    assert parse_chapter_images(html, "https://manga18fx.com/chapter/example-1/") == [
        "https://manga18fx.com/images/001.webp",
        "https://manga18fx.com/images/002.jpg",
        "https://cdn.example/003.png",
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('A: Bad/Title?', "A_ Bad_Title_"),
        ("CON", "_CON"),
        ("   ", "fallback"),
    ],
)
def test_sanitize_component_is_windows_safe(value: str, expected: str) -> None:
    assert sanitize_component(value, "fallback") == expected


def test_sanitize_component_limits_long_names() -> None:
    result = sanitize_component("x" * 300, max_length=80)

    assert len(result) == 80
    assert result == "x" * 80
