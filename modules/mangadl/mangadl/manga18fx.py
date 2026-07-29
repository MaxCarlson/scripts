from __future__ import annotations

import argparse
import http.cookiejar
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}
CONTENT_TYPE_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/bmp": ".bmp",
}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True, slots=True)
class Chapter:
    title: str
    url: str


class _SeriesParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ""
        self.chapters: list[Chapter] = []
        self._post_title_depth = 0
        self._collect_title = False
        self._title_parts: list[str] = []
        self._chapter_url: str | None = None
        self._chapter_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = _attributes(attrs)
        classes = _classes(attributes.get("class"))
        lowered = tag.lower()

        if lowered == "div":
            if self._post_title_depth > 0:
                self._post_title_depth += 1
            elif "post-title" in classes:
                self._post_title_depth = 1

        if lowered == "h1" and self._post_title_depth > 0 and not self.title:
            self._collect_title = True
            self._title_parts = []

        if lowered == "a" and "chapter-name" in classes and attributes.get("href"):
            self._chapter_url = urljoin(self.base_url, attributes["href"] or "")
            self._chapter_parts = []

    def handle_data(self, data: str) -> None:
        if self._collect_title:
            self._title_parts.append(data)
        if self._chapter_url is not None:
            self._chapter_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()

        if lowered == "h1" and self._collect_title:
            self.title = _collapse_space("".join(self._title_parts))
            self._collect_title = False
            self._title_parts = []

        if lowered == "a" and self._chapter_url is not None:
            title = _collapse_space("".join(self._chapter_parts)) or _slug_title(self._chapter_url)
            self.chapters.append(Chapter(title=title, url=self._chapter_url))
            self._chapter_url = None
            self._chapter_parts = []

        if lowered == "div" and self._post_title_depth > 0:
            self._post_title_depth -= 1


class _ChapterParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.images: list[str] = []
        self._read_content_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = _attributes(attrs)
        lowered = tag.lower()

        if lowered == "div":
            classes = _classes(attributes.get("class"))
            if self._read_content_depth > 0:
                self._read_content_depth += 1
            elif "read-content" in classes:
                self._read_content_depth = 1
            return

        if self._read_content_depth > 0 and lowered in {"source", "img"}:
            image_url = _image_attribute(attributes)
            if image_url:
                absolute = urljoin(self.base_url, image_url)
                if absolute not in self.images:
                    self.images.append(absolute)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "div" and self._read_content_depth > 0:
            self._read_content_depth -= 1


def _attributes(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {name.lower(): value or "" for name, value in attrs}


def _classes(value: str | None) -> set[str]:
    return set((value or "").split())


def _collapse_space(value: str) -> str:
    return " ".join(value.split())


def _first_srcset_url(value: str) -> str:
    candidate = value.split(",", 1)[0].strip()
    return candidate.split(None, 1)[0] if candidate else ""


def _image_attribute(attributes: dict[str, str]) -> str:
    for name in ("data-src", "data-lazy-src", "src"):
        value = attributes.get(name, "").strip()
        if value and not value.startswith("data:"):
            return value
    for name in ("data-srcset", "srcset"):
        value = _first_srcset_url(attributes.get(name, ""))
        if value and not value.startswith("data:"):
            return value
    return ""


def _slug_title(url: str) -> str:
    slug = unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    return _collapse_space(slug.replace("-", " ").replace("_", " ")).title() or "Manga18FX"


def sanitize_component(value: str, fallback: str = "untitled", max_length: int = 160) -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", _collapse_space(value)).strip(" .")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .")
    return cleaned or fallback


def parse_series(html: str, base_url: str) -> tuple[str, list[Chapter]]:
    parser = _SeriesParser(base_url)
    parser.feed(html)
    parser.close()
    title = parser.title or _slug_title(base_url)
    unique: dict[str, Chapter] = {}
    for chapter in parser.chapters:
        unique.setdefault(chapter.url, chapter)
    return title, sorted(unique.values(), key=_chapter_sort_key)


def parse_chapter_images(html: str, base_url: str) -> list[str]:
    parser = _ChapterParser(base_url)
    parser.feed(html)
    parser.close()
    return parser.images


def _chapter_number(chapter: Chapter) -> str | None:
    matches = re.findall(r"\d+(?:\.\d+)?", chapter.title)
    return matches[-1] if matches else None


def _chapter_sort_key(chapter: Chapter) -> tuple[int, float, str]:
    number = _chapter_number(chapter)
    if number is not None:
        return 0, float(number), chapter.title.casefold()
    return 1, float("inf"), chapter.title.casefold()


def _chapter_directory_name(chapter: Chapter, fallback_index: int) -> str:
    number = _chapter_number(chapter)
    if number is None:
        prefix = f"{fallback_index:04d}"
    else:
        whole, separator, fraction = number.partition(".")
        prefix = whole.zfill(4) + (separator + fraction if separator else "")
    return f"{prefix} - {sanitize_component(chapter.title, f'Chapter {fallback_index:04d}')}"


def _load_cookie_jar(path: Path | None) -> http.cookiejar.CookieJar:
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


