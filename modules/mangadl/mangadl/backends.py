from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit


BROAD_COLLECTION_SUBCATEGORIES = frozenset(
    {
        "artist",
        "category",
        "collection",
        "favorite",
        "favorites",
        "search",
        "tag",
        "user",
    }
)
BROAD_COLLECTION_EXTRACTORS = frozenset(
    {
        ("simplyhentai", "series"),
    }
)


class Backend(Protocol):
    name: str

    def score(self, url: str) -> int: ...


@dataclass(slots=True)
class GalleryDlBackend:
    name: str = "gallery-dl"

    def score(self, url: str) -> int:
        try:
            from gallery_dl import extractor

            return 100 if extractor.find(url) else 0
        except (ImportError, Exception):
            return 0


@dataclass(slots=True)
class NativeNhentaiBackend:
    name: str = "native-nhentai"

    def score(self, url: str) -> int:
        return 50 if "nhentai.net/g/" in url and shutil.which("nhentai") else 0


@dataclass(slots=True)
class HDPornComicsBackend:
    """The external downloader supports only HDPornComics manhwa pages."""

    name: str = "hdporncomics"

    def score(self, url: str) -> int:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        return (
            200
            if host in {"hdporncomics.com", "www.hdporncomics.com"} and parts.path.lower().startswith("/manhwa/")
            else 0
        )

    def classification(self, url: str) -> str | None:
        return "manhwa" if self.score(url) else None


@dataclass(slots=True)
class Manga18FXBackend:
    """Download complete Manga18FX series through mangadl's native backend."""

    name: str = "manga18fx"

    def score(self, url: str) -> int:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        return (
            210
            if host in {"manga18fx.com", "www.manga18fx.com"} and parts.path.lower().startswith("/manga/")
            else 0
        )

    def classification(self, url: str) -> str | None:
        return "manhwa" if self.score(url) else None


@dataclass(frozen=True, slots=True)
class GalleryDlScope:
    category: str
    subcategory: str
    extractor: str
    broad_collection: bool


def gallery_dl_scope(url: str) -> GalleryDlScope | None:
    """Describe an installed gallery-dl route without making a request."""
    try:
        from gallery_dl import extractor

        selected = extractor.find(url)
    except Exception:
        return None
    if selected is None:
        return None
    category = str(getattr(selected, "category", ""))
    subcategory = str(getattr(selected, "subcategory", ""))
    broad = (
        subcategory in BROAD_COLLECTION_SUBCATEGORIES
        or (category, subcategory) in BROAD_COLLECTION_EXTRACTORS
    )
    return GalleryDlScope(category, subcategory, type(selected).__name__, broad)


def choose_backend(url: str, requested: str = "auto") -> str:
    backends: list[Backend] = [
        Manga18FXBackend(),
        HDPornComicsBackend(),
        GalleryDlBackend(),
        NativeNhentaiBackend(),
    ]
    if requested != "auto":
        match = next((backend for backend in backends if backend.name == requested), None)
        if match is None:
            raise ValueError(f"unknown backend: {requested}")
        if match.score(url) <= 0:
            raise ValueError(f"backend {requested} does not support URL: {url}")
        return match.name
    ranked = sorted(((backend.score(url), backend.name) for backend in backends), reverse=True)
    if not ranked or ranked[0][0] <= 0:
        raise ValueError(f"no installed backend supports URL: {url}")
    return ranked[0][1]


def backend_classification(url: str, backend: str) -> str | None:
    if backend == "hdporncomics":
        return HDPornComicsBackend().classification(url)
    if backend == "manga18fx":
        return Manga18FXBackend().classification(url)
    return None
