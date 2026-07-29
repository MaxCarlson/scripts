import sys
from types import ModuleType

import pytest

from mangadl.backends import (
    HDPornComicsBackend,
    GalleryDlBackend,
    Manga18FXBackend,
    backend_classification,
    choose_backend,
)


def test_gallery_dl_backend_uses_extractor_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    supported_url = "https://nhentai.net/g/123/"
    extractor_module = ModuleType("gallery_dl.extractor")
    extractor_module.find = lambda url: object() if url == supported_url else None  # type: ignore[attr-defined]

    gallery_dl_module = ModuleType("gallery_dl")
    gallery_dl_module.extractor = extractor_module  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "gallery_dl", gallery_dl_module)
    monkeypatch.setitem(sys.modules, "gallery_dl.extractor", extractor_module)

    assert GalleryDlBackend().score(supported_url) == 100
    assert choose_backend(supported_url) == "gallery-dl"
    assert GalleryDlBackend().score("https://example.com/not-supported") == 0


def test_unknown_backend_rejected() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        choose_backend("https://example.com", "missing")


def test_hdporncomics_manhwa_routes_without_executable() -> None:
    url = "https://www.hdporncomics.com/manhwa/a-title/"
    assert HDPornComicsBackend().score(url) == 200
    assert choose_backend(url) == "hdporncomics"
    assert backend_classification(url, "hdporncomics") == "manhwa"


@pytest.mark.parametrize(
    "url",
    [
        "https://hdporncomics.com.example/manhwa/title/",
        "https://not-hdporncomics.com/manhwa/title/",
        "https://hdporncomics.com/comic/title/",
    ],
)
def test_hdporncomics_rejects_deceptive_or_non_manhwa_urls(url: str) -> None:
    assert HDPornComicsBackend().score(url) == 0


def test_manga18fx_series_routes_to_native_backend() -> None:
    url = "https://manga18fx.com/manga/an-invisible-kiss-uncensored/"

    assert Manga18FXBackend().score(url) == 210
    assert choose_backend(url) == "manga18fx"
    assert choose_backend(url, "manga18fx") == "manga18fx"
    assert backend_classification(url, "manga18fx") == "manhwa"


@pytest.mark.parametrize(
    "url",
    [
        "https://manga18fx.com.example/manga/title/",
        "https://not-manga18fx.com/manga/title/",
        "https://manga18fx.com/chapter/title-1/",
    ],
)
def test_manga18fx_rejects_deceptive_or_non_series_urls(url: str) -> None:
    assert Manga18FXBackend().score(url) == 0