def _request(opener: object, url: str, referer: str | None, timeout: float) -> BinaryIO:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(url, headers=headers)
    return opener.open(request, timeout=timeout)  # type: ignore[attr-defined,no-any-return]


def _read_text(opener: object, url: str, referer: str | None, timeout: float) -> str:
    with _request(opener, url, referer, timeout) as response:
        payload = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _image_suffix(url: str, content_type: str | None) -> str:
    suffix = Path(unquote(urlsplit(url).path)).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return ".jpg" if suffix == ".jpeg" else suffix
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    return CONTENT_TYPE_SUFFIXES.get(normalized, ".jpg")


def _download_image(
    opener: object,
    url: str,
    referer: str,
    target_without_suffix: Path,
    timeout: float,
) -> Path:
    existing = next(
        (
            target_without_suffix.with_suffix(suffix)
            for suffix in IMAGE_SUFFIXES
            if target_without_suffix.with_suffix(suffix).is_file()
            and target_without_suffix.with_suffix(suffix).stat().st_size > 0
        ),
        None,
    )
    if existing is not None:
        return existing

    with _request(opener, url, referer, timeout) as response:
        suffix = _image_suffix(url, response.headers.get("Content-Type"))
        target = target_without_suffix.with_suffix(suffix)
        temporary = target.with_suffix(target.suffix + ".part")
        target.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
        if temporary.stat().st_size == 0:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"downloaded an empty image: {url}")
        temporary.replace(target)
        return target


def download_series(
    url: str,
    destination: Path,
    *,
    existing_root: Path | None = None,
    cookies: Path | None = None,
    timeout: float = 45.0,
) -> tuple[Path, int, int]:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in {"manga18fx.com", "www.manga18fx.com"} or not parts.path.lower().startswith("/manga/"):
        raise ValueError(f"not a supported Manga18FX series URL: {url}")

    opener = build_opener(HTTPCookieProcessor(_load_cookie_jar(cookies)))
    series_html = _read_text(opener, url, None, timeout)
    title, chapters = parse_series(series_html, url)
    if not chapters:
        raise RuntimeError(f"no chapters were found on Manga18FX series page: {url}")

    if existing_root is None and destination.parent.name == "_partial":
        existing_root = destination.parent.parent

    series_name = sanitize_component(title, _slug_title(url))
    series_directory = destination / series_name
    existing_series_directory = existing_root / series_name if existing_root is not None else None
    downloaded = 0
    skipped = 0
    print(f"series={title!r} chapters={len(chapters)} destination={series_directory}", flush=True)

    for chapter_index, chapter in enumerate(chapters, start=1):
        chapter_html = _read_text(opener, chapter.url, url, timeout)
        images = parse_chapter_images(chapter_html, chapter.url)
        if not images:
            raise RuntimeError(f"no images were found for chapter {chapter.title!r}: {chapter.url}")

        chapter_directory_name = _chapter_directory_name(chapter, chapter_index)
        chapter_directory = series_directory / chapter_directory_name
        existing_chapter_directory = (
            existing_series_directory / chapter_directory_name if existing_series_directory is not None else None
        )
        print(
            f"chapter={chapter_index}/{len(chapters)} title={chapter.title!r} images={len(images)}",
            flush=True,
        )

        for image_index, image_url in enumerate(images, start=1):
            target_base = chapter_directory / f"{image_index:04d}"
            existed_in_partial = any(
                target_base.with_suffix(suffix).is_file() and target_base.with_suffix(suffix).stat().st_size > 0
                for suffix in IMAGE_SUFFIXES
            )
            existed_in_destination = existing_chapter_directory is not None and any(
                (existing_chapter_directory / f"{image_index:04d}").with_suffix(suffix).is_file()
                and (existing_chapter_directory / f"{image_index:04d}").with_suffix(suffix).stat().st_size > 0
                for suffix in IMAGE_SUFFIXES
            )
            if existed_in_destination:
                skipped += 1
                continue
            _download_image(opener, image_url, chapter.url, target_base, timeout)
            if existed_in_partial:
                skipped += 1
            else:
                downloaded += 1

    return series_directory, downloaded, skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download one complete Manga18FX series.")
    parser.add_argument("url", help="Manga18FX series-root URL.")
    parser.add_argument("-d", "--destination", type=Path, required=True, help="Output root directory.")
    parser.add_argument("-E", "--existing-root", type=Path, help="Existing library root used to skip downloaded files.")
    parser.add_argument("-C", "--cookies", type=Path, help="Netscape/Mozilla cookies file.")
    parser.add_argument("-t", "--timeout", type=float, default=45.0, help="HTTP timeout in seconds (default: 45).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than zero")
    try:
        series_directory, downloaded, skipped = download_series(
            args.url,
            args.destination.expanduser().resolve(),
            existing_root=args.existing_root.expanduser().resolve() if args.existing_root else None,
            cookies=args.cookies.expanduser().resolve() if args.cookies else None,
            timeout=args.timeout,
        )
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 1
    print(
        f"complete destination={series_directory} downloaded={downloaded} skipped={skipped}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
