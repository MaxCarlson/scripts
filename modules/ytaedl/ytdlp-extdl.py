from __future__ import annotations

import argparse
import dataclasses
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable, Optional, Protocol, Sequence


DEFAULT_OUTPUT_TEMPLATE = "%(title)s.%(ext)s"
DEFAULT_BROWSER = "firefox"
DEFAULT_CAPTURE_BROWSER = "auto"
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

DASH_CONTENT_TYPES = {
    "application/dash+xml",
}

IGNORED_URL_PARTS = (
    "google-analytics",
    "googletagmanager",
    "doubleclick",
    "facebook.com/tr",
    "analytics",
    "adsystem",
    "adservice",
)

ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_RESET = "\033[0m"
SPINNER_FRAMES = "|/-\\"


class DefaultHelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


class CommandRunner(Protocol):
    def __call__(self, command: Sequence[str], *, dry_run: bool) -> "CommandResult":
        ...


@dataclasses.dataclass(frozen=True)
class MediaCandidate:
    url: str
    kind: str
    source: str
    score: int
    content_type: str = ""
    note: str = ""


@dataclasses.dataclass(frozen=True)
class CommandResult:
    return_code: int
    command: list[str]
    output: str = ""


@dataclasses.dataclass(frozen=True)
class RescueDownloadOptions:
    output_template: str = DEFAULT_OUTPUT_TEMPLATE
    output_directory: Optional[str] = None
    browser: Optional[str] = DEFAULT_BROWSER
    cookie_file: Optional[str] = None
    user_agent: str = DEFAULT_USER_AGENT
    yt_dlp_executable: str = "yt-dlp"
    ffmpeg_location: Optional[str] = None
    concurrent_fragments: int = 8
    merge_output_format: str = "mp4"
    timeout_seconds: float = 30.0
    browser_wait_seconds: float = 12.0
    capture_browser: str = DEFAULT_CAPTURE_BROWSER
    show_browser: bool = False
    browser_state_path: Optional[str] = None
    skip_normal_yt_dlp: bool = False
    skip_static_html_scan: bool = False
    skip_browser_capture: bool = False
    include_segments: bool = False
    candidate_contains: tuple[str, ...] = ()
    max_fallback_candidates: int = 5
    candidate_log_file: Optional[str] = None
    print_candidates: bool = False
    interactive: bool = False
    dry_run: bool = False
    verbose: bool = False
    yt_dlp_verbose: bool = False
    extra_yt_dlp_args: tuple[str, ...] = ()
    timing: bool = False        # Print per-attempt and per-URL timing summaries
    stop_on_start: bool = False  # Kill yt-dlp the instant the download begins (timing mode)


@dataclasses.dataclass
class AttemptTiming:
    """Records how long one download attempt took."""
    attempt_number: int
    description: str
    method_group: str   # "normal_ytdlp" | "static_html" | "browser_network"
    elapsed_s: float
    success: bool
    stopped_early: bool = False  # True when stop_on_start interrupted the download


@dataclasses.dataclass(frozen=True)
class RescueDownloadResult:
    success: bool
    method: str
    candidate: Optional[MediaCandidate]
    command_result: Optional[CommandResult]
    candidates: tuple[MediaCandidate, ...]


class StepLogger:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def step(self, label: str, message: str) -> None:
        if self.enabled:
            print(f"[step {label}] {message}")

    def detail(self, message: str) -> None:
        return

    def command(self, command: Sequence[str]) -> None:
        return


def color_text(message: str, color: str) -> str:
    if not sys.stdout.isatty():
        return message
    return f"{color}{message}{ANSI_RESET}"


def success_text(message: str) -> str:
    return color_text(message, ANSI_GREEN)


def failure_text(message: str) -> str:
    return color_text(message, ANSI_RED)


def print_attempt(attempt_number: int, method: str) -> None:
    print(f"Attempt {attempt_number}: {method}")


def print_attempt_success(attempt_number: int, method: str) -> None:
    print(success_text(f"Attempt {attempt_number} succeeded: {method} started/completed successfully."))


def print_attempt_failure(attempt_number: int, method: str, return_code: int) -> None:
    print(failure_text(f"Attempt {attempt_number} failed: {method} exited with code {return_code}."))


def wait_with_status(seconds: float, message: str, *, enabled: bool) -> None:
    if seconds <= 0:
        return

    if not enabled:
        time.sleep(seconds)
        return

    deadline = time.monotonic() + seconds
    frame_index = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        frame = SPINNER_FRAMES[frame_index % len(SPINNER_FRAMES)]
        sys.stdout.write(f"\r{message} {frame} {remaining:4.1f}s remaining")
        sys.stdout.flush()
        time.sleep(min(0.2, remaining))
        frame_index += 1

    sys.stdout.write("\r" + " " * shutil.get_terminal_size((120, 20)).columns + "\r")
    sys.stdout.flush()


