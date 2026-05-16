"""
extdl — Extended download fallback library for ytaedl.

Extracted from ytdlp-extdl.py (standalone script).  This module provides
the media-discovery and command-building functions as a library so that
downloader.py can use them when normal yt-dlp fails on a URL.

Fallback chain:
  Method 2 – Static HTML scan: fetch the page, regex-hunt for HLS/DASH/MP4 URLs.
  Method 3 – Playwright browser capture: launch a headless browser, capture network
              traffic, identify media requests.  Requires ``playwright`` to be installed.
"""

from __future__ import annotations

import dataclasses
import html
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0"
)

HLS_CONTENT_TYPES = {
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
    "vnd.apple.mpegurl",
}

DASH_CONTENT_TYPES = {"application/dash+xml"}

IGNORED_URL_PARTS = (
    "google-analytics",
    "googletagmanager",
    "doubleclick",
    "facebook.com/tr",
    "analytics",
    "adsystem",
    "adservice",
)


@dataclasses.dataclass(frozen=True)
class MediaCandidate:
    url: str
    kind: str          # "hls" | "dash" | "direct" | "embed" | "segment"
    source: str        # where it was discovered
    score: int
    content_type: str = ""
    note: str = ""


# ---------------------------------------------------------------------------
# URL classification helpers


