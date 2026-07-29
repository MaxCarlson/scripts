from __future__ import annotations

import argparse
import json
import os
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
    if "401" in lowered or "403" in lowered or "authentication" in lowered:
        return "auth", False
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
    samples: deque[tuple[float, int, int]] = deque([(started, size, images)], maxlen=30)
    tail: deque[str] = deque(maxlen=100)
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
                tail.append(line.rstrip())

        thread = threading.Thread(target=capture, daemon=True)
        thread.start()
        last_emit = 0.0
        last_stats = started
        while process.poll() is None:
            now = time.monotonic()
            if now - last_stats >= STATS_INTERVAL:
                images, size = _tree_stats(output_root)
                samples.append((now, size, images))
                while len(samples) > 2 and now - samples[0][0] > 5.0:
                    samples.popleft()
                last_stats = now
            old_t, old_size, old_images = samples[0]
            delta = max(now - old_t, 0.001)
            elapsed = max(now - started, 0.001)
            site, title = _identity(output_root)
            if now - last_emit >= HEARTBEAT_INTERVAL:
                _emit(
                    args,
                    "heartbeat",
                    state="running",
                    images_done=images,
                    bytes_done=size,
                    current_bps=max(0.0, (size - old_size) / delta),
                    average_bps=max(0.0, (size - baseline_size) / elapsed),
                    current_ips=max(0.0, (images - old_images) / delta),
                    average_ips=max(0.0, (images - baseline_images) / elapsed),
                    site=site,
                    title=title,
                    elapsed=elapsed,
                    message=tail[-1] if tail else f"starting {args.backend}",
                )
                last_emit = now
            time.sleep(0.1)
        thread.join(timeout=5)
        returncode = process.returncode or 0
    images, size = _tree_stats(output_root)
    if returncode == 0:
        if args.backend != "hdporncomics":
            _merge_partial(partial, Path(args.destination))
        skipped = (
            images == baseline_images and size == baseline_size and any("archive" in line.lower() for line in tail)
        )
        incomplete = args.backend == "hdporncomics" and images == 0
        _emit(
            args,
            "job_complete",
            state="succeeded_incomplete" if incomplete else "skipped_archive" if skipped else "succeeded",
            images_done=images,
            images_total=images,
            bytes_done=size,
            bytes_total=size,
            elapsed=time.monotonic() - started,
            message="hdporncomics exited successfully but no chapter images were found" if incomplete else "",
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
    parser.add_argument("-x", "--rate")
    parser.add_argument("-e", "--hdporncomics-executable")
    parser.add_argument("-H", "--hdporncomics-threads", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
