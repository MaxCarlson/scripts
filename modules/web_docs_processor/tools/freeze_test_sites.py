#!/usr/bin/env python3
"""
Freeze real documentation sites into local HTML/XML fixtures for tests.

This script reads a plain-text URL file like:

    # single-page
    https://developers.openai.com/api/docs/guides/prompt-guidance

    # docs-site
    https://developers.openai.com/api/docs/guides

It captures each listed URL into its own fixture directory, optionally discovers
linked documentation pages, rewrites same-origin links to local frozen paths,
and writes a manifest.json describing the capture.

The generated fixtures are intended to be served by a local HTTP server during
tests. This avoids flaky live-network tests while preserving realistic HTML.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path
from typing import Literal
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

InputFormat = Literal[
    "single-page",
    "docs-site",
    "github-wiki",
    "github-pages",
    "sitemap",
]

INPUT_FORMATS = {
    "single-page",
    "docs-site",
    "github-wiki",
    "github-pages",
    "sitemap",
}

NAV_SELECTORS = [
    "nav",
    "aside",
    "[role='navigation']",
    "[class*='sidebar']",
    "[class*='side-bar']",
    "[class*='toc']",
    "[class*='table-of-contents']",
    "[class*='docs-nav']",
    "[class*='docs-sidebar']",
    "[class*='menu']",
]

DEFAULT_USER_AGENT = (
    "web-docs-processor-freezer/0.1.0 " "(test fixture capture; respectful crawling)"
)

GITHUB_WIKI_BLOCKED_PAGE_NAMES = {
    "_edit",
    "_history",
    "_new",
    "_pages",
}
GITHUB_WIKI_MIN_PARTS = 3
GITHUB_WIKI_PAGE_INDEX = 3


@dataclasses.dataclass(frozen=True)
class SeedUrl:
    input_format: InputFormat
    url: str
    line_number: int


@dataclasses.dataclass(frozen=True)
class CapturedPage:
    original_url: str
    final_url: str
    local_path: str
    status_code: int | None
    content_type: str
    sha256: str
    discovered_from: str | None


@dataclasses.dataclass(frozen=True)
class FreezeConfig:
    url_file: Path
    output_dir: Path
    max_pages: int
    timeout_seconds: float
    delay_seconds: float
    render_js: bool
    user_agent: str
    keep_query: bool
    scope: str
    same_prefix_depth: int | None
    overwrite: bool


def normalize_url(url: str, keep_query: bool = False) -> str:
    cleaned, _fragment = urldefrag(url.strip())
    parsed = urlparse(cleaned)

    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    path = re.sub(r"/{2,}", "/", path)
    query = parsed.query if keep_query else ""

    normalized = urlunparse((scheme, netloc, path, "", query, ""))
    if normalized.endswith("/") and path != "/":
        normalized = normalized[:-1]

    return normalized


def slugify(value: str, fallback: str = "item") -> str:
    value = value.strip().lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or fallback


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_url_file(path: Path, keep_query: bool) -> list[SeedUrl]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"Could not read URL file: {path}") from exc

    current_format: InputFormat | None = None
    seeds: list[SeedUrl] = []

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#"):
            label = line.lstrip("#").strip().lower()
            label = label.split()[0] if label else ""
            if label in INPUT_FORMATS:
                current_format = label  # type: ignore[assignment]
            continue

        if current_format is None:
            raise RuntimeError(
                f"URL appears before an input-format section on line {line_number}: {line}"
            )

        parsed = urlparse(line)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"Invalid URL on line {line_number}: {line}")

        seeds.append(
            SeedUrl(
                input_format=current_format,
                url=normalize_url(line, keep_query=keep_query),
                line_number=line_number,
            )
        )

    if not seeds:
        raise RuntimeError(f"No URLs found in URL file: {path}")

    return seeds


def default_scope_for_format(input_format: InputFormat, explicit_scope: str) -> str:
    if explicit_scope != "auto":
        return explicit_scope

    if input_format == "single-page":
        return "single"

    if input_format == "sitemap":
        return "domain"

    return "prefix"


def default_prefix_depth(
    seed_url: str, input_format: InputFormat, explicit_depth: int | None
) -> int:
    if explicit_depth is not None:
        return explicit_depth

    path_parts = [part for part in urlparse(seed_url).path.split("/") if part]

    if input_format == "single-page":
        return len(path_parts)

    if input_format == "github-wiki":
        return 2

    if path_parts and path_parts[0] in {"docs", "documentation"}:
        return 1

    return max(1, min(2, len(path_parts)))


def url_prefix(url: str, depth: int) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    prefix_parts = parts[: max(depth, 0)]
    prefix_path = "/" + "/".join(prefix_parts)

    if prefix_path != "/" and not prefix_path.endswith("/"):
        prefix_path += "/"

    return urlunparse((parsed.scheme, parsed.netloc, prefix_path, "", "", ""))


def is_in_scope(
    candidate_url: str, seed_url: str, scope: str, prefix_depth: int
) -> bool:
    candidate = urlparse(candidate_url)
    seed = urlparse(seed_url)

    if candidate.scheme not in {"http", "https"}:
        return False

    if candidate.netloc != seed.netloc:
        return False

    if scope == "domain":
        return True

    if scope == "single":
        return normalize_url(candidate_url) == normalize_url(seed_url)

    if scope == "prefix":
        prefix = urlparse(url_prefix(seed_url, prefix_depth)).path
        return candidate.path == prefix.rstrip("/") or candidate.path.startswith(prefix)

    return False


def is_github_wiki_url(candidate_url: str, seed_url: str) -> bool:
    candidate = urlparse(candidate_url)
    seed = urlparse(seed_url)
    seed_parts = [part for part in seed.path.split("/") if part]
    candidate_parts = [part for part in candidate.path.split("/") if part]
    has_seed_wiki_root = len(seed_parts) >= GITHUB_WIKI_MIN_PARTS and seed_parts[2].lower() == "wiki"
    has_candidate_wiki_root = (
        len(candidate_parts) >= GITHUB_WIKI_MIN_PARTS
        and candidate_parts[0].lower() == seed_parts[0].lower()
        and candidate_parts[1].lower() == seed_parts[1].lower()
        and candidate_parts[2].lower() == "wiki"
    )
    is_blocked_wiki_page = (
        len(candidate_parts) > GITHUB_WIKI_PAGE_INDEX
        and candidate_parts[GITHUB_WIKI_PAGE_INDEX].lower() in GITHUB_WIKI_BLOCKED_PAGE_NAMES
    )

    return (
        candidate.scheme in {"http", "https"}
        and candidate.netloc.lower() == "github.com"
        and candidate.netloc.lower() == seed.netloc.lower()
        and has_seed_wiki_root
        and has_candidate_wiki_root
        and not is_blocked_wiki_page
    )


def is_allowed_candidate_url(
    candidate_url: str,
    seed_url: str,
    input_format: InputFormat,
    scope: str,
    prefix_depth: int,
) -> bool:
    if input_format == "github-wiki":
        return is_github_wiki_url(candidate_url, seed_url)

    return is_in_scope(candidate_url, seed_url, scope, prefix_depth)


def is_probably_page_url(url: str) -> bool:
    path = urlparse(url).path.lower()

    blocked_extensions = (
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".ico",
        ".css",
        ".js",
        ".json",
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".mp4",
        ".mov",
        ".webm",
        ".mp3",
        ".wav",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
    )

    return not path.endswith(blocked_extensions)


def is_sitemap_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return "sitemap" in path or path.endswith(".xml")


def fixture_site_name(seed: SeedUrl) -> str:
    parsed = urlparse(seed.url)
    host = slugify(parsed.netloc.removeprefix("www."), fallback="site")
    path = slugify(parsed.path, fallback="root")
    return f"{seed.input_format}__{host}__{path}"[:140]


def local_path_for_url(url: str, used_paths: set[str]) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"

    if path.endswith("/"):
        path = f"{path}index.html"

    suffix = Path(path).suffix.lower()
    if not suffix:
        path = f"{path}.html"
    elif suffix in {".xml"}:
        pass
    elif suffix not in {".html", ".htm", ".xhtml"}:
        path = f"{path}.html"

    path = path.lstrip("/")
    if not path:
        path = "index.html"

    if parsed.query:
        query_slug = slugify(parsed.query, fallback="query")
        current = Path(path)
        path = str(
            current.with_name(f"{current.stem}__{query_slug}{current.suffix}")
        ).replace("\\", "/")

    candidate = path
    counter = 2
    while candidate in used_paths:
        current = Path(path)
        candidate = str(
            current.with_name(f"{current.stem}-{counter}{current.suffix}")
        ).replace("\\", "/")
        counter += 1

    used_paths.add(candidate)
    return candidate


def request_text(url: str, config: FreezeConfig) -> tuple[str, int | None, str, str]:
    headers = {
        "User-Agent": config.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/xml;q=0.8,*/*;q=0.7",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=config.timeout_seconds,
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    return response.text, response.status_code, content_type, response.url


def render_text_with_playwright(
    url: str, config: FreezeConfig
) -> tuple[str, int | None, str, str]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run the normal editable install or: wdp setup-browsers"
        ) from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(user_agent=config.user_agent)
        page = context.new_page()
        response = page.goto(
            url, wait_until="networkidle", timeout=int(config.timeout_seconds * 1000)
        )
        page.wait_for_timeout(500)

        rendered_html = page.content()
        final_url = page.url
        status_code = response.status if response is not None else None
        content_type = (
            response.headers.get("content-type", "")
            if response is not None
            else "text/html"
        )

        browser.close()

    return rendered_html, status_code, content_type, final_url


def fetch_text(
    url: str, input_format: InputFormat, config: FreezeConfig
) -> tuple[str, int | None, str, str]:
    if input_format == "sitemap" or is_sitemap_url(url):
        return request_text(url, config)

    if config.render_js:
        return render_text_with_playwright(url, config)

    return request_text(url, config)


def discover_sitemap_links(
    xml_text: str,
    base_url: str,
    seed_url: str,
    input_format: InputFormat,
    scope: str,
    prefix_depth: int,
) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        soup = BeautifulSoup(xml_text, "xml")
        for loc in soup.find_all("loc"):
            candidate = normalize_url(urljoin(base_url, loc.get_text(strip=True)))
            if candidate not in seen and is_allowed_candidate_url(
                candidate, seed_url, input_format, scope, prefix_depth
            ):
                seen.add(candidate)
                links.append(candidate)
        return links

    for element in root.iter():
        if element.tag.endswith("loc") and element.text:
            candidate = normalize_url(urljoin(base_url, element.text.strip()))
            if candidate not in seen and is_allowed_candidate_url(
                candidate, seed_url, input_format, scope, prefix_depth
            ):
                seen.add(candidate)
                links.append(candidate)

    return links


def discover_html_links(
    html_text: str,
    base_url: str,
    seed_url: str,
    input_format: InputFormat,
    scope: str,
    prefix_depth: int,
) -> list[str]:
    soup = BeautifulSoup(html_text, "lxml")

    containers = []
    for selector in NAV_SELECTORS:
        containers.extend(soup.select(selector))

    if not containers:
        containers = [soup]

    links: list[str] = []
    seen: set[str] = set()

    for container in containers:
        for anchor in container.find_all("a", href=True):
            candidate = normalize_url(urljoin(base_url, anchor["href"]))
            if candidate in seen:
                continue
            if not is_probably_page_url(candidate):
                continue
            if not is_allowed_candidate_url(candidate, seed_url, input_format, scope, prefix_depth):
                continue

            seen.add(candidate)
            links.append(candidate)

    return links


def discover_links(
    content: str,
    current_url: str,
    seed_url: str,
    input_format: InputFormat,
    scope: str,
    prefix_depth: int,
) -> list[str]:
    if input_format == "single-page":
        return []

    if input_format == "sitemap" and is_sitemap_url(current_url):
        return discover_sitemap_links(
            content, current_url, seed_url, input_format, scope, prefix_depth
        )

    return discover_html_links(content, current_url, seed_url, input_format, scope, prefix_depth)


def rewrite_html_links(
    content: str, original_url: str, url_to_local_path: dict[str, str]
) -> str:
    soup = BeautifulSoup(content, "lxml")

    attributes = [
        ("a", "href"),
        ("link", "href"),
        ("script", "src"),
        ("img", "src"),
        ("source", "src"),
        ("iframe", "src"),
    ]

    for tag_name, attribute in attributes:
        for tag in soup.find_all(tag_name):
            value = tag.get(attribute)
            if not isinstance(value, str) or not value.strip():
                continue

            absolute_url = normalize_url(urljoin(original_url, value))
            local_path = url_to_local_path.get(absolute_url)
            if local_path:
                tag[attribute] = "/" + local_path

    return str(soup)


def rewrite_sitemap_locs(content: str, url_to_local_path: dict[str, str]) -> str:
    for original_url, local_path in sorted(
        url_to_local_path.items(), key=lambda item: len(item[0]), reverse=True
    ):
        content = content.replace(html.escape(original_url), "/" + local_path)
        content = content.replace(original_url, "/" + local_path)

    return content


def write_capture_file(site_dir: Path, local_path: str, content: str) -> Path:
    output_path = site_dir / local_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def capture_seed(seed: SeedUrl, config: FreezeConfig) -> Path:
    site_name = fixture_site_name(seed)
    site_dir = config.output_dir / site_name

    if site_dir.exists() and any(site_dir.iterdir()) and not config.overwrite:
        raise RuntimeError(
            f"Output fixture directory already exists and is not empty: {site_dir}. "
            "Use --overwrite to replace it."
        )

    site_dir.mkdir(parents=True, exist_ok=True)

    scope = default_scope_for_format(seed.input_format, config.scope)
    prefix_depth = default_prefix_depth(
        seed.url, seed.input_format, config.same_prefix_depth
    )
    effective_max_pages = 1 if seed.input_format == "single-page" else config.max_pages

    queue: deque[tuple[str, str | None]] = deque([(seed.url, None)])
    visited: set[str] = set()
    queued: set[str] = {seed.url}
    raw_content_by_url: dict[str, str] = {}
    captured_pages: list[CapturedPage] = []
    used_paths: set[str] = set()
    url_to_local_path: dict[str, str] = {}

    while queue and len(visited) < effective_max_pages:
        current_url, discovered_from = queue.popleft()
        queued.discard(current_url)

        if current_url in visited:
            continue

        visited.add(current_url)

        try:
            content, status_code, content_type, final_url = fetch_text(
                current_url, seed.input_format, config
            )
        except Exception as exc:
            print(f"[warn] failed to capture {current_url}: {exc}", file=sys.stderr)
            continue

        normalized_final_url = normalize_url(final_url, keep_query=config.keep_query)
        local_path = local_path_for_url(normalized_final_url, used_paths)
        url_to_local_path[current_url] = local_path
        url_to_local_path[normalized_final_url] = local_path
        raw_content_by_url[normalized_final_url] = content

        captured_pages.append(
            CapturedPage(
                original_url=current_url,
                final_url=normalized_final_url,
                local_path=local_path,
                status_code=status_code,
                content_type=content_type,
                sha256=sha256_text(content),
                discovered_from=discovered_from,
            )
        )

        print(
            f"[ok] {seed.input_format} {len(captured_pages):03d} {current_url}",
            file=sys.stderr,
        )

        links = discover_links(
            content=content,
            current_url=normalized_final_url,
            seed_url=seed.url,
            input_format=seed.input_format,
            scope=scope,
            prefix_depth=prefix_depth,
        )

        for link in links:
            if link in visited or link in queued:
                continue
            queue.append((link, normalized_final_url))
            queued.add(link)

        if config.delay_seconds > 0:
            time.sleep(config.delay_seconds)

    for page in captured_pages:
        content = raw_content_by_url[page.final_url]

        if seed.input_format == "sitemap" and is_sitemap_url(page.final_url):
            rewritten = rewrite_sitemap_locs(content, url_to_local_path)
        else:
            rewritten = rewrite_html_links(content, page.final_url, url_to_local_path)

        write_capture_file(site_dir, page.local_path, rewritten)

    manifest = {
        "schema_version": 1,
        "site_name": site_name,
        "input_format": seed.input_format,
        "seed_url": seed.url,
        "seed_line_number": seed.line_number,
        "scope": scope,
        "same_prefix_depth": prefix_depth,
        "max_pages": effective_max_pages,
        "render_js": config.render_js,
        "captured_page_count": len(captured_pages),
        "entry_local_path": captured_pages[0].local_path if captured_pages else None,
        "entry_local_url_hint": (
            "/" + captured_pages[0].local_path if captured_pages else None
        ),
        "pages": [dataclasses.asdict(page) for page in captured_pages],
        "url_to_local_path": url_to_local_path,
    }

    (site_dir / "fixture-manifest.json").write_text(
        json.dumps(manifest, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return site_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="freeze-test-sites",
        description="Freeze real documentation sites into local test fixtures.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--url-file",
        "-F",
        required=True,
        help="Input URL file. Section comments like '# docs-site' select the input format for following URLs.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default="tests/fixtures/frozen_sites",
        help="Directory where frozen fixture sites will be written.",
    )
    parser.add_argument(
        "--max-pages",
        "-m",
        type=int,
        default=25,
        help="Maximum pages to capture per seed. single-page inputs always capture one page.",
    )
    parser.add_argument(
        "--timeout-seconds",
        "-T",
        type=float,
        default=45.0,
        help="HTTP or Playwright timeout per page.",
    )
    parser.add_argument(
        "--delay-seconds",
        "-d",
        type=float,
        default=0.35,
        help="Delay between captured pages.",
    )
    parser.add_argument(
        "--render-js",
        "-j",
        action="store_true",
        default=True,
        help="Render HTML pages with Playwright Chromium before saving.",
    )
    parser.add_argument(
        "--no-render-js",
        "-J",
        dest="render_js",
        action="store_false",
        help="Use requests instead of Playwright for HTML pages.",
    )
    parser.add_argument(
        "--user-agent",
        "-a",
        default=DEFAULT_USER_AGENT,
        help="User-Agent for requests and Playwright.",
    )
    parser.add_argument(
        "--keep-query",
        "-q",
        action="store_true",
        help="Keep query strings in URL identity and local path generation.",
    )
    parser.add_argument(
        "--scope",
        "-s",
        choices=["auto", "single", "prefix", "domain"],
        default="auto",
        help="Capture scope. auto chooses single for single-page, domain for sitemap, prefix otherwise.",
    )
    parser.add_argument(
        "--same-prefix-depth",
        "-p",
        type=int,
        default=None,
        help="Path depth for prefix scoping. Omit for format-specific defaults.",
    )
    parser.add_argument(
        "--overwrite",
        "-w",
        action="store_true",
        help="Overwrite existing fixture directories.",
    )

    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> FreezeConfig:
    return FreezeConfig(
        url_file=Path(args.url_file).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        max_pages=args.max_pages,
        timeout_seconds=args.timeout_seconds,
        delay_seconds=args.delay_seconds,
        render_js=args.render_js,
        user_agent=args.user_agent,
        keep_query=args.keep_query,
        scope=args.scope,
        same_prefix_depth=args.same_prefix_depth,
        overwrite=args.overwrite,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = build_config(args)

    seeds = parse_url_file(config.url_file, keep_query=config.keep_query)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    fixture_dirs: list[str] = []
    failures = 0

    for seed in seeds:
        try:
            fixture_dir = capture_seed(seed, config)
            fixture_dirs.append(str(fixture_dir.as_posix()))
        except Exception as exc:  # noqa: PERF203
            failures += 1
            print(f"[fail] {seed.url}: {exc}", file=sys.stderr)

    batch_manifest = {
        "schema_version": 1,
        "url_file": str(config.url_file.as_posix()),
        "output_dir": str(config.output_dir.as_posix()),
        "seed_count": len(seeds),
        "failure_count": failures,
        "fixture_dirs": fixture_dirs,
    }

    batch_manifest_path = config.output_dir / "freeze-batch-manifest.json"
    batch_manifest_path.write_text(
        json.dumps(batch_manifest, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("", file=sys.stderr)
    print(f"Wrote batch manifest: {batch_manifest_path}", file=sys.stderr)
    print(f"Captured fixture dirs: {len(fixture_dirs)}", file=sys.stderr)

    if failures:
        print(f"Failed seeds: {failures}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
