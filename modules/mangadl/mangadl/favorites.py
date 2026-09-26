from __future__ import annotations

import http.cookiejar
import json
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .backends import choose_backend, gallery_dl_scope
from .gallery_auth import ProfileStore, domain_for

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"


@dataclass(frozen=True, slots=True)
class FavoritesResult:
    source_url: str
    pages_scanned: int
    urls: tuple[str, ...]
    rejected: tuple[str, ...]


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, tuple[str, ...], tuple[str, ...], str]] = []
        self._href: str | None = None
        self._rel: tuple[str, ...] = ()
        self._classes: tuple[str, ...] = ()
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        href = values.get("href", "").strip()
        if not href:
            return
        self._href = href
        self._rel = tuple(part.lower() for part in values.get("rel", "").split() if part)
        self._classes = tuple(part.lower() for part in values.get("class", "").split() if part)
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        self.links.append((self._href, self._rel, self._classes, " ".join(self._text).strip()))
        self._href = None
        self._rel = ()
        self._classes = ()
        self._text = []


def _normalized_http_url(base_url: str, href: str) -> str | None:
    value, _fragment = urldefrag(urljoin(base_url, href))
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return value


def _same_site(left: str, right: str) -> bool:
    return domain_for(left) == domain_for(right)


def _download_target(url: str) -> bool:
    try:
        backend = choose_backend(url, "auto")
        if backend != "gallery-dl":
            return True
        scope = gallery_dl_scope(url)
        return not scope.broad_collection
    except (RuntimeError, ValueError):
        return False


def extract_favorite_links(page_url: str, html: str) -> tuple[list[str], str | None]:
    parser = _LinkParser()
    parser.feed(html)

    urls: list[str] = []
    seen: set[str] = set()
    next_url: str | None = None
    for href, rel, classes, text in parser.links:
        absolute = _normalized_http_url(page_url, href)
        if absolute is None:
            continue

        if next_url is None and _same_site(page_url, absolute):
            label = text.strip().lower()
            if "next" in rel or "next" in classes or label in {"next", "next >", "next ›", "›", "»", "older", "older >"}:
                next_url = absolute

        if absolute in seen or absolute == page_url:
            continue
        if not _same_site(page_url, absolute):
            continue
        if not _download_target(absolute):
            continue
        seen.add(absolute)
        urls.append(absolute)

    return urls, next_url


def _build_opener(cookie_file: Path | None):
    if cookie_file is None:
        return build_opener()
    if not cookie_file.is_file():
        raise ValueError(f"cookie file does not exist: {cookie_file}")
    jar = http.cookiejar.MozillaCookieJar(str(cookie_file))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, http.cookiejar.LoadError) as exc:
        raise ValueError(f"could not load Netscape cookie file {cookie_file}: {exc}") from exc
    return build_opener(HTTPCookieProcessor(jar))


def resolve_credentials(
    url: str,
    *,
    auth_dir: Path | None = None,
    cookie_file: Path | None = None,
    user_agent: str | None = None,
) -> tuple[Path | None, str]:
    if cookie_file is not None:
        profile = ProfileStore(auth_dir).load(domain_for(url))
        return cookie_file, user_agent or (profile.user_agent if profile else DEFAULT_USER_AGENT)

    profile = ProfileStore(auth_dir).load(domain_for(url))
    if profile is None:
        return None, user_agent or DEFAULT_USER_AGENT
    return profile.cookie_path, user_agent or profile.user_agent


def crawl_favorites(
    url: str,
    *,
    auth_dir: Path | None = None,
    cookie_file: Path | None = None,
    user_agent: str | None = None,
    max_pages: int = 20,
    page_delay: float = 1.0,
    timeout: float = 30.0,
    progress: Callable[[str], None] | None = None,
) -> FavoritesResult:
    if max_pages < 1:
        raise ValueError("--max-pages must be at least 1")
    if page_delay < 0:
        raise ValueError("--page-delay must be zero or greater")
    if timeout <= 0:
        raise ValueError("--timeout must be greater than zero")

    cookie_file, user_agent = resolve_credentials(
        url,
        auth_dir=auth_dir,
        cookie_file=cookie_file,
        user_agent=user_agent,
    )
    opener = _build_opener(cookie_file)
    found: list[str] = []
    seen_urls: set[str] = set()
    rejected: list[str] = []
    visited_pages: set[str] = set()
    page_url: str | None = url
    pages_scanned = 0

    while page_url and pages_scanned < max_pages:
        if page_url in visited_pages:
            break
        if not _same_site(url, page_url):
            rejected.append(page_url)
            break
        visited_pages.add(page_url)
        if progress:
            progress(f"Fetching favorites page {pages_scanned + 1}: {page_url}")

        request = Request(
            page_url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with opener.open(request, timeout=timeout) as response:
            content_type = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(content_type, errors="replace")
            final_url = response.geturl()

        page_links, next_url = extract_favorite_links(final_url, html)
        for candidate in page_links:
            if candidate in seen_urls:
                continue
            seen_urls.add(candidate)
            found.append(candidate)
        pages_scanned += 1

        if next_url and next_url not in visited_pages and pages_scanned < max_pages:
            if page_delay:
                time.sleep(page_delay)
            page_url = next_url
        else:
            page_url = None

    return FavoritesResult(
        source_url=url,
        pages_scanned=pages_scanned,
        urls=tuple(found),
        rejected=tuple(rejected),
    )


def write_url_file(path: Path, result: FavoritesResult) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    payload = "".join(f"{url}\n" for url in result.urls)
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(path)


def result_payload(result: FavoritesResult, output: Path, applied: bool) -> dict[str, object]:
    return {
        **asdict(result),
        "output": str(output),
        "applied": applied,
        "count": len(result.urls),
    }


def format_result(result: FavoritesResult, output: Path, applied: bool) -> str:
    action = "WROTE" if applied else "DRY-RUN"
    lines = [
        f"{action}: {len(result.urls)} URL(s) from {result.pages_scanned} page(s)",
        f"Source: {result.source_url}",
        f"Output: {output}",
    ]
    lines.extend(f"  {url}" for url in result.urls)
    if not applied:
        lines.append("Re-run with -f/--apply to write the URL file.")
    return "\n".join(lines)
