from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from .hdporncomics_patch import patch_recovery_hint
from .models import WorkerEvent
from .naming import DIRECTORY_TEMPLATE, FILENAME_TEMPLATE

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}
STATS_INTERVAL = 1.0
HEARTBEAT_INTERVAL = 0.5
MANGA18FX_CHAPTER_RE = re.compile(
    r"^chapter=(?P<index>\d+)/(?P<total>\d+)\s+title=(?P<title>.+?)\s+images=(?P<images>\d+)$"
)
MANGA18FX_PROGRESS_RE = re.compile(
    r"^progress\s+chapter=(?P<index>\d+)/(?P<total>\d+)\s+title=(?P<title>.+?)\s+"
    r"chapter_images=(?P<chapter_images>\d+)\s+downloaded=(?P<downloaded>\d+)\s+"
    r"skipped=(?P<skipped>\d+)\s+processed=(?P<processed>\d+)\s+discovered=(?P<discovered>\d+)$"
)
MANGA18FX_COMPLETE_RE = re.compile(
    r"^complete\s+destination=.*?\s+downloaded=(?P<downloaded>\d+)\s+skipped=(?P<skipped>\d+)$"
)


def _tree_stats(root: Path) -> tuple[int, int]:
    """Return complete-image count and bytes written, including active .part files."""
    images = size = 0
    if not root.exists():
        return images, size
    for path in root.rglob("*"):
        try:
            if not path.is_file() or path.name.endswith(".tmp"):
                continue
            size += path.stat().st_size
            if not path.name.endswith(".part") and path.suffix.lower() in IMAGE_SUFFIXES:
                images += 1
        except OSError:
            continue
    return images, size


def _identity(root: Path) -> tuple[str, str]:
    for path in root.rglob("*") if root.exists() else ():
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            relative = path.relative_to(root)
            site = relative.parts[0] if len(relative.parts) > 1 else "gallery"
            return site, path.parent.name
    return "", ""


def _unquote_title(value: str) -> str:
    title = value.strip()
    if len(title) >= 2 and title[0] == title[-1] and title[0] in {"'", '"'}:
        return title[1:-1]
    return title


def _parse_manga18fx_output(line: str) -> dict[str, Any] | None:
    """Parse stable native-backend status lines without interpreting arbitrary output."""
    chapter = MANGA18FX_CHAPTER_RE.match(line)
    if chapter:
        return {
            "kind": "chapter",
            "chapter_index": int(chapter.group("index")),
            "chapters_total": int(chapter.group("total")),
            "chapter_title": _unquote_title(chapter.group("title")),
            "chapter_images": int(chapter.group("images")),
        }

    progress = MANGA18FX_PROGRESS_RE.match(line)
    if progress:
        return {
            "kind": "progress",
            "chapter_index": int(progress.group("index")),
            "chapters_total": int(progress.group("total")),
            "chapter_title": _unquote_title(progress.group("title")),
            "chapter_images": int(progress.group("chapter_images")),
            "downloaded": int(progress.group("downloaded")),
            "skipped": int(progress.group("skipped")),
            "processed": int(progress.group("processed")),
            "discovered": int(progress.group("discovered")),
        }

    complete = MANGA18FX_COMPLETE_RE.match(line)
    if complete:
        downloaded = int(complete.group("downloaded"))
        skipped = int(complete.group("skipped"))
        total = downloaded + skipped
        return {
            "kind": "complete",
            "downloaded": downloaded,
            "skipped": skipped,
            "processed": total,
            "images_total": total,
        }
    return None


def _manga18fx_completion(downloaded: int, skipped: int) -> tuple[str, int, str]:
    """Classify a native Manga18FX completion using backend-reported counts."""
    total = downloaded + skipped
    if total <= 0:
        raise ValueError("Manga18FX reported zero downloaded or existing images")
    if downloaded == 0:
        return "skipped_archive", total, f"already complete: {skipped} images were present in the library"
    if skipped:
        return "succeeded", total, f"completed: {downloaded} downloaded, {skipped} already present"
    return "succeeded", total, ""


