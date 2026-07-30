from __future__ import annotations

import http.cookiejar
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import BinaryIO, Mapping
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ..input import canonicalize_url
from .constants import CONTENT_TYPE_SUFFIXES, IMAGE_SUFFIXES, SUPPORTED_COVER_HOSTS, USER_AGENT
from .models import SeriesPageMetadata
from .util import collapse_space, walk_json


class SeriesPageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.meta: dict[str, str] = {}
        self.canonical_url = base_url
        self.h1_parts: list[str] = []
        self.title_parts: list[str] = []
        self.json_ld_blocks: list[str] = []
        self.summary_images: list[str] = []
        self.itemprop_images: list[str] = []
        self._json_ld_parts: list[str] = []
        self._in_h1 = False
        self._in_title = False
        self._in_json_ld = False
        self._summary_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        attributes = {name.lower(): value or "" for name, value in attrs}
        classes = set(attributes.get("class", "").split())

        if lowered == "div":
            if self._summary_depth:
                self._summary_depth += 1
            elif "summary_image" in classes or "summary-image" in classes:
                self._summary_depth = 1

        if lowered == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").strip().lower()
            content = attributes.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content

        if lowered == "link" and "canonical" in attributes.get("rel", "").lower().split():
            href = attributes.get("href", "").strip()
            if href:
                self.canonical_url = urljoin(self.base_url, href)

        if lowered == "h1":
            self._in_h1 = True
        elif lowered == "title":
            self._in_title = True
        elif lowered == "script" and "ld+json" in attributes.get("type", "").lower():
            self._in_json_ld = True
            self._json_ld_parts = []

        if lowered == "img":
            image = image_attribute(attributes)
            if image:
                absolute = urljoin(self.base_url, image)
                if self._summary_depth:
                    self.summary_images.append(absolute)
                itemprop = attributes.get("itemprop", "").lower()
                if itemprop == "image" or attributes.get("property", "").lower() == "image":
                    self.itemprop_images.append(absolute)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self.h1_parts.append(data)
        if self._in_title:
            self.title_parts.append(data)
        if self._in_json_ld:
            self._json_ld_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "h1":
            self._in_h1 = False
        elif lowered == "title":
            self._in_title = False
        elif lowered == "script" and self._in_json_ld:
            self._in_json_ld = False
            self.json_ld_blocks.append("".join(self._json_ld_parts))
            self._json_ld_parts = []
        elif lowered == "div" and self._summary_depth:
            self._summary_depth -= 1


def image_attribute(attributes: Mapping[str, str]) -> str:
    for name in ("data-src", "data-lazy-src", "data-original", "src"):
        value = attributes.get(name, "").strip()
        if value and not value.startswith("data:"):
            return value
    for name in ("data-srcset", "srcset"):
        value = attributes.get(name, "").split(",", 1)[0].strip()
        if value:
            return value.split(None, 1)[0]
    return ""


def json_ld_values(raw: str, base_url: str) -> tuple[list[str], list[str]]:
    titles: list[str] = []
    images: list[str] = []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return titles, images
    for item in walk_json(payload):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("headline")
        if isinstance(name, str) and collapse_space(name):
            titles.append(collapse_space(name))
        image = item.get("image") or item.get("thumbnailUrl")
        if isinstance(image, str):
            images.append(urljoin(base_url, image))
        elif isinstance(image, list):
            images.extend(urljoin(base_url, value) for value in image if isinstance(value, str))
        elif isinstance(image, dict):
            value = image.get("url") or image.get("contentUrl")
            if isinstance(value, str):
                images.append(urljoin(base_url, value))
    return titles, images


def slug_title(url: str) -> str:
    slug = unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    return collapse_space(slug.replace("-", " ").replace("_", " ")).title() or "Untitled"