def normalize_content_type(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def infer_origin(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Cannot infer origin from URL: {url}")
    return f"{parsed.scheme}://{parsed.netloc}"


def slugify_filename(value: str, *, fallback: str = "video") -> str:
    cleaned = urllib.parse.unquote(value).strip()
    cleaned = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", cleaned)
    cleaned = re.sub(r"[_\s]+", "-", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9.-]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip(".-")
    return cleaned or fallback


def infer_url_slug(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]

    for part in reversed(path_parts):
        slug = slugify_filename(part)
        if re.search(r"[A-Za-z]", slug):
            return slug

    if path_parts:
        return slugify_filename(path_parts[-1])

    return slugify_filename(parsed.netloc)


def has_ignored_url_part(url: str) -> bool:
    lowered = url.lower()
    return any(part in lowered for part in IGNORED_URL_PARTS)


def looks_like_preview_video(lowered_url: str) -> bool:
    return (
        "/pv/" in lowered_url
        or "/preview" in lowered_url
        or re.search(r"(^|[/_-])pv[_-]", lowered_url) is not None
    )


def looks_like_embedded_player_url(lowered_url: str) -> bool:
    parsed = urllib.parse.urlparse(lowered_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if has_ignored_url_part(lowered_url):
        return False
    if "mydaddy.cc" in host and "/video/" in path:
        return True
    return any(part in path for part in ("/embed/", "/player/", "/video/"))


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
            return "segment", 20, "transport-stream segment; useful as evidence, not ideal target"

        if ".mp4" in lowered_url:
            score = 70
            note = "direct mp4 URL"
            if looks_like_preview_video(lowered_url):
                score -= 35
                note = "direct mp4 URL, but it looks like a preview"
            return "direct", score + infer_resolution_bonus(lowered_url), note

        return "direct", 60, "video content type"

    if ".mp4" in lowered_url:
        score = 55
        note = "mp4-looking URL"
        if looks_like_preview_video(lowered_url):
            score -= 35
            note = "mp4-looking URL, but it looks like a preview"
        return "direct", score + infer_resolution_bonus(lowered_url), note

    if ".ts" in lowered_url:
        return "segment", 15, "transport-stream segment; not ideal target"

    if looks_like_embedded_player_url(lowered_url):
        return "embed", 65, "embedded player URL; let yt-dlp resolve media from this page"

    return None, 0, "not recognized as downloadable media"


def make_candidate(
    url: str,
    *,
    source: str,
    content_type: str = "",
    score_adjustment: int = 0,
) -> Optional[MediaCandidate]:
    cleaned_url = html.unescape(url.strip().strip('"').strip("'"))

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


def dedupe_candidates(candidates: Iterable[MediaCandidate]) -> list[MediaCandidate]:
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
    candidate_contains: Sequence[str],
    include_segments: bool,
) -> list[MediaCandidate]:
    filtered: list[MediaCandidate] = []
    lowered_terms = [term.lower() for term in candidate_contains]

    for candidate in candidates:
        if candidate.kind == "segment" and not include_segments:
            continue

        lowered_url = candidate.url.lower()
        if lowered_terms and not all(term in lowered_url for term in lowered_terms):
            continue

        filtered.append(candidate)

    return filtered


def absolutize_url(raw_url: str, base_url: str) -> str:
    return urllib.parse.urljoin(base_url, html.unescape(raw_url))


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


def extract_static_candidates(page_html: str, page_url: str) -> list[MediaCandidate]:
    candidates: list[MediaCandidate] = []

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
            candidate = make_candidate(
                absolute_url,
                source="static_html",
                score_adjustment=-5,
            )
            if candidate is not None:
                candidates.append(candidate)

    return dedupe_candidates(candidates)


def expand_embedded_player_candidates(
    candidates: Sequence[MediaCandidate],
    *,
    page_url: str,
    options: RescueDownloadOptions,
    logger: StepLogger,
) -> list[MediaCandidate]:
    expanded: list[MediaCandidate] = list(candidates)
    embed_candidates = [candidate for candidate in candidates if candidate.kind == "embed"]

    for candidate in embed_candidates:
        logger.step("2b", f"Inspecting embedded player: {candidate.url}")
        try:
            player_html = fetch_page_html(
                candidate.url,
                referer=page_url,
                origin=infer_origin(candidate.url),
                user_agent=options.user_agent,
                timeout_seconds=options.timeout_seconds,
            )
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            logger.step("2b", f"Embedded player inspection failed: {exc}")
            continue

        for player_candidate in extract_static_candidates(player_html, candidate.url):
            expanded.append(
                dataclasses.replace(
                    player_candidate,
                    source=f"{candidate.source}_embed",
                    score=player_candidate.score + 20,
                    note=f"{player_candidate.note}; discovered from embedded player",
                )
            )

    return dedupe_candidates(expanded)


def discover_static_media_candidates(
    page_url: str,
    *,
    options: RescueDownloadOptions,
    referer: str,
    origin: str,
    logger: StepLogger,
) -> list[MediaCandidate]:
    if options.skip_static_html_scan:
        logger.step("2", "Skipping static HTML media discovery because --skip_static_html_scan was passed.")
        return []

    logger.step("2", "Trying less-simple fallback: static HTML media discovery.")
    logger.detail("2a: Fetching page HTML with inferred Referer and Origin headers.")
    logger.detail(f"Referer: {referer}")
    logger.detail(f"Origin:  {origin}")

    try:
        page_html = fetch_page_html(
            page_url,
            referer=referer,
            origin=origin,
            user_agent=options.user_agent,
            timeout_seconds=options.timeout_seconds,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.detail(f"Static HTML fetch failed: {exc}")
        return []

    logger.detail("2b: Searching static HTML for .m3u8, .mpd, .mp4, and extensionless HLS-like URLs.")
    candidates = extract_static_candidates(page_html, page_url)
    candidates = expand_embedded_player_candidates(
        candidates,
        page_url=page_url,
        options=options,
        logger=logger,
    )
    candidates = prepare_candidates(
        candidates,
        options=options,
        logger=logger,
        step_label="2c",
        source_name="static HTML",
    )

    return candidates


def try_import_playwright_sync_api():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    return sync_playwright


def preferred_playwright_browsers(capture_browser: str, browser: Optional[str]) -> list[str]:
    if capture_browser != "auto":
        return [capture_browser]

    normalized_browser = (browser or "").lower()
    if normalized_browser in {"firefox"}:
        return ["firefox", "chromium", "webkit"]

    if normalized_browser in {"chrome", "chromium", "edge", "brave", "vivaldi"}:
        return ["chromium", "firefox", "webkit"]

    return ["chromium", "firefox", "webkit"]


def browser_extract_candidates(
    page_url: str,
    *,
    referer: str,
    origin: str,
    user_agent: str,
    timeout_seconds: float,
    wait_seconds: float,
    capture_browser: str,
    cookie_browser: Optional[str],
    show_browser: bool,
    browser_state_path: Optional[str],
    verbose: bool,
) -> list[MediaCandidate]:
    sync_playwright = try_import_playwright_sync_api()
    if sync_playwright is None:
        raise RuntimeError(
            "Playwright is not installed. Install it with: "
            "uv pip install playwright && python -m playwright install chromium"
        )

    last_error: Optional[Exception] = None

    for playwright_browser in preferred_playwright_browsers(capture_browser, cookie_browser):
        try:
            return browser_extract_candidates_with_backend(
                page_url,
                referer=referer,
                origin=origin,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                wait_seconds=wait_seconds,
                playwright_browser=playwright_browser,
                show_browser=show_browser,
                browser_state_path=browser_state_path,
                verbose=verbose,
            )
        except Exception as exc:
            last_error = exc
            if verbose:
                print(f"[browser] {playwright_browser} capture failed: {exc}")

    if last_error is not None:
        raise last_error

    return []


def browser_extract_candidates_with_backend(
    page_url: str,
    *,
    referer: str,
    origin: str,
    user_agent: str,
    timeout_seconds: float,
    wait_seconds: float,
    playwright_browser: str,
    show_browser: bool,
    browser_state_path: Optional[str],
    verbose: bool,
) -> list[MediaCandidate]:
    sync_playwright = try_import_playwright_sync_api()
    if sync_playwright is None:
        raise RuntimeError("Playwright is not installed.")

    candidates: list[MediaCandidate] = []

    with sync_playwright() as playwright:
        browser_factory = getattr(playwright, playwright_browser)
        browser = browser_factory.launch(headless=not show_browser)

        context_kwargs = {
            "user_agent": user_agent,
            "extra_http_headers": {
                "Referer": referer,
                "Origin": origin,
            },
        }

        if browser_state_path:
            context_kwargs["storage_state"] = browser_state_path

        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        def add_url_candidate(url: str, source: str, content_type: str = "") -> None:
            candidate = make_candidate(
                url,
                source=source,
                content_type=content_type,
            )
            if candidate is None:
                return

            candidates.append(candidate)

        def on_request(request) -> None:
            add_url_candidate(request.url, "browser_request")

        def on_response(response) -> None:
            headers = response.headers
            content_type = headers.get("content-type", "")
            add_url_candidate(response.url, "browser_response", content_type)

        page.on("request", on_request)
        page.on("response", on_response)

        if verbose:
            print(f"[browser] starting {playwright_browser} network capture")

        page.goto(page_url, wait_until="domcontentloaded", timeout=int(timeout_seconds * 1000))

        try:
            page.wait_for_load_state("networkidle", timeout=int(min(timeout_seconds, 10.0) * 1000))
        except Exception:
            pass

        trigger_playback(page, verbose=verbose)

        if show_browser:
            print(f"Browser is visible. You have {wait_seconds:.0f} seconds to click play or solve page UI.")

        wait_with_status(
            wait_seconds,
            f"[browser] collecting network traffic in {playwright_browser}",
            enabled=verbose,
        )

        try:
            trigger_playback(page, verbose=verbose)
            wait_with_status(
                min(3.0, wait_seconds),
                f"[browser] checking for late media requests in {playwright_browser}",
                enabled=verbose,
            )
        except Exception:
            pass

        context.close()
        browser.close()

    return dedupe_candidates(candidates)


def discover_browser_media_candidates(
    page_url: str,
    *,
    options: RescueDownloadOptions,
    referer: str,
    origin: str,
    logger: StepLogger,
) -> list[MediaCandidate]:
    if options.skip_browser_capture:
        logger.step("3", "Skipping browser/network media discovery because --skip_browser_capture was passed.")
        return []

    logger.step("3", "Trying most-complex fallback: browser network capture.")
    logger.detail("3a: Launching Playwright browser context.")
    logger.detail("3b: Capturing request URLs and response content types.")
    logger.detail("3c: Auto-triggering playback by calling video.play(), clicking likely play buttons, and pressing Space.")
    logger.detail("3d: Detecting HLS by .m3u8 URLs and content types such as application/vnd.apple.mpegurl.")
    logger.detail("3e: Detecting DASH by .mpd URLs and application/dash+xml.")
    logger.detail("3f: Detecting direct media by video/* content type and .mp4 URLs.")

    try:
        candidates = browser_extract_candidates(
            page_url,
            referer=referer,
            origin=origin,
            user_agent=options.user_agent,
            timeout_seconds=options.timeout_seconds,
            wait_seconds=options.browser_wait_seconds,
            capture_browser=options.capture_browser,
            cookie_browser=options.browser,
            show_browser=options.show_browser,
            browser_state_path=options.browser_state_path,
            verbose=options.verbose,
        )
    except Exception as exc:
        print(f"Browser fallback extraction failed: {exc}", file=sys.stderr)
        return []

    candidates = prepare_candidates(
        candidates,
        options=options,
        logger=logger,
        step_label="3g",
        source_name="browser network",
    )

    return candidates


def trigger_playback(page, *, verbose: bool) -> None:
    script = """
    async () => {
        const result = {
            videos: 0,
            playCalls: 0,
            clicked: 0
        };

        const videos = Array.from(document.querySelectorAll("video"));
        result.videos = videos.length;

        for (const video of videos) {
            try {
                video.muted = true;
                video.playsInline = true;
                const playResult = video.play();
                result.playCalls += 1;
                if (playResult && typeof playResult.catch === "function") {
                    playResult.catch(() => {});
                }
            } catch (error) {}
        }

        const selectors = [
            "button",
            "[role='button']",
            ".play",
            ".play-button",
            ".vjs-big-play-button",
            ".jw-icon-playback",
            ".plyr__control",
            "[aria-label*='Play' i]",
            "[title*='Play' i]"
        ];

        const elements = [];
        for (const selector of selectors) {
            elements.push(...Array.from(document.querySelectorAll(selector)));
        }

        const unique = Array.from(new Set(elements));
        for (const element of unique.slice(0, 8)) {
            try {
                const rect = element.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) {
                    continue;
                }
                element.click();
                result.clicked += 1;
            } catch (error) {}
        }

        return result;
    }
    """

    try:
        result = page.evaluate(script)
    except Exception as exc:
        pass

    try:
        page.mouse.click(640, 360)
    except Exception:
        pass

    try:
        page.keyboard.press("Space")
    except Exception:
        pass


def build_effective_output_template(
    *,
    output_template: str,
    output_directory: Optional[str],
    page_url: Optional[str] = None,
) -> str:
    if output_template == DEFAULT_OUTPUT_TEMPLATE and page_url:
        output_template = f"{infer_url_slug(page_url)}.%(ext)s"

    if not output_directory:
        return output_template

    template_has_path = (
        "/" in output_template
        or "\\" in output_template
        or Path(output_template).is_absolute()
    )
    if template_has_path:
        return output_template

    normalized_dir = output_directory.rstrip("/\\")
    return f"{normalized_dir}/{output_template}"


def build_yt_dlp_command(
    target_url: str,
    *,
    options: RescueDownloadOptions,
    referer: str,
    origin: str,
) -> list[str]:
    command = [options.yt_dlp_executable]

    if options.yt_dlp_verbose:
        command.append("-v")

    if options.browser:
        command.extend(["--cookies-from-browser", options.browser])

    if options.cookie_file:
        command.extend(["--cookies", options.cookie_file])

    command.extend(["--referer", referer])
    command.extend(["--add-header", f"Origin:{origin}"])

    if options.user_agent:
        command.extend(["--user-agent", options.user_agent])

    if options.concurrent_fragments > 0:
        command.extend(["--concurrent-fragments", str(options.concurrent_fragments)])

    if options.merge_output_format:
        command.extend(["--merge-output-format", options.merge_output_format])

    if options.ffmpeg_location:
        command.extend(["--ffmpeg-location", options.ffmpeg_location])

    effective_output_template = build_effective_output_template(
        output_template=options.output_template,
        output_directory=options.output_directory,
        page_url=referer,
    )
    command.extend(["-o", effective_output_template])

    command.extend(options.extra_yt_dlp_args)
    command.append(target_url)

    return command


def run_command(command: Sequence[str], *, dry_run: bool, stop_on_start: bool = False) -> CommandResult:
    if dry_run:
        print(format_command(command))
        return CommandResult(return_code=0, command=list(command), output="")

    print("Download process running; yt-dlp progress will update in place when available.")

    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    output_parts: list[str] = []
    pending = ""
    progress_active = False

    assert process.stdout is not None
    while True:
        chunk = process.stdout.read(1)
        if chunk == "":
            if process.poll() is not None:
                break
            time.sleep(0.05)
            continue

        output_parts.append(chunk)

        if chunk == "\r":
            progress_active = _emit_process_line(pending, progress_active=progress_active, final=False)
            if stop_on_start and progress_active:
                # A [download] progress line was rendered — download has started; kill now.
                try:
                    process.terminate()
                except Exception:
                    pass
                pending = ""
                break
            pending = ""
            continue

        if chunk == "\n":
            progress_active = _emit_process_line(pending, progress_active=progress_active, final=True)
            if stop_on_start and progress_active:
                # yt-dlp uses \n (not \r) when stdout is a pipe; catch that case too.
                try:
                    process.terminate()
                except Exception:
                    pass
                pending = ""
                break
            pending = ""
            continue

        pending += chunk

    if pending:
        progress_active = _emit_process_line(pending, progress_active=progress_active, final=True)

    if progress_active:
        print()

    return_code = process.wait()

    return CommandResult(
        return_code=return_code,
        command=list(command),
        output="".join(output_parts),
    )


def _is_yt_dlp_progress_line(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith("[download]")
        and "%" in stripped
        and (
            " ETA " in stripped
            or " of " in stripped
            or stripped.startswith("[download] 100%")
        )
    )


def _emit_process_line(line: str, *, progress_active: bool, final: bool) -> bool:
    cleaned = line.rstrip("\r\n")
    if not cleaned:
        return progress_active

    if _is_yt_dlp_progress_line(cleaned):
        sys.stdout.write("\r" + cleaned[:shutil.get_terminal_size((120, 20)).columns - 1])
        sys.stdout.flush()
        return True

    if progress_active:
        print()

    print(cleaned)
    return False


def format_command(command: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(command))

    import shlex

    return shlex.join(command)


def ensure_executable_exists(executable: str) -> None:
    if shutil.which(executable) is None and not Path(executable).exists():
        raise FileNotFoundError(
            f"Executable not found: {executable}. Install it or pass --yt_dlp_executable."
        )


def ensure_output_directory(output_directory: Optional[str]) -> None:
    if output_directory:
        Path(output_directory).mkdir(parents=True, exist_ok=True)


def write_candidates(path: str, candidates: Sequence[MediaCandidate]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [dataclasses.asdict(candidate) for candidate in candidates]
    target.write_text(json.dumps(payload, indent=4, sort_keys=True) + "\n", encoding="utf-8")


def _extract_domain_simple(url: str) -> str:
    """Extract base domain from URL, stripping www./m. prefixes."""
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        if not host:
            return ""
        if ":" in host:
            host = host.rsplit(":", 1)[0]
        for prefix in ("www.", "m."):
            if host.startswith(prefix):
                host = host[len(prefix):]
        return host
    except Exception:
        return ""


def run_sample_mode(folder: Path, count: int, seed: int) -> int:
    """
    Scan all .txt URL files under *folder*, group URLs by base domain,
    then print *count* randomly-selected URLs per domain to stdout.

    Output is one URL per line — suitable for piping into ``--url-file``.
    """
    import random

    rng = random.Random(seed)

    txt_files = sorted(folder.rglob("*.txt"))
    if not txt_files:
        print(f"No .txt files found in {folder}", file=sys.stderr)
        return 2

    domain_map: dict[str, list[str]] = {}
    seen_urls: set[str] = set()
    total_files = 0

    for txt_file in txt_files:
        try:
            lines = read_url_file(str(txt_file))
        except Exception:
            continue
        total_files += 1
        for url in lines:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            domain = _extract_domain_simple(url)
            if domain:
                domain_map.setdefault(domain, []).append(url)

    if not domain_map:
        print("No valid URLs found.", file=sys.stderr)
        return 2

    # Print sample header to stderr so stdout stays clean for piping
    print(
        f"# Sampled from {total_files} file(s)  |  "
        f"{len(domain_map)} unique domain(s)  |  "
        f"{len(seen_urls)} total URLs  |  "
        f"seed={seed}  count={count}",
        file=sys.stderr,
    )

    output_count = 0
    for domain in sorted(domain_map.keys()):
        urls = domain_map[domain]
        sample = rng.sample(urls, min(count, len(urls)))
        for url in sample:
            print(url)
            output_count += 1

    print(f"# {output_count} URLs printed ({count} per domain)", file=sys.stderr)
    return 0


def read_url_file(path: str) -> list[str]:
    urls: list[str] = []
    for line_number, raw_line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(("http://", "https://")):
            raise ValueError(f"{path}:{line_number} is not an HTTP URL: {line}")
        urls.append(line)
    return urls


def print_candidate(candidate: MediaCandidate, *, prefix: str = "") -> None:
    print(
        f"{prefix}score={candidate.score:3d} "
        f"kind={candidate.kind:7s} "
        f"source={candidate.source:16s} "
        f"type={candidate.content_type or '-'}"
    )
    print(f"{prefix}note: {candidate.note}")
    print(f"{prefix}url:  {candidate.url}")


def print_candidates(candidates: Sequence[MediaCandidate]) -> None:
    if not candidates:
        print("No media candidates discovered.")
        return

    print("Discovered media candidates:")
    for index, candidate in enumerate(candidates, start=1):
        print(f"{index:02d}.", end=" ")
        print_candidate(candidate)


def choose_interactive_candidate(candidates: Sequence[MediaCandidate]) -> Optional[MediaCandidate]:
    print_candidates(candidates)

    while True:
        raw_value = input("Candidate number to try first, Enter for best, or q to quit: ").strip()
        if raw_value == "":
            return candidates[0] if candidates else None
        if raw_value.lower() in {"q", "quit", "exit"}:
            return None

        try:
            index = int(raw_value)
        except ValueError:
            print("Enter a number, Enter, or q.")
            continue

        if 1 <= index <= len(candidates):
            return candidates[index - 1]

        print(f"Enter a number between 1 and {len(candidates)}.")


def prepare_candidates(
    candidates: Sequence[MediaCandidate],
    *,
    options: RescueDownloadOptions,
    logger: StepLogger,
    step_label: str,
    source_name: str,
) -> list[MediaCandidate]:
    logger.step(step_label, f"Ranking and filtering {source_name} candidates.")
    logger.detail(f"Raw candidates found: {len(candidates)}")

    prepared = dedupe_candidates(candidates)
    logger.detail(f"After de-duplication: {len(prepared)}")

    prepared = filter_candidates(
        prepared,
        candidate_contains=options.candidate_contains,
        include_segments=options.include_segments,
    )
    logger.detail(f"After user filters and segment policy: {len(prepared)}")

    if options.candidate_log_file and prepared:
        write_candidates(options.candidate_log_file, prepared)
        logger.detail(f"Wrote candidates to: {options.candidate_log_file}")

    if options.print_candidates:
        print_candidates(prepared)

    return prepared


def order_candidates_for_download(
    candidates: Sequence[MediaCandidate],
    *,
    first_candidate: Optional[MediaCandidate],
    max_candidates: int,
) -> list[MediaCandidate]:
    ordered = list(candidates)

    if first_candidate is not None:
        ordered = [first_candidate] + [
            candidate
            for candidate in ordered
            if candidate.url != first_candidate.url
        ]

    if max_candidates > 0:
        ordered = ordered[:max_candidates]

    return ordered


def download_candidates_until_success(
    candidates: Sequence[MediaCandidate],
    *,
    options: RescueDownloadOptions,
    referer: str,
    origin: str,
    logger: StepLogger,
    method_prefix: str,
    step_label: str,
    attempt_start: int,
    timings: Optional[list] = None,
) -> RescueDownloadResult:
    logger.step(step_label, f"Trying {method_prefix} fallback candidates with yt-dlp.")
    logger.detail(f"Candidate count: {len(candidates)}")

    if not candidates:
        print(f"No downloadable candidates found for {method_prefix}; moving on.")
        return RescueDownloadResult(
            success=False,
            method=f"{method_prefix}_no_candidates",
            candidate=None,
            command_result=None,
            candidates=tuple(candidates),
        )

    selected_first: Optional[MediaCandidate] = None
    if options.interactive:
        selected_first = choose_interactive_candidate(candidates)
        if selected_first is None:
            print("No candidate selected.")
            return RescueDownloadResult(
                success=False,
                method="interactive_cancelled",
                candidate=None,
                command_result=None,
                candidates=tuple(candidates),
            )

    ordered_candidates = order_candidates_for_download(
        candidates,
        first_candidate=selected_first,
        max_candidates=options.max_fallback_candidates,
    )

    last_result: Optional[CommandResult] = None
    last_candidate: Optional[MediaCandidate] = None

    for index, candidate in enumerate(ordered_candidates, start=1):
        if candidate.kind == "segment" and not options.include_segments:
            continue

        attempt_number = attempt_start + index - 1
        method_name = f"{method_prefix} {candidate.kind} candidate {index}/{len(ordered_candidates)}"
        print_attempt(attempt_number, method_name)
        logger.detail(f"Candidate URL: {candidate.url}")

        command = build_yt_dlp_command(
            candidate.url,
            options=options,
            referer=referer,
            origin=origin,
        )
        logger.command(command)

        _t0 = time.time()
        result = run_command(command, dry_run=options.dry_run, stop_on_start=options.stop_on_start)
        _elapsed = time.time() - _t0
        last_result = result
        last_candidate = candidate

        _method_group = "static_html" if method_prefix.startswith("static") else "browser_network"
        if timings is not None:
            timings.append(AttemptTiming(
                attempt_number=attempt_number,
                description=method_name,
                method_group=_method_group,
                elapsed_s=_elapsed,
                success=result.return_code == 0,
                stopped_early=options.stop_on_start and result.return_code == 0,
            ))
        if options.timing:
            _status = "stopped (download started)" if (options.stop_on_start and result.return_code == 0) else (
                "succeeded" if result.return_code == 0 else f"failed rc={result.return_code}")
            print(f"  ↳ Attempt {attempt_number} elapsed: {_elapsed:.2f}s  [{_status}]")

        if result.return_code == 0:
            print_attempt_success(attempt_number, method_name)
            return RescueDownloadResult(
                success=True,
                method=f"{method_prefix}_{candidate.kind}",
                candidate=candidate,
                command_result=result,
                candidates=tuple(candidates),
            )

        print_attempt_failure(attempt_number, method_name, result.return_code)

    print(f"All {method_prefix} fallback candidates failed.", file=sys.stderr)
    return RescueDownloadResult(
        success=False,
        method=f"{method_prefix}_failed",
        candidate=last_candidate,
        command_result=last_result,
        candidates=tuple(candidates),
    )


def download_video_with_fallback(
    page_url: str,
    *,
    options: RescueDownloadOptions,
    command_runner: CommandRunner = run_command,
    timings: Optional[list] = None,
) -> RescueDownloadResult:
    logger = StepLogger(options.verbose)

    ensure_executable_exists(options.yt_dlp_executable)
    ensure_output_directory(options.output_directory)

    referer = page_url
    origin = infer_origin(page_url)

    logger.step("0", "Initialized automatic download workflow.")
    logger.detail(f"URL:                 {page_url}")
    logger.detail(f"Browser cookies:     {options.browser or 'disabled'}")
    logger.detail(f"Referer:             {referer} (auto-inferred)")
    logger.detail(f"Origin:              {origin} (auto-inferred)")
    logger.detail(f"Output template:     {build_effective_output_template(output_template=options.output_template, output_directory=options.output_directory)}")
    logger.detail("Strategy order:      normal yt-dlp -> static HTML media URLs -> browser/network capture")

    if not options.skip_normal_yt_dlp:
        logger.step("1", "Trying simplest method: normal yt-dlp page download.")
        normal_command = build_yt_dlp_command(
            page_url,
            options=options,
            referer=referer,
            origin=origin,
        )
        logger.command(normal_command)

        print_attempt(1, "normal yt-dlp page download")
        _t1 = time.time()
        normal_result = command_runner(normal_command, dry_run=options.dry_run,
                                       stop_on_start=options.stop_on_start)
        _elapsed1 = time.time() - _t1
        _stopped = options.stop_on_start and normal_result.return_code == 0
        if timings is not None:
            timings.append(AttemptTiming(
                attempt_number=1,
                description="normal yt-dlp page download",
                method_group="normal_ytdlp",
                elapsed_s=_elapsed1,
                success=normal_result.return_code == 0,
                stopped_early=_stopped,
            ))
        if options.timing:
            _st = "stopped (download started)" if _stopped else (
                "succeeded" if normal_result.return_code == 0 else f"failed rc={normal_result.return_code}")
            print(f"  ↳ Attempt 1 elapsed: {_elapsed1:.2f}s  [{_st}]")

        if normal_result.return_code == 0:
            print_attempt_success(1, "normal yt-dlp page download")
            return RescueDownloadResult(
                success=True,
                method="normal_yt_dlp",
                candidate=None,
                command_result=normal_result,
                candidates=(),
            )

        logger.detail(f"Normal yt-dlp failed with exit code {normal_result.return_code}.")
        print_attempt_failure(1, "normal yt-dlp page download", normal_result.return_code)
        print("Next: static HTML media discovery.")
    else:
        logger.step("1", "Skipping normal yt-dlp page download because --skip_normal_yt_dlp was passed.")

    fallback_attempt_start = 2 if not options.skip_normal_yt_dlp else 1
    static_candidates = discover_static_media_candidates(
        page_url,
        options=options,
        referer=referer,
        origin=origin,
        logger=logger,
    )
    static_result = download_candidates_until_success(
        static_candidates,
        options=options,
        referer=referer,
        origin=origin,
        logger=logger,
        method_prefix="static_html",
        step_label="2d",
        attempt_start=fallback_attempt_start,
        timings=timings,
    )
    if static_result.success:
        return static_result

    print("Next: browser/network capture.")
    browser_candidates = discover_browser_media_candidates(
        page_url,
        options=options,
        referer=referer,
        origin=origin,
        logger=logger,
    )
    static_attempt_count = min(
        len(static_candidates),
        options.max_fallback_candidates if options.max_fallback_candidates > 0 else len(static_candidates),
    )
    browser_result = download_candidates_until_success(
        browser_candidates,
        options=options,
        referer=referer,
        origin=origin,
        logger=logger,
        method_prefix="browser_network",
        step_label="3h",
        attempt_start=fallback_attempt_start + static_attempt_count,
        timings=timings,
    )
    if browser_result.success:
        return browser_result

    combined_candidates = dedupe_candidates([*static_candidates, *browser_candidates])
    return RescueDownloadResult(
        success=False,
        method="all_methods_failed",
        candidate=browser_result.candidate or static_result.candidate,
        command_result=browser_result.command_result or static_result.command_result,
        candidates=tuple(combined_candidates),
    )


def _timing_stats(values: list[float]) -> str:
    if not values:
        return "n/a"
    values = sorted(values)
    n = len(values)
    mn = values[0]
    mx = values[-1]
    avg = sum(values) / n
    mid = n // 2
    median = values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2
    return f"min={mn:.1f}s  avg={avg:.1f}s  median={median:.1f}s  max={mx:.1f}s  (n={n})"


def _print_timing_summary(label: str, timings: list[AttemptTiming], group: Optional[str] = None) -> None:
    subset = [t for t in timings if group is None or t.method_group == group]
    if not subset:
        return
    values = [t.elapsed_s for t in subset]
    n_ok = sum(1 for t in subset if t.success)
    print(f"  {label:<22}: {_timing_stats(values)}  succeeded={n_ok}/{len(subset)}")


def download_urls(
    urls: Sequence[str],
    *,
    options: RescueDownloadOptions,
    command_runner: CommandRunner = run_command,
) -> list[RescueDownloadResult]:
    results: list[RescueDownloadResult] = []
    total = len(urls)
    all_timings: list[AttemptTiming] = []

    for index, url in enumerate(urls, start=1):
        if total > 1:
            print(f"\nURL {index}/{total}: {url}")

        url_timings: list[AttemptTiming] = []
        try:
            result = download_video_with_fallback(
                url,
                options=options,
                command_runner=command_runner,
                timings=url_timings if options.timing else None,
            )
        except Exception as exc:
            print(failure_text(f"URL {index}/{total} failed before download attempts: {exc}"), file=sys.stderr)
            result = RescueDownloadResult(
                success=False,
                method="exception",
                candidate=None,
                command_result=None,
                candidates=(),
            )

        results.append(result)
        all_timings.extend(url_timings)

        if options.timing and url_timings:
            total_url_s = sum(t.elapsed_s for t in url_timings)
            print(f"\n  ── Attempt timing for this URL (total active time: {total_url_s:.1f}s) ──")
            for t in url_timings:
                mark = "✓" if t.success else "✗"
                extra = " [stopped early]" if t.stopped_early else ""
                print(f"    Attempt {t.attempt_number:>2} [{mark}]  {t.elapsed_s:6.2f}s  {t.description}{extra}")

        if total > 1 and result.success:
            print(success_text(f"URL {index}/{total} completed with method: {result.method}"))
        elif total > 1:
            print(failure_text(f"URL {index}/{total} failed."))

    if options.timing and all_timings and total > 1:
        print("\n" + "=" * 70)
        print("MASTER TIMING SUMMARY")
        print("=" * 70)
        _print_timing_summary("normal yt-dlp",    all_timings, "normal_ytdlp")
        _print_timing_summary("static_html",       all_timings, "static_html")
        _print_timing_summary("browser_network",   all_timings, "browser_network")
        print("  " + "-" * 60)
        _print_timing_summary("ALL attempts",      all_timings, None)
        print("=" * 70)

    return results


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ytdlp-extdl",
        formatter_class=DefaultHelpFormatter,
        description=(
            "Download a video with yt-dlp, then automatically fall back to discovering "
            "HLS/DASH/direct media URLs from the page when normal yt-dlp extraction fails."
        ),
        epilog=(
            "Normal use:\n"
            "  python .\\ytdlp-extdl.py -u \"PAGE_URL\"\n\n"
            "Batch use with one URL per line:\n"
            "  python .\\ytdlp-extdl.py --url-file .\\urls.txt -d .\\downloads\n\n"
            "Common use with output directory:\n"
            "  python .\\ytdlp-extdl.py -u \"PAGE_URL\" -d .\\downloads\n\n"
            "Manual browser fallback when video only loads after clicking play:\n"
            "  python .\\ytdlp-extdl.py -u \"PAGE_URL\" -g -p\n\n"
            "Verbose diagnostic workflow:\n"
            "  python .\\ytdlp-extdl.py -u \"PAGE_URL\" -v\n\n"
            "Naming convention:\n"
            "  The default yt-dlp output template is title + extension only.\n"
            "  With -d, it is applied as <output_dir>/%(title)s.%(ext)s.\n"
        ),
    )

    input_group = parser.add_argument_group("input arguments")
    input_group.add_argument(
        "-u",
        "--url",
        default=None,
        help="Page URL to download. Use this or --url-file.",
    )
    input_group.add_argument(
        "-U",
        "--url-file",
        dest="url_file",
        default=None,
        help="Text file containing one page URL per line. Blank lines and lines starting with # are ignored.",
    )

    common = parser.add_argument_group("common optional arguments")
    common.add_argument(
        "-b",
        "--browser",
        default=DEFAULT_BROWSER,
        help=(
            "Browser used for yt-dlp cookies. Use 'none' to disable browser cookies. "
            "Referer and Origin are inferred automatically from each input URL."
        ),
    )
    common.add_argument(
        "-d",
        "--output_directory",
        default=None,
        help="Optional output directory. Output is written as <output_directory>/%%(title)s.%%(ext)s.",
    )
    common.add_argument(
        "-o",
        "--output_template",
        default=DEFAULT_OUTPUT_TEMPLATE,
        help="yt-dlp output template. Default matches the existing downloader naming convention.",
    )
    common.add_argument(
        "-g",
        "--show_browser",
        action="store_true",
        help="Show the fallback browser window so you can manually click play if needed.",
    )
    common.add_argument(
        "-p",
        "--print_candidates",
        action="store_true",
        help="Print discovered fallback media candidates before trying them.",
    )
    common.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Prompt for which discovered fallback candidate to try first.",
    )
    common.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Print detailed step-by-step workflow diagnostics: normal yt-dlp attempt, "
            "static HTML discovery, browser/network discovery, candidate ranking, and fallback attempts."
        ),
    )

    advanced = parser.add_argument_group("advanced optional arguments")
    advanced.add_argument(
        "-y",
        "--yt_dlp_executable",
        default="yt-dlp",
        help="yt-dlp executable name or full path.",
    )
    advanced.add_argument(
        "-f",
        "--ffmpeg_location",
        default=None,
        help="Optional ffmpeg location passed through to yt-dlp.",
    )
    advanced.add_argument(
        "-k",
        "--cookie_file",
        default=None,
        help="Optional cookie file passed to yt-dlp.",
    )
    advanced.add_argument(
        "-A",
        "--user_agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent used for page fetch, browser capture, and yt-dlp.",
    )
    advanced.add_argument(
        "-F",
        "--concurrent_fragments",
        type=int,
        default=8,
        help="yt-dlp concurrent fragment count for HLS/DASH downloads.",
    )
    advanced.add_argument(
        "-m",
        "--merge_output_format",
        default="mp4",
        help="yt-dlp merge output format.",
    )
    advanced.add_argument(
        "-t",
        "--timeout_seconds",
        type=float,
        default=30.0,
        help="Page fetch and browser navigation timeout in seconds.",
    )
    advanced.add_argument(
        "-w",
        "--browser_wait_seconds",
        type=float,
        default=12.0,
        help="Seconds to collect browser network traffic after page load/playback trigger.",
    )
    advanced.add_argument(
        "-C",
        "--capture_browser",
        choices=["auto", "chromium", "firefox", "webkit"],
        default=DEFAULT_CAPTURE_BROWSER,
        help="Playwright browser backend for fallback network capture.",
    )
    advanced.add_argument(
        "-S",
        "--browser_state_path",
        default=None,
        help="Optional Playwright storage_state JSON path for logged-in browser state.",
    )
    advanced.add_argument(
        "-n",
        "--dry_run",
        action="store_true",
        help="Print yt-dlp commands instead of executing downloads.",
    )
    advanced.add_argument(
        "-V",
        "--yt_dlp_verbose",
        action="store_true",
        help="Pass -v to yt-dlp.",
    )
    advanced.add_argument(
        "-s",
        "--skip_normal_yt_dlp",
        action="store_true",
        help="Skip normal page-url yt-dlp attempt and immediately discover fallback media URLs.",
    )
    advanced.add_argument(
        "-H",
        "--skip_static_html_scan",
        action="store_true",
        help="Skip static HTML media URL scanning.",
    )
    advanced.add_argument(
        "-x",
        "--skip_browser_capture",
        action="store_true",
        help="Skip Playwright browser network capture.",
    )
    advanced.add_argument(
        "-M",
        "--max_fallback_candidates",
        type=int,
        default=5,
        help="Maximum fallback media candidates to try. Use 0 for all candidates.",
    )
    advanced.add_argument(
        "-q",
        "--candidate_contains",
        action="append",
        default=[],
        help="Only keep candidate URLs containing this substring. Repeat to require multiple substrings.",
    )
    advanced.add_argument(
        "-l",
        "--candidate_log_file",
        default=None,
        help="Write discovered fallback candidates to this JSON file.",
    )
    advanced.add_argument(
        "-T",
        "--include_segments",
        action="store_true",
        help="Include .ts segment URLs as last-resort candidates. Usually not useful.",
    )
    advanced.add_argument(
        "-a",
        "--extra_yt_dlp_arg",
        action="append",
        default=[],
        help="Extra argument appended to every yt-dlp command. Repeat as needed.",
    )
    sample = parser.add_argument_group("domain-sampling mode (--sample-dir replaces --url / --url-file)")
    sample.add_argument(
        "-Q",
        "--sample-dir",
        default=None,
        metavar="DIR",
        help=(
            "Scan all .txt URL files under DIR, group URLs by base domain, "
            "and print a random sample to stdout (one URL per line). "
            "Output can be piped directly into --url-file for batch testing."
        ),
    )
    sample.add_argument(
        "-E",
        "--sample-count",
        type=int,
        default=1,
        metavar="N",
        help="Number of URLs to sample per unique base domain (default: 1).",
    )
    sample.add_argument(
        "-R",
        "--sample-seed",
        type=int,
        default=0,
        metavar="SEED",
        help="Random seed for reproducible sampling (default: 0).",
    )

    advanced.add_argument(
        "-Z",
        "--timing",
        action="store_true",
        help=(
            "Print per-attempt elapsed time, per-URL summary, and a master summary "
            "(min/avg/median/max) across all attempt types. Useful for tuning stall timeouts."
        ),
    )
    advanced.add_argument(
        "-X",
        "--stop-on-start",
        action="store_true",
        help=(
            "Kill yt-dlp the instant a download actually begins (first [download] progress "
            "line). Combine with --timing / -Z and a URL file to measure time-to-start for "
            "each attempt type without waiting for full downloads."
        ),
    )

    args = parser.parse_args(argv)

    # Exactly one input mode must be chosen
    input_modes = [bool(args.url), bool(args.url_file), bool(args.sample_dir)]
    if sum(input_modes) != 1:
        parser.error("pass exactly one of --url, --url-file, or --sample-dir")

    if isinstance(args.browser, str) and args.browser.strip().lower() in {"", "none", "false", "off", "no"}:
        args.browser = None

    return args