def _emit(args: argparse.Namespace, name: str, **data: Any) -> None:
    event = WorkerEvent(
        event=name,
        run_id=args.run_id,
        job_id=args.job_id,
        attempt_id=args.attempt_id,
        worker=args.worker,
        url=args.url,
        wall_time=time.time(),
        monotonic=time.monotonic(),
        data=data,
    )
    print(json.dumps(event.to_dict(), sort_keys=True), flush=True)


def _classify(returncode: int, tail: str) -> tuple[str, bool]:
    lowered = tail.lower()
    if "429" in lowered or "rate limit" in lowered:
        return "rate_limit", True
    if "database is locked" in lowered or "archive" in lowered and "locked" in lowered:
        return "archive", True
    auth_status = re.search(
        r"(?:http(?:/\d(?:\.\d)?)?|status(?: code)?|response)[^\n]{0,20}\b(?:401|403)\b"
        r"|\b(?:401|403)\b[^\n]{0,20}(?:forbidden|unauthorized)",
        lowered,
    )
    if auth_status or any(
        marker in lowered for marker in ("challengeerror", "cloudflare challenge", "authentication required")
    ):
        return "auth_challenge", False
    if "404" in lowered or "not found" in lowered:
        return "bad_url", False
    if "timeout" in lowered or "connection" in lowered or "http error 5" in lowered:
        return "http", True
    if "permission" in lowered or "no space" in lowered or "disk full" in lowered:
        return "filesystem", False
    return ("backend", returncode != 0)