def normalize_content_type(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def has_ignored_url_part(url: str) -> bool:
    lowered = url.lower()
    return any(part in lowered for part in IGNORED_URL_PARTS)


def looks_like_preview_video(lowered_url: str) -> bool:
    parsed = urllib.parse.urlparse(lowered_url)
    query = urllib.parse.parse_qs(parsed.query.lower(), keep_blank_values=True)
    return (
        "/pv/" in lowered_url
        or "/preview" in lowered_url
        or "preview" in parsed.path.lower()
        or "trailer" in parsed.path.lower()
        or "teaser" in parsed.path.lower()
        or "sample" in parsed.path.lower()
        or query.get("ispreview") == ["true"]
        or re.search(r"(^|[/_-])pv([_.-]|$)", lowered_url) is not None
    )


def looks_like_embedded_player_url(lowered_url: str) -> bool:
    parsed = urllib.parse.urlparse(lowered_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if has_ignored_url_part(lowered_url):
        return False
    if "mydaddy.cc" in host and "/video/" in path:
        return True
    # Only /embed/ and /player/ are reliable embedded-player path indicators.
    # /video/ is intentionally excluded: on most tube sites it is the normal
    # page URL pattern (e.g. site.com/video/123/title/) so matching it causes
    # the scraper to treat every related-video link on the page as a candidate.
    return any(part in path for part in ("/embed/", "/player/"))


def infer_resolution_bonus(url: str) -> int:
    lowered = url.lower()
    match = re.search(r"(?:^|[/_-])([1-9]\d{2,3})p?(?=\.mp4|[/_.-])", lowered)
    if match is None:
        return 0
    height = int(match.group(1))
    if height > 4320:
        return 0
    return min(height // 100, 30)


def infer_candidate_kind(url: str, content_type: str = "") -> tuple[Optional[str], int, str]:
    lowered_url = url.lower()
    normalized_type = normalize_content_type(content_type)

    if has_ignored_url_part(url):
        return None, 0, "ignored analytics/ad/tracker-like URL"
    if normalized_type in HLS_CONTENT_TYPES or "mpegurl" in normalized_type:
        return "hls", 100, "HLS playlist content type"
    if normalized_type in DASH_CONTENT_TYPES or "dash+xml" in normalized_type:
        return "dash", 95, "DASH manifest content type"
    if ".m3u8" in lowered_url:
        return "hls", 90, "m3u8 URL"
    if ".mpd" in lowered_url:
        return "dash", 85, "mpd URL"
    if normalized_type.startswith("video/"):
        if ".ts" in lowered_url or lowered_url.endswith(".ts"):
            return "segment", 20, "transport-stream segment"
        if ".mp4" in lowered_url:
            score = 70
            note = "direct mp4 URL"
            if looks_like_preview_video(lowered_url):
                score -= 35
                note = "direct mp4 URL, looks like a preview"
            return "direct", score + infer_resolution_bonus(lowered_url), note
        return "direct", 60, "video content type"
    if ".mp4" in lowered_url:
        score = 55
        note = "mp4-looking URL"
        if looks_like_preview_video(lowered_url):
            score -= 35
            note = "mp4-looking URL, looks like a preview"
        return "direct", score + infer_resolution_bonus(lowered_url), note
    if ".ts" in lowered_url:
        return "segment", 15, "transport-stream segment"
    if looks_like_embedded_player_url(lowered_url):
        return "embed", 65, "embedded player URL"
    return None, 0, "not recognized as downloadable media"


def make_candidate(
    url: str,
    *,
    source: str,
    content_type: str = "",
    score_adjustment: int = 0,
) -> Optional[MediaCandidate]:
    cleaned_url = html.unescape(url.strip().strip('"').strip("'")).replace("\\/", "/")
    # Promote protocol-relative URLs (//cdn.example.com/...) to https://
    if cleaned_url.startswith("//"):
        cleaned_url = "https:" + cleaned_url
    if not cleaned_url.startswith(("http://", "https://")):
        return None
    kind, score, note = infer_candidate_kind(cleaned_url, content_type)
    if kind is None:
        return None
    return MediaCandidate(
        url=cleaned_url,
        kind=kind,
        source=source,
        score=score + score_adjustment,
        content_type=normalize_content_type(content_type),
        note=note,
    )


def dedupe_candidates(candidates: Iterable[MediaCandidate]) -> List[MediaCandidate]:
    by_url: dict[str, MediaCandidate] = {}
    for candidate in candidates:
        existing = by_url.get(candidate.url)
        if existing is None or candidate.score > existing.score:
            by_url[candidate.url] = candidate
    return sorted(
        by_url.values(),
        key=lambda item: (
            item.score,
            item.kind == "hls",
            item.kind == "dash",
            item.kind == "direct",
            -len(item.url),
        ),
        reverse=True,
    )


def filter_candidates(
    candidates: Sequence[MediaCandidate],
    *,
    include_segments: bool = False,
    candidate_contains: Sequence[str] = (),
) -> List[MediaCandidate]:
    lowered_terms = [t.lower() for t in candidate_contains]
    filtered: List[MediaCandidate] = []
    for candidate in candidates:
        if candidate.kind == "segment" and not include_segments:
            continue
        lowered_url = candidate.url.lower()
        if lowered_terms and not all(t in lowered_url for t in lowered_terms):
            continue
        filtered.append(candidate)
    return filtered


# ---------------------------------------------------------------------------
# Network helpers


def infer_origin(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def absolutize_url(raw_url: str, base_url: str) -> str:
    # Unescape HTML entities first, then normalise JS-escaped slashes
    # (e.g. "\/\/cdn.example.com\/..." → "//cdn.example.com/...").
    # urljoin treats leading backslash as a relative path component instead of
    # recognising the protocol-relative URL, so we must clean it first.
    unescaped = html.unescape(raw_url).replace("\\/", "/")
    return urllib.parse.urljoin(base_url, unescaped)


def fetch_page_html(
    page_url: str,
    *,
    referer: str,
    origin: str,
    user_agent: str,
    timeout_seconds: float,
) -> str:
    request = urllib.request.Request(
        page_url,
        headers={
            "User-Agent": user_agent,
            "Referer": referer,
            "Origin": origin,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Static HTML candidate discovery


def extract_static_candidates(page_html: str, page_url: str) -> List[MediaCandidate]:
    candidates: List[MediaCandidate] = []
    url_patterns = [
        r"""https?://[^\s"'<>\\]+""",
        r"""//[^\s"'<>\\]+""",
        r"""["']([^"']+\.(?:m3u8|mpd|mp4)(?:\?[^"']*)?)["']""",
        r"""["']([^"']*_TPL_mp4(?:\?[^"']*)?)["']""",
        r"""(?:src|data-src|href)\s*=\s*["']([^"']+)["']""",
        r"""\bi=(//[^"',\s)]+|https?://[^"',\s)]+)""",
    ]
    for pattern in url_patterns:
        for match in re.finditer(pattern, page_html, flags=re.IGNORECASE):
            raw_url = match.group(1) if match.lastindex else match.group(0)
            absolute_url = absolutize_url(raw_url, page_url)
            candidate = make_candidate(absolute_url, source="static_html", score_adjustment=-5)
            if candidate is not None:
                candidates.append(candidate)
    return dedupe_candidates(candidates)


def expand_embedded_player_candidates(
    candidates: Sequence[MediaCandidate],
    *,
    page_url: str,
    user_agent: str,
    timeout_seconds: float,
) -> List[MediaCandidate]:
    expanded: List[MediaCandidate] = list(candidates)
    for candidate in [c for c in candidates if c.kind == "embed"]:
        try:
            player_html = fetch_page_html(
                candidate.url,
                referer=page_url,
                origin=infer_origin(candidate.url),
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
            )
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            continue
        for player_candidate in extract_static_candidates(player_html, candidate.url):
            expanded.append(
                dataclasses.replace(
                    player_candidate,
                    source=f"{candidate.source}_embed",
                    score=player_candidate.score + 20,
                    note=f"{player_candidate.note}; from embedded player",
                )
            )
    return dedupe_candidates(expanded)


def discover_static_media_candidates(
    page_url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: float = 30.0,
) -> List[MediaCandidate]:
    """Fetch page HTML and extract HLS/DASH/MP4 candidate URLs."""
    referer = page_url
    origin = infer_origin(page_url)
    try:
        page_html = fetch_page_html(
            page_url,
            referer=referer,
            origin=origin,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        return []
    candidates = extract_static_candidates(page_html, page_url)
    candidates = expand_embedded_player_candidates(
        candidates,
        page_url=page_url,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
    )
    return filter_candidates(candidates)


# ---------------------------------------------------------------------------
# Playwright browser capture (Method 3)


def _try_import_playwright():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        return sync_playwright
    except ImportError:
        return None


def _preferred_playwright_browsers(capture_browser: str) -> List[str]:
    if capture_browser != "auto":
        return [capture_browser]
    return ["chromium", "firefox", "webkit"]


def _trigger_playback(page) -> None:
    script = """
    async () => {
        const videos = Array.from(document.querySelectorAll("video"));
        for (const video of videos) {
            try { video.muted = true; video.playsInline = true; video.play().catch(()=>{}); } catch(e) {}
        }
        const selectors = ["button","[role='button']",".play",".play-button",
            ".vjs-big-play-button",".jw-icon-playback",".plyr__control",
            "[aria-label*='Play' i]","[title*='Play' i]"];
        const elements = [];
        for (const sel of selectors) elements.push(...Array.from(document.querySelectorAll(sel)));
        for (const el of Array.from(new Set(elements)).slice(0, 8)) {
            try { const r = el.getBoundingClientRect(); if (r.width > 0 && r.height > 0) el.click(); } catch(e) {}
        }
    }
    """
    try:
        page.evaluate(script)
    except Exception:
        pass
    try:
        page.mouse.click(640, 360)
    except Exception:
        pass
    try:
        page.keyboard.press("Space")
    except Exception:
        pass


def discover_browser_media_candidates(
    page_url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: float = 30.0,
    wait_seconds: float = 12.0,
    capture_browser: str = "auto",
    browser_state_path: Optional[str] = None,
) -> List[MediaCandidate]:
    """Launch a Playwright browser, capture network traffic, return media candidates.

    Raises ``RuntimeError`` if Playwright is not installed.
    """
    sync_playwright = _try_import_playwright()
    if sync_playwright is None:
        raise RuntimeError(
            "Playwright is not installed. Install with: "
            "pip install playwright && python -m playwright install chromium"
        )

    referer = page_url
    origin = infer_origin(page_url)
    candidates: List[MediaCandidate] = []
    last_exc: Optional[Exception] = None

    for browser_name in _preferred_playwright_browsers(capture_browser):
        try:
            with sync_playwright() as pw:
                browser_factory = getattr(pw, browser_name)
                browser = browser_factory.launch(headless=True)
                ctx_kwargs: dict = {
                    "user_agent": user_agent,
                    "extra_http_headers": {"Referer": referer, "Origin": origin},
                }
                if browser_state_path:
                    ctx_kwargs["storage_state"] = browser_state_path
                context = browser.new_context(**ctx_kwargs)
                page = context.new_page()

                def _on_request(req) -> None:
                    c = make_candidate(req.url, source="browser_request")
                    if c:
                        candidates.append(c)

                def _on_response(resp) -> None:
                    ct = resp.headers.get("content-type", "")
                    c = make_candidate(resp.url, source="browser_response", content_type=ct)
                    if c:
                        candidates.append(c)

                page.on("request", _on_request)
                page.on("response", _on_response)
                page.goto(page_url, wait_until="domcontentloaded", timeout=int(timeout_seconds * 1000))
                try:
                    page.wait_for_load_state("networkidle", timeout=int(min(timeout_seconds, 10.0) * 1000))
                except Exception:
                    pass
                _trigger_playback(page)
                import time as _time
                _time.sleep(wait_seconds)
                try:
                    _trigger_playback(page)
                    _time.sleep(min(3.0, wait_seconds))
                except Exception:
                    pass
                context.close()
                browser.close()
            return dedupe_candidates(filter_candidates(candidates))
        except Exception as exc:
            last_exc = exc
            candidates = []

    if last_exc is not None:
        raise last_exc
    return []


# ---------------------------------------------------------------------------
# yt-dlp command builder for fallback candidates


def build_yt_dlp_command_for_candidate(
    candidate_url: str,
    *,
    out_dir: Path,
    referer: str,
    origin: str,
    yt_dlp_executable: "str | list[str]" = "yt-dlp",
    user_agent: str = DEFAULT_USER_AGENT,
    browser: Optional[str] = None,
    cookie_file: Optional[str] = None,
    concurrent_fragments: int = 8,
    merge_output_format: str = "mp4",
    ffmpeg_location: Optional[str] = None,
    max_dl_speed: Optional[float] = None,
    max_height: Optional[int] = None,
    output_template: Optional[Path] = None,
    extra_args: Sequence[str] = (),
) -> List[str]:
    """Build a yt-dlp command to download a discovered fallback candidate URL."""
    exe = list(yt_dlp_executable) if isinstance(yt_dlp_executable, (list, tuple)) else [yt_dlp_executable]
    cmd = [*exe, "--newline", "--no-playlist"]
    if browser:
        cmd += ["--cookies-from-browser", browser]
    if cookie_file:
        cmd += ["--cookies", cookie_file]
    cmd += ["--referer", referer, "--add-header", f"Origin:{origin}"]
    if user_agent:
        cmd += ["--user-agent", user_agent]
    if concurrent_fragments > 0:
        cmd += ["--concurrent-fragments", str(concurrent_fragments)]
    if merge_output_format:
        cmd += ["--merge-output-format", merge_output_format]
    if ffmpeg_location:
        cmd += ["--ffmpeg-location", ffmpeg_location]
    if max_dl_speed and max_dl_speed > 0:
        cmd += ["--limit-rate", f"{max_dl_speed:.2f}M"]
    if max_height and max_height > 0:
        fmt = f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best"
        cmd += ["--format", fmt]
    cmd += ["-o", str(output_template or (out_dir / "%(title)s.%(ext)s"))]
    cmd += list(extra_args)
    cmd.append(candidate_url)
    return cmd