def pick_metadata(html: str, source_url: str) -> SeriesPageMetadata:
    parser = SeriesPageParser(source_url)
    parser.feed(html)
    parser.close()

    json_titles: list[str] = []
    json_images: list[str] = []
    for block in parser.json_ld_blocks:
        titles, images = json_ld_values(block, source_url)
        json_titles.extend(titles)
        json_images.extend(images)

    title_candidates = [
        parser.meta.get("og:title", ""),
        parser.meta.get("twitter:title", ""),
        *json_titles,
        collapse_space("".join(parser.h1_parts)),
        collapse_space("".join(parser.title_parts)),
        slug_title(source_url),
    ]
    title = next((collapse_space(value) for value in title_candidates if collapse_space(value)), slug_title(source_url))

    cover_candidates = [
        parser.meta.get("og:image", ""),
        parser.meta.get("og:image:secure_url", ""),
        parser.meta.get("twitter:image", ""),
        *parser.summary_images,
        *parser.itemprop_images,
        *json_images,
    ]
    cover_url = ""
    for candidate in cover_candidates:
        absolute = urljoin(source_url, candidate.strip()) if candidate.strip() else ""
        parts = urlsplit(absolute)
        if parts.scheme in {"http", "https"} and parts.netloc:
            cover_url = absolute
            break
    if not cover_url:
        raise RuntimeError(f"no cover image was found on series page: {source_url}")

    canonical = canonicalize_url(parser.canonical_url)
    host = (urlsplit(canonical).hostname or "").lower().rstrip(".")
    alternates = tuple(
        dict.fromkeys(
            value
            for value in (collapse_space(item) for item in title_candidates)
            if value and value.casefold() != title.casefold()
        )
    )
    return SeriesPageMetadata(source_url, canonical, host, title, alternates, cover_url)


def load_cookie_jar(path: Path | None) -> http.cookiejar.CookieJar:
    if path is None:
        return http.cookiejar.CookieJar()
    if not path.is_file():
        raise RuntimeError(f"cookies file was not found: {path}")
    jar = http.cookiejar.MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, http.cookiejar.LoadError) as exc:
        raise RuntimeError(f"could not load Netscape/Mozilla cookies from {path}: {exc}") from exc
    return jar


def make_opener(cookies: Path | None = None) -> object:
    return build_opener(HTTPCookieProcessor(load_cookie_jar(cookies)))


def request(opener: object, url: str, *, referer: str | None, timeout: float) -> BinaryIO:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    return opener.open(Request(url, headers=headers), timeout=timeout)  # type: ignore[attr-defined,no-any-return]


def supports_cover_url(url: str) -> bool:
    try:
        host = (urlsplit(canonicalize_url(url)).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host in SUPPORTED_COVER_HOSTS


def fetch_series_metadata(
    url: str,
    *,
    cookies: Path | None = None,
    timeout: float = 45.0,
    opener: object | None = None,
) -> SeriesPageMetadata:
    canonical = canonicalize_url(url)
    host = (urlsplit(canonical).hostname or "").lower().rstrip(".")
    if host not in SUPPORTED_COVER_HOSTS:
        raise ValueError(f"cover scraping is not configured for host: {host or '<missing>'}")
    active = opener or make_opener(cookies)
    with request(active, canonical, referer=None, timeout=timeout) as response:
        payload = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return pick_metadata(payload.decode(charset, errors="replace"), canonical)


def image_suffix(url: str, content_type: str | None) -> str:
    suffix = Path(unquote(urlsplit(url).path)).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return ".jpg" if suffix == ".jpeg" else suffix
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    return CONTENT_TYPE_SUFFIXES.get(normalized, ".jpg")


def valid_image_signature(payload: bytes) -> bool:
    return (
        payload.startswith(b"\xff\xd8\xff")
        or payload.startswith(b"\x89PNG\r\n\x1a\n")
        or payload.startswith((b"GIF87a", b"GIF89a"))
        or (payload.startswith(b"RIFF") and payload[8:12] == b"WEBP")
        or (len(payload) >= 12 and payload[4:8] == b"ftyp" and payload[8:12] in {b"avif", b"avis"})
        or payload.startswith(b"BM")
    )


def read_cover_bytes(
    metadata: SeriesPageMetadata,
    *,
    cookies: Path | None,
    timeout: float,
    opener: object | None = None,
) -> tuple[bytes, str]:
    active = opener or make_opener(cookies)
    with request(active, metadata.cover_url, referer=metadata.canonical_url, timeout=timeout) as response:
        payload = response.read()
        content_type = response.headers.get("Content-Type")
    if len(payload) < 1024:
        raise RuntimeError(f"cover image is suspiciously small ({len(payload)} bytes): {metadata.cover_url}")
    if not valid_image_signature(payload):
        raise RuntimeError(f"cover response is not a recognized image: {metadata.cover_url}")
    return payload, image_suffix(metadata.cover_url, content_type)