def options_from_args(args: argparse.Namespace) -> RescueDownloadOptions:
    return RescueDownloadOptions(
        output_template=args.output_template,
        output_directory=args.output_directory,
        browser=args.browser,
        cookie_file=args.cookie_file,
        user_agent=args.user_agent,
        yt_dlp_executable=args.yt_dlp_executable,
        ffmpeg_location=args.ffmpeg_location,
        concurrent_fragments=args.concurrent_fragments,
        merge_output_format=args.merge_output_format,
        timeout_seconds=args.timeout_seconds,
        browser_wait_seconds=args.browser_wait_seconds,
        capture_browser=args.capture_browser,
        show_browser=args.show_browser,
        browser_state_path=args.browser_state_path,
        skip_normal_yt_dlp=args.skip_normal_yt_dlp,
        skip_static_html_scan=args.skip_static_html_scan,
        skip_browser_capture=args.skip_browser_capture,
        include_segments=args.include_segments,
        candidate_contains=tuple(args.candidate_contains),
        max_fallback_candidates=args.max_fallback_candidates,
        candidate_log_file=args.candidate_log_file,
        print_candidates=args.print_candidates,
        interactive=args.interactive,
        dry_run=args.dry_run,
        verbose=args.verbose,
        yt_dlp_verbose=args.yt_dlp_verbose,
        extra_yt_dlp_args=tuple(args.extra_yt_dlp_arg),
        timing=args.timing,
        stop_on_start=args.stop_on_start,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    # Domain sampling mode — prints URLs to stdout, no downloads
    if args.sample_dir:
        return run_sample_mode(
            folder=Path(args.sample_dir).expanduser().resolve(),
            count=args.sample_count,
            seed=args.sample_seed,
        )

    options = options_from_args(args)

    try:
        urls = [args.url] if args.url else read_url_file(args.url_file)
        if not urls:
            print("No URLs to download.", file=sys.stderr)
            return 2

        results = download_urls(
            urls,
            options=options,
        )
    except Exception as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 2

    failures = [result for result in results if not result.success]
    if len(urls) > 1:
        print(f"\nBatch complete: {len(urls) - len(failures)}/{len(urls)} downloaded successfully.")

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
