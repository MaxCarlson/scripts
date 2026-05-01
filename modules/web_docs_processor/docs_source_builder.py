#!/usr/bin/env python3
"""
Build retrieval-friendly source packs from documentation websites.

The main output format is Markdown because it preserves headings, links, code
blocks, and page boundaries in a compact text-first format suitable for LLM
retrieval systems. JSON is useful for post-processing. PDF output is supported
as an optional export format through ReportLab.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html
import json
import re
import subprocess
import sys
import time
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Literal
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import requests
import trafilatura
from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_markdown

try:
    from web_docs_processor import __version__
except ImportError:
    __version__ = "0.1.0"


DEFAULT_USER_AGENT = (
    "web-docs-processor/0.3.3 "
    "(personal archival and LLM source preparation; respectful crawling)"
)
MIN_EXTRACTED_TEXT_CHARS = 300

REQUIRED_IMPORTS = [
    "bs4",
    "lxml",
    "markdownify",
    "requests",
    "trafilatura",
]

FULL_FEATURE_IMPORTS = [
    "playwright",
    "reportlab",
]

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

CONTENT_SELECTORS = [
    "main",
    "article",
    "[role='main']",
    "[class*='content']",
    "[class*='markdown']",
    "[class*='prose']",
    "[class*='docs-content']",
    "[class*='doc-content']",
]

InputFormat = Literal[
    "auto",
    "single-page",
    "docs-site",
    "github-wiki",
    "github-pages",
    "sitemap",
]

OutputFormat = Literal[
    "markdown",
    "json",
    "pdf",
]

UrlFileMode = Literal[
    "exact",
    "expand",
]

INPUT_FORMATS = {
    "auto",
    "single-page",
    "docs-site",
    "github-wiki",
    "github-pages",
    "sitemap",
}

GITHUB_WIKI_BLOCKED_PAGE_NAMES = {
    "_edit",
    "_history",
    "_new",
    "_pages",
}
GITHUB_WIKI_MIN_PARTS = 3
GITHUB_WIKI_PAGE_INDEX = 3


@dataclasses.dataclass(frozen=True)
class PageResult:
    url: str
    title: str
    markdown: str
    source_index: int
    status_code: int | None
    content_sha256: str
    extracted_by: str


@dataclasses.dataclass(frozen=True)
class CrawlConfig:
    urls: list[str]
    output_path: Path
    output_format: OutputFormat
    title: str
    input_format: InputFormat
    scope: str
    include_patterns: list[re.Pattern[str]]
    exclude_patterns: list[re.Pattern[str]]
    max_pages: int
    delay_seconds: float
    timeout_seconds: float
    split_pages: bool
    dry_run: bool
    render_js: bool
    user_agent: str
    min_chars: int
    same_prefix_depth: int
    keep_query: bool
    write_manifest: bool
    write_candidates: bool
    url_file: Path | None = None
    url_file_mode: UrlFileMode | None = None
    batch_seed_url: str | None = None

    @property
    def output_dir(self) -> Path:
        if self.output_path.suffix:
            return self.output_path.parent

        return self.output_path


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


def url_prefix(url: str, depth: int) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    prefix_parts = parts[: max(depth, 0)]
    prefix_path = "/" + "/".join(prefix_parts)

    if prefix_path != "/" and not prefix_path.endswith("/"):
        prefix_path += "/"

    return urlunparse((parsed.scheme, parsed.netloc, prefix_path, "", "", ""))


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


def pattern_strings(patterns: list[re.Pattern[str]]) -> list[str]:
    return [pattern.pattern for pattern in patterns]


def matches_any(patterns: list[re.Pattern[str]], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def is_probably_documentation_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()

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
        ".xml",
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".mp4",
        ".mov",
        ".webm",
        ".mp3",
        ".wav",
    )

    if path.endswith(blocked_extensions):
        return False

    return parsed.scheme in {"http", "https"}


def is_sitemap_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return parsed.scheme in {"http", "https"} and ("sitemap" in path or path.endswith(".xml"))


def infer_input_format(urls: list[str], explicit_input_format: InputFormat) -> InputFormat:
    if explicit_input_format != "auto":
        return explicit_input_format

    first_url = urls[0] if urls else ""
    parsed = urlparse(first_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if host == "github.com" and "/wiki" in path:
        return "github-wiki"

    if host.endswith("github.io"):
        return "github-pages"

    if path.endswith("sitemap.xml") or "sitemap" in path:
        return "sitemap"

    return "docs-site"


def coerce_input_format(value: str) -> InputFormat:
    if value in INPUT_FORMATS:
        return value  # type: ignore[return-value]
    return "auto"


def default_scope_for_input_format(input_format: InputFormat, explicit_scope: str | None) -> str:
    if explicit_scope:
        return explicit_scope

    if input_format == "single-page":
        return "single"

    if input_format in {"github-wiki", "github-pages", "docs-site"}:
        return "prefix"

    if input_format == "sitemap":
        return "domain"

    return "prefix"


def default_same_prefix_depth(urls: list[str], input_format: InputFormat, explicit_depth: int | None) -> int:
    if explicit_depth is not None:
        return explicit_depth

    first_url = urls[0] if urls else ""
    path_parts = [part for part in urlparse(first_url).path.split("/") if part]

    if input_format == "single-page":
        return len(path_parts)

    if input_format == "github-wiki":
        return 2

    if path_parts and path_parts[0] in {"docs", "documentation"}:
        return 1

    return max(1, min(2, len(path_parts)))


def default_max_pages_for_input_format(input_format: InputFormat, explicit_max_pages: int | None) -> int:
    if explicit_max_pages is not None:
        return explicit_max_pages

    defaults = {
        "single-page": 1,
        "docs-site": 300,
        "github-wiki": 200,
        "github-pages": 300,
        "sitemap": 500,
        "auto": 300,
    }
    return defaults[input_format]


def default_render_js_for_input_format(input_format: InputFormat, explicit_render_js: bool | None) -> bool:
    if explicit_render_js is not None:
        return explicit_render_js

    return input_format in {"docs-site", "github-pages"}


def in_scope(candidate_url: str, seed_urls: list[str], scope: str, same_prefix_depth: int) -> bool:
    candidate = urlparse(candidate_url)

    for seed_url in seed_urls:
        seed = urlparse(seed_url)

        if candidate.netloc != seed.netloc:
            continue

        if scope == "domain":
            return True

        if scope == "prefix":
            prefix = urlparse(url_prefix(seed_url, same_prefix_depth)).path
            if candidate.path == prefix.rstrip("/") or candidate.path.startswith(prefix):
                return True
            continue

        if scope == "single":
            if normalize_url(candidate_url) == normalize_url(seed_url):
                return True
            continue

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
    seed_urls: list[str],
    input_format: InputFormat,
    scope: str,
    same_prefix_depth: int,
) -> bool:
    if input_format == "github-wiki":
        return any(is_github_wiki_url(candidate_url, seed_url) for seed_url in seed_urls)

    return in_scope(candidate_url, seed_urls, scope, same_prefix_depth)


def should_keep_url(candidate_url: str, config: CrawlConfig) -> bool:
    if config.input_format == "sitemap" and is_sitemap_url(candidate_url):
        allowed_url_type = True
    else:
        allowed_url_type = is_probably_documentation_url(candidate_url)

    if not allowed_url_type:
        return False

    if not is_allowed_candidate_url(
        candidate_url,
        config.urls,
        config.input_format,
        config.scope,
        config.same_prefix_depth,
    ):
        return False

    if config.input_format == "sitemap" and is_sitemap_url(candidate_url):
        return True

    if config.include_patterns and not matches_any(config.include_patterns, candidate_url):
        return False

    return not (config.exclude_patterns and matches_any(config.exclude_patterns, candidate_url))


def request_html(url: str, config: CrawlConfig) -> tuple[str, int | None]:
    headers = {
        "User-Agent": config.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=config.timeout_seconds,
    )
    response.raise_for_status()

    return response.text, response.status_code


def render_html_with_playwright(url: str, config: CrawlConfig) -> tuple[str, int | None]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run the normal editable install again, "
            "or repair browser support with: wdp setup-browsers"
        ) from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(user_agent=config.user_agent)
            response = page.goto(url, wait_until="networkidle", timeout=int(config.timeout_seconds * 1000))
            page.wait_for_timeout(500)
            rendered_html = page.content()
            status_code = response.status if response is not None else None
            browser.close()
    except Exception as exc:
        raise RuntimeError(
            "Playwright Chromium could not start. Run: wdp setup-browsers"
        ) from exc

    return rendered_html, status_code


def fetch_html(url: str, config: CrawlConfig) -> tuple[str, int | None]:
    if config.render_js:
        return render_html_with_playwright(url, config)

    return request_html(url, config)


def soup_from_html(page_html: str) -> BeautifulSoup:
    return BeautifulSoup(page_html, "lxml")


def extract_title(soup: BeautifulSoup, url: str) -> str:
    h1 = soup.find("h1")
    if h1:
        title = " ".join(h1.get_text(" ", strip=True).split())
        if title:
            return html.unescape(title)

    if soup.title and soup.title.string:
        title = " ".join(soup.title.string.strip().split())
        if title:
            return html.unescape(title)

    parsed = urlparse(url)
    fallback = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
    return fallback.replace("-", " ").replace("_", " ").title()


def clean_soup_for_markdown(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup.find_all(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()

    for tag in soup.find_all(["button", "form", "iframe"]):
        tag.decompose()

    return soup


def select_content_html(soup: BeautifulSoup) -> str:
    clean_soup_for_markdown(soup)

    for selector in CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node:
            text = node.get_text(" ", strip=True)
            if len(text) >= MIN_EXTRACTED_TEXT_CHARS:
                return str(node)

    body = soup.body
    if body:
        return str(body)

    return str(soup)


def extract_markdown(page_html: str, url: str) -> tuple[str, str]:
    soup = soup_from_html(page_html)
    title = extract_title(soup, url)

    extracted = trafilatura.extract(
        page_html,
        url=url,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        include_links=True,
        favor_precision=False,
        favor_recall=True,
    )

    if extracted and len(extracted.strip()) >= MIN_EXTRACTED_TEXT_CHARS:
        return title, normalize_markdown(extracted.strip())

    content_html = select_content_html(soup)
    markdown = html_to_markdown(
        content_html,
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"],
    )

    return title, normalize_markdown(markdown)


def normalize_markdown(markdown: str) -> str:
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    return markdown.strip()


def discover_links_from_selectors(
    soup: BeautifulSoup,
    base_url: str,
    selectors: list[str],
    config: CrawlConfig,
) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()

    for selector in selectors:
        for container in soup.select(selector):
            for anchor in container.find_all("a", href=True):
                candidate = normalize_url(
                    urljoin(base_url, anchor["href"]),
                    keep_query=config.keep_query,
                )
                if candidate in seen:
                    continue
                if should_keep_url(candidate, config):
                    links.append(candidate)
                    seen.add(candidate)

    return links


def discover_all_links(soup: BeautifulSoup, base_url: str, config: CrawlConfig) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        candidate = normalize_url(
            urljoin(base_url, anchor["href"]),
            keep_query=config.keep_query,
        )
        if candidate in seen:
            continue
        if should_keep_url(candidate, config):
            links.append(candidate)
            seen.add(candidate)

    return links


def discover_sitemap_links(page_xml: str, base_url: str, config: CrawlConfig) -> list[str]:
    soup = BeautifulSoup(page_xml, "xml")
    links: list[str] = []
    seen: set[str] = set()

    for loc in soup.find_all("loc"):
        loc_text = loc.get_text(strip=True)
        if not loc_text:
            continue

        candidate = normalize_url(
            urljoin(base_url, loc_text),
            keep_query=config.keep_query,
        )
        if candidate in seen:
            continue
        if should_keep_url(candidate, config):
            links.append(candidate)
            seen.add(candidate)

    return links


def discover_next_links(page_html: str, base_url: str, config: CrawlConfig) -> list[str]:
    if config.input_format == "sitemap" and is_sitemap_url(base_url):
        return discover_sitemap_links(page_html, base_url, config)

    soup = soup_from_html(page_html)

    nav_links = discover_links_from_selectors(soup, base_url, NAV_SELECTORS, config)
    if nav_links:
        return nav_links

    return discover_all_links(soup, base_url, config)


def slugify(value: str, fallback: str = "page") -> str:
    value = value.strip().lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or fallback


def title_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    label = " ".join(parts[:2]) if parts else host
    title = f"{host} {label}".replace("-", " ").replace("_", " ").title()
    return re.sub(r"\s+", " ", title).strip()


def default_output_path(
    urls: list[str],
    output_format: OutputFormat,
    dry_run: bool,
    explicit_output: str | None,
) -> Path:
    if explicit_output:
        output_path = Path(explicit_output).expanduser().resolve()
        if dry_run and not output_path.suffix:
            return output_path / "candidate-urls.txt"
        return output_path

    first_url = urls[0] if urls else "docs"
    parsed = urlparse(first_url)
    path_slug = slugify(parsed.path, fallback="docs")
    host_slug = slugify(parsed.netloc.removeprefix("www."), fallback="site")
    base_name = f"{host_slug}-{path_slug}"

    if dry_run:
        return (Path.cwd() / "out" / f"{base_name}-candidates.txt").resolve()

    suffix_by_format = {
        "markdown": ".md",
        "json": ".json",
        "pdf": ".pdf",
    }
    return (Path.cwd() / "out" / f"{base_name}{suffix_by_format[output_format]}").resolve()


def default_url_file_output_path(
    url_file: str | Path,
    output_format: OutputFormat,
    mode: UrlFileMode,
    explicit_output: str | None,
) -> Path:
    if explicit_output:
        return Path(explicit_output).expanduser().resolve()

    stem = Path(url_file).stem or "sources"

    if mode == "expand":
        return (Path.cwd() / "out" / stem).resolve()

    suffix_by_format = {
        "markdown": ".md",
        "json": ".json",
        "pdf": ".pdf",
    }
    return (Path.cwd() / "out" / f"{stem}{suffix_by_format[output_format]}").resolve()


def output_path_for_seed(output_dir: Path, seed_url: str, output_format: OutputFormat) -> Path:
    parsed = urlparse(seed_url)
    host_slug = slugify(parsed.netloc.removeprefix("www."), fallback="site")
    path_slug = slugify(parsed.path, fallback="docs")
    suffix_by_format = {
        "markdown": ".md",
        "json": ".json",
        "pdf": ".pdf",
    }
    return output_dir / f"{host_slug}-{path_slug}{suffix_by_format[output_format]}"


def unique_output_path(output_path: Path, used_paths: set[Path]) -> Path:
    candidate = output_path
    counter = 2

    while candidate in used_paths:
        candidate = output_path.with_name(f"{output_path.stem}-{counter}{output_path.suffix}")
        counter += 1

    used_paths.add(candidate)
    return candidate


def read_url_file(url_file: str | Path, keep_query: bool = False) -> list[str]:
    path = Path(url_file).expanduser().resolve()

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"Could not read URL file: {path}") from exc

    urls: list[str] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parsed = urlparse(line)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"URL file contains an invalid URL on line {line_number}: {line}")

        urls.append(normalize_url(line, keep_query=keep_query))

    if not urls:
        raise RuntimeError(f"URL file did not contain any URLs: {path}")

    return urls


def read_manifest(manifest_path: str | Path) -> dict[str, object]:
    path = Path(manifest_path).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Could not read manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Manifest is not valid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"Manifest root must be a JSON object: {path}")

    return payload


def manifest_string_list(payload: dict[str, object], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def manifest_str(payload: dict[str, object], key: str, default: str) -> str:
    value = payload.get(key)
    return str(value) if value else default


def manifest_int(payload: dict[str, object], key: str, default: int) -> int:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def manifest_float(payload: dict[str, object], key: str, default: float) -> float:
    value = payload.get(key)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def manifest_bool(payload: dict[str, object], key: str, default: bool | None) -> bool | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def page_filename(index: int, title: str, url: str) -> str:
    parsed = urlparse(url)
    path_name = slugify(parsed.path, fallback=slugify(title, fallback="page"))
    title_name = slugify(title, fallback=path_name)

    name = title_name if title_name and title_name != "page" else path_name

    return f"{index:03d}-{name[:80]}.md"


def markdown_page_block(page: PageResult) -> str:
    source_comment = (
        f"<!-- source_url: {page.url} -->\n"
        f"<!-- source_index: {page.source_index} -->\n"
        f"<!-- content_sha256: {page.content_sha256} -->\n"
        f"<!-- extracted_by: {page.extracted_by} -->"
    )

    title = page.title.strip() or page.url

    return (
        "\n\n---\n\n"
        f"# {title}\n\n"
        f"{source_comment}\n\n"
        f"Source: {page.url}\n\n"
        f"{page.markdown}\n"
    )


def combined_markdown(pages: list[PageResult], title: str) -> str:
    toc_lines = [
        f"# {title}",
        "",
        "This document was generated from documentation web pages for LLM retrieval use.",
        "",
        "## Source Table of Contents",
        "",
    ]

    for page in pages:
        anchor = slugify(page.title)
        toc_lines.append(f"- [{page.source_index:03d}. {page.title}](#{anchor})")
        toc_lines.append(f"  - Source: {page.url}")

    content = "\n".join(toc_lines)

    for page in pages:
        content += markdown_page_block(page)

    return content.strip() + "\n"


def pages_to_json_payload(
    pages: list[PageResult],
    discovered_urls: list[str],
    config: CrawlConfig,
) -> dict[str, object]:
    return {
        "title": config.title,
        "seed_urls": config.urls,
        "input_format": config.input_format,
        "output_format": config.output_format,
        "scope": config.scope,
        "same_prefix_depth": config.same_prefix_depth,
        "max_pages": config.max_pages,
        "render_js": config.render_js,
        "delay_seconds": config.delay_seconds,
        "timeout_seconds": config.timeout_seconds,
        "min_chars": config.min_chars,
        "keep_query": config.keep_query,
        "url_file": str(config.url_file.as_posix()) if config.url_file else None,
        "url_file_mode": config.url_file_mode,
        "batch_seed_url": config.batch_seed_url,
        "include": pattern_strings(config.include_patterns),
        "exclude": pattern_strings(config.exclude_patterns),
        "page_count": len(pages),
        "pages": [
            {
                "index": page.source_index,
                "title": page.title,
                "url": page.url,
                "status_code": page.status_code,
                "content_sha256": page.content_sha256,
                "extracted_by": page.extracted_by,
                "char_count": len(page.markdown),
                "markdown": page.markdown,
            }
            for page in pages
        ],
        "discovered_urls": discovered_urls,
    }


def markdown_to_basic_html(markdown: str, title: str) -> str:
    escaped = html.escape(markdown)

    linked = re.sub(
        r"^(#{1,6})\s+(.+)$",
        heading_to_html,
        escaped,
        flags=re.MULTILINE,
    )

    linked = re.sub(
        r"```(.*?)```",
        r"<pre><code>\1</code></pre>",
        linked,
        flags=re.DOTALL,
    )

    paragraphs = []
    for block in linked.split("\n\n"):
        stripped = block.strip()
        if not stripped:
            continue
        if stripped.startswith("<h") or stripped.startswith("<pre") or stripped.startswith("<hr"):
            paragraphs.append(stripped)
        elif stripped == "---":
            paragraphs.append("<hr>")
        else:
            paragraphs.append(f"<p>{stripped.replace(chr(10), '<br>')}</p>")

    body = "\n".join(paragraphs)

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{
    font-family: Arial, sans-serif;
    line-height: 1.45;
    margin: 2rem;
    max-width: 72rem;
}}
pre {{
    background: #f5f5f5;
    border: 1px solid #ddd;
    overflow-x: auto;
    padding: 0.8rem;
    white-space: pre-wrap;
}}
code {{
    font-family: Consolas, Menlo, Monaco, monospace;
}}
h1, h2, h3, h4, h5, h6 {{
    page-break-after: avoid;
}}
hr {{
    border: 0;
    border-top: 1px solid #ccc;
    margin: 2rem 0;
}}
p {{
    margin: 0.8rem 0;
}}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def heading_to_html(match: re.Match[str]) -> str:
    level = len(match.group(1))
    text = match.group(2)
    return f"<h{level}>{text}</h{level}>"


def write_pdf_from_markdown(markdown: str, output_path: Path, title: str) -> None:
    try:
        from reportlab.lib.pagesizes import letter  # noqa: PLC0415
        from reportlab.lib.styles import getSampleStyleSheet  # noqa: PLC0415
        from reportlab.platypus import PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("PDF output requires ReportLab. Run the normal editable install again.") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        title=title,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    story = []
    in_code_block = False
    code_lines: list[str] = []

    def flush_code_block() -> None:
        if not code_lines:
            return
        story.append(Preformatted("\n".join(code_lines), styles["Code"]))
        story.append(Spacer(1, 8))
        code_lines.clear()

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()

        if line.startswith("```"):
            if in_code_block:
                flush_code_block()
                in_code_block = False
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 6))
            continue

        if stripped == "---":
            story.append(PageBreak())
            continue

        if stripped.startswith("# "):
            story.append(Paragraph(html.escape(stripped[2:]), styles["Title"]))
            story.append(Spacer(1, 10))
            continue

        if stripped.startswith("## "):
            story.append(Paragraph(html.escape(stripped[3:]), styles["Heading1"]))
            story.append(Spacer(1, 8))
            continue

        if stripped.startswith("### "):
            story.append(Paragraph(html.escape(stripped[4:]), styles["Heading2"]))
            story.append(Spacer(1, 6))
            continue

        if stripped.startswith("#### "):
            story.append(Paragraph(html.escape(stripped[5:]), styles["Heading3"]))
            story.append(Spacer(1, 6))
            continue

        story.append(Paragraph(html.escape(stripped), styles["BodyText"]))

    if in_code_block:
        flush_code_block()

    document.build(story)


def write_output_file(pages: list[PageResult], discovered_urls: list[str], config: CrawlConfig) -> Path:
    config.output_dir.mkdir(parents=True, exist_ok=True)

    if config.output_path.suffix:
        output_path = config.output_path
    else:
        suffix_by_format = {
            "markdown": ".md",
            "json": ".json",
            "pdf": ".pdf",
        }
        output_path = config.output_path / f"source-pack{suffix_by_format[config.output_format]}"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if config.output_format == "markdown":
        output_path.write_text(combined_markdown(pages, config.title), encoding="utf-8")
        return output_path

    if config.output_format == "json":
        payload = pages_to_json_payload(pages, discovered_urls, config)
        output_path.write_text(json.dumps(payload, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
        return output_path

    if config.output_format == "pdf":
        write_pdf_from_markdown(combined_markdown(pages, config.title), output_path, config.title)
        return output_path

    raise ValueError(f"Unsupported output format: {config.output_format}")


def write_split_pages(pages: list[PageResult], config: CrawlConfig) -> list[Path]:
    pages_dir = config.output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []

    for page in pages:
        filename = page_filename(page.source_index, page.title, page.url)
        output_path = pages_dir / filename
        output_path.write_text(markdown_page_block(page).strip() + "\n", encoding="utf-8")
        paths.append(output_path)

    return paths


def write_manifest(
    pages: list[PageResult],
    discovered_urls: list[str],
    output_file: Path | None,
    config: CrawlConfig,
    candidate_urls_file: Path | None = None,
) -> Path:
    if config.batch_seed_url and output_file is not None:
        output_path = config.output_dir / f"{output_file.stem}-manifest.json"
    else:
        output_path = config.output_dir / "manifest.json"

    payload = {
        "title": config.title,
        "seed_urls": config.urls,
        "input_format": config.input_format,
        "output_format": config.output_format,
        "scope": config.scope,
        "same_prefix_depth": config.same_prefix_depth,
        "max_pages": config.max_pages,
        "render_js": config.render_js,
        "delay_seconds": config.delay_seconds,
        "timeout_seconds": config.timeout_seconds,
        "min_chars": config.min_chars,
        "keep_query": config.keep_query,
        "url_file": str(config.url_file.as_posix()) if config.url_file else None,
        "url_file_mode": config.url_file_mode,
        "batch_seed_url": config.batch_seed_url,
        "include": pattern_strings(config.include_patterns),
        "exclude": pattern_strings(config.exclude_patterns),
        "page_count": len(pages),
        "generated_files": {
            "main_output": str(output_file.as_posix()) if output_file else None,
            "split_pages_dir": str((config.output_dir / "pages").as_posix()) if config.split_pages else None,
            "candidate_urls": str(candidate_urls_file.as_posix()) if candidate_urls_file else None,
            "manifest": str(output_path.as_posix()),
        },
        "pages": [
            {
                "index": page.source_index,
                "title": page.title,
                "url": page.url,
                "status_code": page.status_code,
                "content_sha256": page.content_sha256,
                "extracted_by": page.extracted_by,
                "char_count": len(page.markdown),
            }
            for page in pages
        ],
        "discovered_urls": discovered_urls,
    }

    output_path.write_text(json.dumps(payload, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    return output_path


def write_candidate_urls(discovered_urls: Iterable[str], config: CrawlConfig) -> Path:
    if config.batch_seed_url and config.output_path.suffix:
        output_path = config.output_dir / f"{config.output_path.stem}-candidate-urls.txt"
    else:
        output_path = config.output_dir / "candidate-urls.txt"
    unique_urls = list(dict.fromkeys(discovered_urls))
    output_path.write_text("\n".join(unique_urls) + "\n", encoding="utf-8")
    return output_path


def run_playwright_browser_install(browser: str, dry_run: bool = False) -> int:
    command = [
        sys.executable,
        "-m",
        "playwright",
        "install",
        browser,
    ]

    if dry_run:
        print(" ".join(command))
        return 0

    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        print(f"[fail] could not run Playwright installer: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"[fail] Playwright installer exited with code {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1

    return 0


def check_import(module_name: str) -> tuple[bool, str]:
    try:
        __import__(module_name)
    except Exception as exc:
        return False, str(exc)

    return True, "ok"


def check_playwright_chromium(skip_browser_launch: bool) -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except Exception as exc:
        return False, f"playwright import failed: {exc}"

    try:
        with sync_playwright() as playwright:
            executable_path = playwright.chromium.executable_path
            if not Path(executable_path).exists():
                return False, f"chromium executable not found: {executable_path}"

            if skip_browser_launch:
                return True, f"chromium executable found: {executable_path}"

            browser = playwright.chromium.launch(headless=True)
            browser.close()
    except Exception as exc:
        return False, f"chromium launch failed: {exc}"

    return True, "chromium launch ok"


def check_output_directory(output_dir: Path) -> tuple[bool, str]:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        probe_path = output_dir / ".wdp-doctor-write-test"
        probe_path.write_text("ok\n", encoding="utf-8")
        probe_path.unlink()
    except Exception as exc:
        return False, str(exc)

    return True, "write ok"


def print_check(label: str, ok: bool, detail: str) -> None:
    status = "ok" if ok else "fail"
    print(f"[{status}] {label}: {detail}")


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def crawl(config: CrawlConfig) -> tuple[list[PageResult], list[str]]:
    queue: deque[str] = deque()
    visited: set[str] = set()
    discovered: list[str] = []
    pages: list[PageResult] = []

    for url in config.urls:
        normalized = normalize_url(url, keep_query=config.keep_query)
        if should_keep_url(normalized, config):
            queue.append(normalized)
            if not (config.input_format == "sitemap" and is_sitemap_url(normalized)):
                discovered.append(normalized)

    while queue and len(visited) < config.max_pages:
        current_url = queue.popleft()

        if current_url in visited:
            continue

        visited.add(current_url)

        try:
            page_html, status_code = fetch_html(current_url, config)
        except Exception as exc:
            print(f"[warn] failed to fetch {current_url}: {exc}", file=sys.stderr)
            continue

        next_links = discover_next_links(page_html, current_url, config)
        for link in next_links:
            if not (config.input_format == "sitemap" and is_sitemap_url(link)) and link not in discovered:
                discovered.append(link)
            if link not in visited and link not in queue and len(visited) + len(queue) < config.max_pages * 3:
                queue.append(link)

        if config.input_format == "sitemap" and is_sitemap_url(current_url):
            if config.delay_seconds > 0:
                time.sleep(config.delay_seconds)
            continue

        if config.dry_run:
            print(current_url)
            if config.delay_seconds > 0:
                time.sleep(config.delay_seconds)
            continue

        try:
            title, markdown = extract_markdown(page_html, current_url)
        except Exception as exc:
            print(f"[warn] failed to extract {current_url}: {exc}", file=sys.stderr)
            continue

        if len(markdown) < config.min_chars:
            print(
                f"[warn] skipped short extraction ({len(markdown)} chars): {current_url}",
                file=sys.stderr,
            )
            continue

        page = PageResult(
            url=current_url,
            title=title,
            markdown=markdown,
            source_index=len(pages) + 1,
            status_code=status_code,
            content_sha256=hash_text(markdown),
            extracted_by="trafilatura-or-markdownify",
        )
        pages.append(page)

        print(f"[ok] {page.source_index:03d} {page.title} <{page.url}>", file=sys.stderr)

        if config.delay_seconds > 0:
            time.sleep(config.delay_seconds)

    return pages, discovered


def add_common_crawl_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--url",
        "-u",
        action="append",
        default=[],
        help="Seed URL. May be passed multiple times.",
    )
    parser.add_argument(
        "--input-format",
        "-I",
        choices=[
            "auto",
            "single-page",
            "docs-site",
            "github-wiki",
            "github-pages",
            "sitemap",
        ],
        default="auto",
        help="Input site type. Use auto unless a site needs explicit handling.",
    )
    parser.add_argument(
        "--scope",
        "-s",
        choices=["single", "prefix", "domain"],
        default=None,
        help="Crawl scope. Defaults depend on input format.",
    )
    parser.add_argument(
        "--same-prefix-depth",
        "-p",
        type=int,
        default=None,
        help=(
            "Path depth used for prefix scope. For /codex/skills, depth 2 scopes "
            "to /codex/skills/ if possible. When omitted, docs roots such as /docs/ use depth 1."
        ),
    )
    parser.add_argument(
        "--include",
        "-i",
        action="append",
        default=[],
        help="Regex that candidate URLs must match. May be passed multiple times.",
    )
    parser.add_argument(
        "--exclude",
        "-x",
        action="append",
        default=[],
        help="Regex for candidate URLs to exclude. May be passed multiple times.",
    )
    parser.add_argument(
        "--max-pages",
        "-m",
        type=int,
        default=None,
        help="Maximum number of pages to fetch. Defaults depend on input format.",
    )
    parser.add_argument(
        "--delay-seconds",
        "-d",
        type=float,
        default=0.35,
        help="Delay between requests.",
    )
    parser.add_argument(
        "--timeout-seconds",
        "-T",
        type=float,
        default=30.0,
        help="HTTP timeout per page.",
    )
    render_group = parser.add_mutually_exclusive_group()
    render_group.add_argument(
        "--render-js",
        "-j",
        dest="render_js",
        action="store_true",
        default=None,
        help="Use Playwright/Chromium to render JavaScript-heavy docs pages before extraction.",
    )
    render_group.add_argument(
        "--no-render-js",
        "-J",
        dest="render_js",
        action="store_false",
        help="Disable JavaScript rendering even when the input format would enable it by default.",
    )
    render_group.set_defaults(render_js=None)
    parser.add_argument(
        "--user-agent",
        "-a",
        default=DEFAULT_USER_AGENT,
        help="HTTP User-Agent header.",
    )
    parser.add_argument(
        "--min-chars",
        "-c",
        type=int,
        default=300,
        help="Minimum extracted Markdown characters required to keep a page.",
    )
    parser.add_argument(
        "--keep-query",
        "-q",
        action="store_true",
        help="Keep URL query strings. Usually disabled to avoid duplicate tracking URLs.",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="web-docs-processor",
        description="Create retrieval-friendly source packs from documentation websites.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(
        title="subcommands",
        dest="command",
        required=True,
    )

    build_parser = subparsers.add_parser(
        "build",
        help="Crawl docs pages and build a source document.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_common_crawl_arguments(build_parser)
    build_parser.add_argument(
        "--format",
        "-f",
        choices=["markdown", "json", "pdf"],
        default="markdown",
        help="Output document format.",
    )
    build_parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file path or output directory. Defaults to ./out/<site-and-path>.<format>.",
    )
    build_parser.add_argument(
        "--title",
        "-t",
        default=None,
        help="Title for the generated document. Defaults to a title derived from the seed URL.",
    )
    build_parser.add_argument(
        "--split-pages",
        "-S",
        action="store_true",
        help="Also write one Markdown file per page.",
    )
    build_parser.add_argument(
        "--no-manifest",
        "-M",
        action="store_true",
        help="Do not write manifest.json.",
    )
    build_parser.add_argument(
        "--no-candidates",
        "-C",
        action="store_true",
        help="Do not write candidate-urls.txt.",
    )
    build_parser.add_argument(
        "--manifest",
        "-g",
        default=None,
        help="Read crawl settings and discovered URL order from a previous manifest.json.",
    )
    build_parser.add_argument(
        "--url-file",
        "-F",
        default=None,
        help="Plain-text URL file. Blank lines and lines starting with # are ignored.",
    )
    build_parser.add_argument(
        "--url-file-mode",
        "-U",
        choices=["exact", "expand"],
        default="exact",
        help=(
            "URL file handling mode. exact fetches only listed URLs into one document; "
            "expand treats each URL as a seed and writes one document per seed."
        ),
    )
    build_parser.add_argument(
        "--one-output-per-seed",
        "-O",
        action="store_true",
        help="Write one output per URL-file seed. This is implied by --url-file-mode expand.",
    )

    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover candidate URLs without extracting a source document.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_common_crawl_arguments(discover_parser)
    discover_parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output candidate URL file path or output directory. Defaults to ./out/<site-and-path>-candidates.txt.",
    )
    discover_parser.add_argument(
        "--no-manifest",
        "-M",
        action="store_true",
        help="Do not write manifest.json for the discovered URL set.",
    )

    setup_browsers_parser = subparsers.add_parser(
        "setup-browsers",
        help="Install Playwright browser runtimes used for JavaScript-rendered docs pages.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    setup_browsers_parser.add_argument(
        "--browser",
        "-b",
        choices=["chromium", "firefox", "webkit"],
        default="chromium",
        help="Playwright browser runtime to install.",
    )
    setup_browsers_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Print the Playwright install command without running it.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check package imports, browser availability, and output-directory write access.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    doctor_parser.add_argument(
        "--output-dir",
        "-o",
        default=".",
        help="Directory to use for a write-permission probe.",
    )
    doctor_parser.add_argument(
        "--skip-browser-launch",
        "-L",
        action="store_true",
        help="Check Chromium executable presence without launching the browser.",
    )

    return parser.parse_args(argv)


def build_config(args: argparse.Namespace, dry_run: bool) -> CrawlConfig:
    manifest_payload: dict[str, object] | None = None
    if getattr(args, "manifest", None):
        manifest_payload = read_manifest(args.manifest)

    url_file = Path(args.url_file).expanduser().resolve() if getattr(args, "url_file", None) else None
    url_file_mode: UrlFileMode | None = args.url_file_mode if url_file else None
    if url_file and getattr(args, "one_output_per_seed", False):
        url_file_mode = "expand"
    keep_query = args.keep_query or manifest_bool(manifest_payload or {}, "keep_query", False)
    url_file_urls = read_url_file(url_file, keep_query=keep_query) if url_file else []
    manifest_seed_urls = manifest_string_list(manifest_payload or {}, "seed_urls")
    manifest_discovered_urls = manifest_string_list(manifest_payload or {}, "discovered_urls")
    cli_urls = args.url or []
    source_urls = url_file_urls + cli_urls
    if not source_urls:
        source_urls = manifest_discovered_urls or manifest_seed_urls
    if not source_urls:
        raise RuntimeError("At least one --url/-u is required unless --manifest/-g provides URLs.")

    urls = [normalize_url(url, keep_query=keep_query) for url in source_urls]
    explicit_input_format: InputFormat = args.input_format
    manifest_input_format = manifest_str(manifest_payload or {}, "input_format", "auto")
    if explicit_input_format == "auto" and manifest_input_format != "auto":
        explicit_input_format = coerce_input_format(manifest_input_format)
    inferred_input_format = infer_input_format(urls, explicit_input_format)

    manifest_scope = manifest_str(manifest_payload or {}, "scope", "")
    explicit_scope = args.scope or manifest_scope or None
    if url_file_mode == "exact" and explicit_scope is None:
        explicit_scope = "single"
    scope = default_scope_for_input_format(inferred_input_format, explicit_scope)

    output_format: OutputFormat = getattr(args, "format", "markdown")
    if url_file and not dry_run:
        final_output_path = default_url_file_output_path(
            url_file,
            output_format,
            url_file_mode or "exact",
            getattr(args, "output", None),
        )
    elif getattr(args, "one_output_per_seed", False) and not dry_run:
        final_output_path = Path(getattr(args, "output", None) or (Path.cwd() / "out" / "seeds")).expanduser().resolve()
    else:
        final_output_path = default_output_path(
            urls,
            output_format,
            dry_run,
            getattr(args, "output", None),
        )
    title = getattr(args, "title", None) or manifest_str(manifest_payload or {}, "title", "") or title_from_url(urls[0])
    manifest_max_pages = manifest_int(manifest_payload or {}, "max_pages", 0) or None
    if url_file_mode == "exact" and args.max_pages is None and manifest_max_pages is None:
        max_pages = len(urls)
    else:
        max_pages = default_max_pages_for_input_format(inferred_input_format, args.max_pages or manifest_max_pages)
    manifest_prefix_depth = manifest_int(manifest_payload or {}, "same_prefix_depth", -1)
    explicit_prefix_depth = args.same_prefix_depth
    if explicit_prefix_depth is None and manifest_prefix_depth >= 0:
        explicit_prefix_depth = manifest_prefix_depth
    same_prefix_depth = default_same_prefix_depth(
        urls,
        inferred_input_format,
        explicit_prefix_depth,
    )
    explicit_render_js = args.render_js
    if explicit_render_js is None:
        explicit_render_js = manifest_bool(manifest_payload or {}, "render_js", None)
    render_js = default_render_js_for_input_format(
        inferred_input_format,
        explicit_render_js,
    )
    include_patterns = args.include or manifest_string_list(manifest_payload or {}, "include")
    exclude_patterns = args.exclude or manifest_string_list(manifest_payload or {}, "exclude")
    delay_seconds = args.delay_seconds
    if manifest_payload and "delay_seconds" in manifest_payload:
        delay_seconds = manifest_float(manifest_payload, "delay_seconds", delay_seconds)
    timeout_seconds = args.timeout_seconds
    if manifest_payload and "timeout_seconds" in manifest_payload:
        timeout_seconds = manifest_float(manifest_payload, "timeout_seconds", timeout_seconds)
    min_chars = args.min_chars
    if manifest_payload and "min_chars" in manifest_payload:
        min_chars = manifest_int(manifest_payload, "min_chars", min_chars)

    return CrawlConfig(
        urls=urls,
        output_path=final_output_path,
        output_format=output_format,
        title=title,
        input_format=inferred_input_format,
        scope=scope,
        include_patterns=compile_patterns(include_patterns),
        exclude_patterns=compile_patterns(exclude_patterns),
        max_pages=max_pages,
        delay_seconds=delay_seconds,
        timeout_seconds=timeout_seconds,
        split_pages=getattr(args, "split_pages", False),
        dry_run=dry_run,
        render_js=render_js,
        user_agent=args.user_agent,
        min_chars=min_chars,
        same_prefix_depth=same_prefix_depth,
        keep_query=keep_query,
        write_manifest=not getattr(args, "no_manifest", False),
        write_candidates=not getattr(args, "no_candidates", False),
        url_file=url_file,
        url_file_mode=url_file_mode,
        batch_seed_url=None,
    )


def run_single_build(config: CrawlConfig) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)

    pages, discovered_urls = crawl(config)

    if not pages:
        print(
            "No pages were extracted. Try --render-js, broader --scope, or different include/exclude rules.",
            file=sys.stderr,
        )
        return 2

    output_file = write_output_file(pages, discovered_urls, config)

    candidate_path: Path | None = None
    if config.write_candidates:
        candidate_path = write_candidate_urls(discovered_urls, config)

    split_paths: list[Path] = []
    if config.split_pages:
        split_paths = write_split_pages(pages, config)

    manifest_path: Path | None = None
    if config.write_manifest:
        manifest_path = write_manifest(pages, discovered_urls, output_file, config, candidate_path)

    print("", file=sys.stderr)
    print(f"Wrote output: {output_file}", file=sys.stderr)

    if manifest_path:
        print(f"Wrote manifest: {manifest_path}", file=sys.stderr)

    if candidate_path:
        print(f"Wrote candidate URLs: {candidate_path}", file=sys.stderr)

    if split_paths:
        print(f"Wrote split pages: {len(split_paths)} files under {config.output_dir / 'pages'}", file=sys.stderr)

    print(f"Extracted page count: {len(pages)}", file=sys.stderr)

    return 0


def run_expand_build(config: CrawlConfig) -> int:
    output_dir = config.output_path
    output_dir.mkdir(parents=True, exist_ok=True)
    used_paths: set[Path] = set()
    failures = 0

    for seed_url in config.urls:
        seed_output_path = unique_output_path(
            output_path_for_seed(output_dir, seed_url, config.output_format),
            used_paths,
        )
        seed_config = dataclasses.replace(
            config,
            urls=[seed_url],
            output_path=seed_output_path,
            title=title_from_url(seed_url),
            batch_seed_url=seed_url,
        )

        result = run_single_build(seed_config)
        if result != 0:
            failures += 1

    if failures:
        print(f"Batch completed with {failures} failed seed(s).", file=sys.stderr)
        return 2

    print(f"Batch completed successfully for {len(config.urls)} seed(s).", file=sys.stderr)
    return 0


def run_build(args: argparse.Namespace) -> int:
    config = build_config(args, dry_run=False)

    if config.url_file_mode == "expand" or getattr(args, "one_output_per_seed", False):
        return run_expand_build(config)

    return run_single_build(config)


def run_discover(args: argparse.Namespace) -> int:
    config = build_config(args, dry_run=True)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    _pages, discovered_urls = crawl(config)

    if config.output_path.suffix:
        output_path = config.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        unique_urls = list(dict.fromkeys(discovered_urls))
        output_path.write_text("\n".join(unique_urls) + "\n", encoding="utf-8")
    else:
        output_path = write_candidate_urls(discovered_urls, config)

    manifest_path: Path | None = None
    if not getattr(args, "no_manifest", False):
        manifest_path = write_manifest([], discovered_urls, None, config, output_path)

    print("", file=sys.stderr)
    print(f"Wrote candidate URLs: {output_path}", file=sys.stderr)
    if manifest_path:
        print(f"Wrote manifest: {manifest_path}", file=sys.stderr)
    print(f"Candidate URL count: {len(discovered_urls)}", file=sys.stderr)

    return 0


def run_setup_browsers(args: argparse.Namespace) -> int:
    return run_playwright_browser_install(args.browser, dry_run=args.dry_run)


def run_doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []

    python_ok = sys.version_info >= (3, 10)
    checks.append(
        (
            "python",
            python_ok,
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} at {sys.executable}",
        )
    )
    checks.append(("package", True, f"web-docs-processor {__version__}"))

    for module_name in REQUIRED_IMPORTS:
        ok, detail = check_import(module_name)
        checks.append((f"import {module_name}", ok, detail))

    for module_name in FULL_FEATURE_IMPORTS:
        ok, detail = check_import(module_name)
        checks.append((f"import {module_name}", ok, detail))

    chromium_ok, chromium_detail = check_playwright_chromium(args.skip_browser_launch)
    checks.append(("playwright chromium", chromium_ok, chromium_detail))

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_ok, output_detail = check_output_directory(output_dir)
    checks.append(("output directory", output_ok, f"{output_dir}: {output_detail}"))

    for label, ok, detail in checks:
        print_check(label, ok, detail)

    return 0 if all(ok for _label, ok, _detail in checks) else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.command == "build":
        return run_build(args)

    if args.command == "discover":
        return run_discover(args)

    if args.command == "setup-browsers":
        return run_setup_browsers(args)

    if args.command == "doctor":
        return run_doctor(args)

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
