from __future__ import annotations

import json
from pathlib import Path

import pytest

from mangadl.cli import main
from mangadl.favorites import FavoritesResult, _parse_browser_spec, extract_favorite_links


def test_extract_favorite_links_keeps_supported_same_site_targets_and_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mangadl.favorites._download_target",
        lambda url: "/g/" in url,
    )
    html = """
    <html><body>
      <a href="/g/123/">One</a>
      <a href="https://nhentai.net/g/456/">Two</a>
      <a href="/favorites/?page=2" class="next"><i></i></a>
      <a href="https://cdn.example/1.jpg">Image</a>
      <a href="/tag/parody/">Collection</a>
    </body></html>
    """

    urls, next_url = extract_favorite_links("https://nhentai.net/favorites/", html)

    assert urls == [
        "https://nhentai.net/g/123/",
        "https://nhentai.net/g/456/",
    ]
    assert next_url == "https://nhentai.net/favorites/?page=2"


def test_favorites_cli_is_dry_run_first_and_apply_writes_url_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "favorites.txt"
    result = FavoritesResult(
        source_url="https://nhentai.net/favorites/",
        pages_scanned=2,
        urls=("https://nhentai.net/g/123/", "https://nhentai.net/g/456/"),
        rejected=(),
    )
    monkeypatch.setattr("mangadl.cli_core.crawl_favorites", lambda *args, **kwargs: result)

    assert main(["favorites", "-u", result.source_url, "-o", str(output), "-j"]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["applied"] is False
    assert dry_run["count"] == 2
    assert not output.exists()

    assert main(["favorites", "-u", result.source_url, "-o", str(output), "-f", "-j"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["applied"] is True
    assert output.read_text(encoding="utf-8").splitlines() == list(result.urls)


def test_gallery_dl_browser_cookie_spec_is_preserved() -> None:
    assert _parse_browser_spec("firefox") == ("firefox", None, None, None, None)
    assert _parse_browser_spec("firefox/nhentai.net:default-release::all") == (
        "firefox",
        "default-release",
        None,
        "all",
        "nhentai.net",
    )


def test_favorites_parser_rejects_invalid_bounds(tmp_path: Path) -> None:
    output = tmp_path / "favorites.txt"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "favorites",
                "-u",
                "https://nhentai.net/favorites/",
                "-o",
                str(output),
                "-P",
                "0",
            ]
        )

    assert exc_info.value.code == 2
    assert not output.exists()