def _merge_partial(partial: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for source in list(partial.iterdir()):
        target = destination / source.name
        if target.exists() and source.is_dir() and target.is_dir():
            _merge_partial(source, target)
            source.rmdir()
        elif not target.exists():
            shutil.move(str(source), str(target))
        elif source.is_file():
            source.unlink()
    if partial.exists() and not any(partial.iterdir()):
        partial.rmdir()


def _resolve_hdporncomics_executable(value: str | None) -> str:
    """Resolve the optional executable without guessing or using a shell."""
    configured = value or os.environ.get("HDPORNCOMICS_EXECUTABLE")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.parent != Path(".") or candidate.is_absolute():
            if not candidate.is_file():
                raise RuntimeError(f"hdporncomics executable was not found: {candidate}")
            return str(candidate.resolve())
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        raise RuntimeError(f"hdporncomics executable was not found on PATH: {configured}")
    resolved = shutil.which("hdporncomics")
    if resolved is None and os.name == "nt":
        resolved = shutil.which("hdporncomics.exe")
    if resolved is None:
        raise RuntimeError(
            "hdporncomics executable was not found; install it with: python -m pip install --upgrade hdporncomics"
        )
    return resolved


def _command(args: argparse.Namespace, partial: Path) -> list[str]:
    if args.backend == "native-nhentai":
        executable = shutil.which("nhentai")
        if not executable:
            raise RuntimeError("native nhentai executable is not installed")
        return [executable, "--id", args.url.rsplit("/", 2)[-2], "--output", str(partial)]
    if args.backend == "manga18fx":
        command = [
            sys.executable,
            "-m",
            "mangadl.manga18fx",
            "--destination",
            str(partial),
        ]
        if args.cookies:
            command.extend(["--cookies", args.cookies])
        command.append(args.url)
        return command
    if args.backend == "hdporncomics":
        return [
            _resolve_hdporncomics_executable(args.hdporncomics_executable),
            "--directory",
            str(args.destination),
            "--threads",
            str(args.hdporncomics_threads),
            "--force",
            "--manhwa",
            args.url,
        ]
    command = [
        sys.executable,
        "-m",
        "gallery_dl",
        "--no-input",
        "--verbose",
        "--destination",
        str(partial),
        "--option",
        f'directory=["{DIRECTORY_TEMPLATE}"]',
        "--option",
        f"filename={FILENAME_TEMPLATE}",
        "--download-archive",
        args.archive,
    ]
    if args.gallery_config:
        command.extend(["--config", args.gallery_config])
    if args.cookies:
        command.extend(["--cookies", args.cookies])
    if args.cookies_browser:
        command.extend(["--cookies-from-browser", args.cookies_browser])
    if getattr(args, "gallery_user_agent", None):
        command.extend(["--user-agent", args.gallery_user_agent])
    if args.rate:
        command.extend(["--limit-rate", args.rate])
    command.append(args.url)
    return command


def run(args: argparse.Namespace) -> int:
    partial = Path(args.partial_dir) / str(args.job_id)
    partial.mkdir(parents=True, exist_ok=True)
    Path(args.raw_log).parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    output_root = Path(args.destination) if args.backend == "hdporncomics" else partial
    baseline_images, baseline_size = _tree_stats(output_root)
    images, size = baseline_images, baseline_size
    site, title = _identity(output_root)
    if args.backend == "manga18fx":
        site = "M18"
    samples: deque[tuple[float, int, int]] = deque([(started, size, images)], maxlen=30)
    tail: deque[str] = deque(maxlen=100)
    backend_progress: dict[str, Any] = {}
    backend_progress_lock = threading.Lock()
    _emit(args, "worker_ready", state="running", destination=str(output_root), backend=args.backend)
    try:
        command = _command(args, partial)
    except RuntimeError as exc:
        _emit(args, "job_terminal_failure", state="failed_backend", category="backend", message=str(exc))
        return 2
    with Path(args.raw_log).open("a", encoding="utf-8", errors="replace") as raw:
        raw.write(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] worker={args.worker} attempt={args.attempt_id} url={args.url}\n"
        )
        raw.write("command=" + " ".join(command[:-1]) + " <url>\n")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )

        def capture() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                raw.write(line)
                raw.flush()
                text = line.rstrip()
                tail.append(text)
                if args.backend != "manga18fx":
                    continue
                parsed = _parse_manga18fx_output(text)
                if parsed is None:
                    continue
                with backend_progress_lock:
                    backend_progress.update(parsed)
                    if parsed["kind"] == "chapter":
                        backend_progress["message"] = (
                            f"chapter {parsed['chapter_index']}/{parsed['chapters_total']}: "
                            f"{parsed['chapter_title']} ({parsed['chapter_images']} images)"
                        )
                    elif parsed["kind"] == "progress":
                        backend_progress["message"] = (
                            f"chapter {parsed['chapter_index']}/{parsed['chapters_total']} complete | "
                            f"{parsed['processed']} processed: {parsed['downloaded']} downloaded, "
                            f"{parsed['skipped']} existing"
                        )
                    elif parsed["kind"] == "complete":
                        backend_progress["message"] = (
                            f"complete: {parsed['downloaded']} downloaded, {parsed['skipped']} already present"
                        )

        thread = threading.Thread(target=capture, daemon=True)
        thread.start()
        last_emit = 0.0
        last_stats = started
        while process.poll() is None:
            now = time.monotonic()
            with backend_progress_lock:
                progress = dict(backend_progress)
            reported_images = int(progress.get("processed", images))
            if now - last_stats >= STATS_INTERVAL:
                images, size = _tree_stats(output_root)
                if not title:
                    discovered_site, discovered_title = _identity(output_root)
                    if discovered_site:
                        site = discovered_site
                    title = discovered_title
                with backend_progress_lock:
                    progress = dict(backend_progress)
                reported_images = int(progress.get("processed", images))
                samples.append((now, size, reported_images))
                while len(samples) > 2 and now - samples[0][0] > 5.0:
                    samples.popleft()
                last_stats = now
            old_t, old_size, old_images = samples[0]
            delta = max(now - old_t, 0.001)
            elapsed = max(now - started, 0.001)
            reported_total = progress.get("images_total") if progress.get("kind") == "complete" else None
            message = str(progress.get("message") or (tail[-1] if tail else f"starting {args.backend}"))
            if now - last_emit >= HEARTBEAT_INTERVAL:
                _emit(
                    args,
                    "heartbeat",
                    state="running",
                    images_done=reported_images,
                    images_total=reported_total,
                    bytes_done=size,
                    current_bps=max(0.0, (size - old_size) / delta),
                    average_bps=max(0.0, (size - baseline_size) / elapsed),
                    current_ips=max(0.0, (reported_images - old_images) / delta),
                    average_ips=max(0.0, (reported_images - baseline_images) / elapsed),
                    site=site,
                    title=title,
                    elapsed=elapsed,
                    message=message,
                )
                last_emit = now
            time.sleep(0.1)
        thread.join(timeout=5)
        returncode = process.returncode or 0
    images, size = _tree_stats(output_root)
    with backend_progress_lock:
        final_progress = dict(backend_progress)

    if returncode == 0:
        manga18fx_downloaded = int(final_progress.get("downloaded", 0))
        manga18fx_skipped = int(final_progress.get("skipped", 0))
        manga18fx_total = manga18fx_downloaded + manga18fx_skipped

        manga18fx_state = "succeeded"
        manga18fx_message = ""
        if args.backend == "manga18fx":
            try:
                manga18fx_state, manga18fx_total, manga18fx_message = _manga18fx_completion(
                    manga18fx_downloaded,
                    manga18fx_skipped,
                )
            except ValueError as exc:
                _emit(
                    args,
                    "job_terminal_failure",
                    state="failed_backend",
                    category="backend",
                    message=str(exc),
                    images_done=0,
                    images_total=0,
                    bytes_done=size,
                    elapsed=time.monotonic() - started,
                )
                return 1

        if args.backend != "hdporncomics":
            _merge_partial(partial, Path(args.destination))

        gallery_skipped = (
            args.backend != "manga18fx"
            and images == baseline_images
            and size == baseline_size
            and any("archive" in line.lower() for line in tail)
        )
        incomplete = args.backend == "hdporncomics" and images == 0

        final_images = manga18fx_total if args.backend == "manga18fx" else images
        message = manga18fx_message
        if incomplete:
            message = "hdporncomics exited successfully but no chapter images were found"

        _emit(
            args,
            "job_complete",
            state=(
                "succeeded_incomplete"
                if incomplete
                else manga18fx_state
                if args.backend == "manga18fx"
                else "skipped_archive"
                if gallery_skipped
                else "succeeded"
            ),
            images_done=final_images,
            images_total=final_images,
            bytes_done=size,
            bytes_total=size,
            elapsed=time.monotonic() - started,
            message=message,
        )
        return 0

    output = "\n".join(tail)
    category, retryable = _classify(returncode, output)
    hint = patch_recovery_hint(output) if args.backend == "hdporncomics" else None
    state = "failed_" + ("rate_limit" if category == "rate_limit" else category)
    _emit(
        args,
        "job_retryable_failure" if retryable else "job_terminal_failure",
        state=state,
        category=category,
        message=hint or tail[-1] if tail else f"backend exited {returncode}",
        returncode=returncode,
        images_done=images,
        bytes_done=size,
    )
    return returncode or 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mangadl worker", description="Internal mangadl worker process.")
    parser.add_argument("-R", "--run-id", required=True)
    parser.add_argument("-J", "--job-id", required=True, type=int)
    parser.add_argument("-A", "--attempt-id", required=True)
    parser.add_argument("-W", "--worker", required=True, type=int)
    parser.add_argument("-u", "--url", required=True)
    parser.add_argument("-b", "--backend", required=True)
    parser.add_argument("-d", "--destination", required=True)
    parser.add_argument("-a", "--archive", required=True)
    parser.add_argument("-P", "--partial-dir", required=True)
    parser.add_argument("-L", "--raw-log", required=True)
    parser.add_argument("-g", "--gallery-config")
    parser.add_argument("-c", "--cookies")
    parser.add_argument("-B", "--cookies-browser")
    parser.add_argument("-U", "--gallery-user-agent")
    parser.add_argument("-x", "--rate")
    parser.add_argument("-e", "--hdporncomics-executable")
    parser.add_argument("-H", "--hdporncomics-threads", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
