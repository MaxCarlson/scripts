"""Bounded source-owned previews; only the coordinator publishes the manifest."""

from __future__ import annotations

from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
import tempfile
import threading
import time
import sys

from PIL import Image
from termdash.live import LiveBlock
from termdash.utils import fmt_hms, format_bytes_decimal

from .cancellation import cancellation_scope, check_cancelled
from .engine import CompressionEngine, ESTIMATED_BYTES_PER_PIXEL, MEMORY_BUDGET_BYTES
from .inventory_pipeline import FileObservation
from .models import CompressionStrategy
from .scheduler import MemoryScheduler
from .timing import execution_role
from .transactions import digest as file_digest


@dataclass(frozen=True)
class PreviewEvent:
    index: int
    sequence: int
    payload: str
    interrupted: bool = False


def _publish_file(destination: Path, writer) -> str:
    """Verify a private temporary, then publish exclusively without overwriting."""
    descriptor, name = tempfile.mkstemp(prefix=".preview-", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            checksum = writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        check_cancelled()
        if file_digest(temporary) != checksum:
            raise OSError("Preview output checksum mismatch")
        check_cancelled()
        os.link(temporary, destination)
        return checksum
    finally:
        temporary.unlink(missing_ok=True)


def _write(stream, payload) -> None:
    check_cancelled()
    if stream.write(payload) != len(payload):
        raise OSError("Short write while creating preview")


def _source_preview(index, template, meta, folder, run, args, engine, events, cancelled):
    row = json.loads(template)
    sequence = 0
    interrupted = False

    def emit():
        nonlocal sequence
        sequence += 1
        event = PreviewEvent(index, sequence, json.dumps(row))
        while not cancelled.is_set():
            try:
                events.put(event, timeout=0.1)
                break
            except Full:
                continue
        return event

    with cancellation_scope(cancelled), execution_role("worker"):
        try:
            check_cancelled()
            row["status"] = "running"
            emit()
            folder.mkdir()
            observation = FileObservation(meta.path, meta.path.parent, meta.path.lstat())
            observation.validate()
            before = observation.info
            if before.st_size != meta.size_bytes or (meta.mtime_ns and before.st_mtime_ns != meta.mtime_ns):
                raise ValueError("Source changed since inventory; rescan before preview")
            original = folder / ("original" + meta.path.suffix.lower())

            def copy_original(stream):
                checksum = hashlib.sha256()
                with meta.path.open("rb") as source:
                    remaining = before.st_size
                    while remaining:
                        check_cancelled()
                        chunk = source.read(min(remaining, 1024**2))
                        if not chunk:
                            raise ValueError("Source shrank while copying preview original")
                        _write(stream, chunk)
                        checksum.update(chunk)
                        remaining -= len(chunk)
                    if source.read(1):
                        raise ValueError("Source grew while copying preview original")
                observation.validate()
                return checksum.hexdigest()

            checksum = _publish_file(original, copy_original)
            row.update(
                original=original.relative_to(run).as_posix(), original_bytes=before.st_size, original_sha256=checksum
            )
            emit()
            with Image.open(original) as image:
                if image.size != (meta.width, meta.height) or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Changed dimensions or unsupported animation")
                if image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
                    raise ValueError("Unsupported pixel/color mode")
                image.load()
                for variant in row["variants"]:
                    check_cancelled()
                    observation.validate()
                    variant["status"] = "running"
                    emit()
                    try:
                        strategy = CompressionStrategy(
                            variant["name"],
                            format=args.format,
                            mode=variant["mode"],
                            quality=variant["quality"] or 100,
                            method=args.effort,
                            encoder=args.algorithm,
                        )
                        if args.format == "auto":
                            fmt, payload, score, encoder = engine._encode_auto(image, meta, strategy)
                        else:
                            fmt = args.format
                            payload, score, encoder = engine._encode_verified(image, fmt, strategy)
                        destination = folder / f"{variant['name']}.{'jpg' if fmt == 'jpeg' else fmt}"

                        def write_candidate(stream):
                            _write(stream, payload)
                            return hashlib.sha256(payload).hexdigest()

                        _publish_file(destination, write_candidate)
                        variant.update(
                            status="complete",
                            file=destination.relative_to(run).as_posix(),
                            bytes=len(payload),
                            format=fmt,
                            encoder=encoder,
                            ssim=score,
                            savings_percent=100 * (before.st_size - len(payload)) / max(1, before.st_size),
                        )
                    except (ValueError, RuntimeError, OSError) as exc:
                        variant.update(status="failed", error=str(exc))
                    emit()
            observation.validate()
            row["status"] = "complete" if all(item["status"] == "complete" for item in row["variants"]) else "failed"
        except (KeyboardInterrupt, CancelledError):
            interrupted = True
            cancelled.set()
            row["status"] = "cancelled"
        except Exception as exc:
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            for variant in row["variants"]:
                if variant["status"] in ("pending", "running"):
                    variant.update(
                        status="cancelled" if row["status"] == "cancelled" else "failed",
                        error=row.get("error", "Preview interrupted"),
                    )
    sequence += 1
    return PreviewEvent(index, sequence, json.dumps(row), interrupted)


def run_preview_pipeline(args, selected, run, report, save_manifest):
    manifest = run / "manifest.json"
    engine = CompressionEngine(
        memory_budget_bytes=args.memory_budget_mib * 1024**2, memory_policy=getattr(args, "_memory_policy", None)
    )
    jobs = []
    for index, meta in enumerate(selected):
        # Include encoded metadata/retained payloads as well as decoded/metric
        # workspace and the bounded source-copy/checksum buffers.
        cost = meta.width * meta.height * ESTIMATED_BYTES_PER_PIXEL + 3 * meta.size_bytes + 2 * 1024**2
        if (
            meta.width <= 0
            or meta.height <= 0
            or meta.width * meta.height > 40_000_000
            or cost > min(MEMORY_BUDGET_BYTES, engine.memory_budget_bytes)
        ):
            report["images"][index].update(
                status="failed", error="Preview source exceeds configured image/memory safety limits"
            )
            for variant in report["images"][index]["variants"]:
                variant.update(status="failed", error="Source exceeds safety limits")
        else:
            jobs.append((index, cost))
    workers = min(
        args.threads,
        os.cpu_count() or 4,
        len(jobs),
        engine.memory_budget_bytes // min((cost for _, cost in jobs), default=engine.memory_budget_bytes),
    )
    scheduler = MemoryScheduler(jobs, engine.memory_budget_bytes, workers)
    events = Queue(maxsize=max(1, 2 * workers))
    cancelled = threading.Event()
    versions = [-1] * len(selected)
    diagnostics = {
        "requested_workers": args.threads,
        "effective_workers": workers,
        "peak_active_workers": 0,
        "event_queue_limit": events.maxsize,
        "peak_pending_futures": 0,
        "waiting_reason": "",
        "memory_policy": (
            engine.memory_policy.diagnostics()
            if engine.memory_policy
            else {"requested": "fixed", "resolved_mib": args.memory_budget_mib}
        ),
    }
    report["worker_diagnostics"] = diagnostics
    futures = {}
    failure = None
    started = time.monotonic()
    last_plain = 0.0
    display = ("Preview starting", "", "")
    live = LiveBlock(stream=sys.stderr, enabled=not args.json and not getattr(args, "no_ui", False))

    def apply(event, *, publish=True):
        if event.sequence <= versions[event.index]:
            return
        versions[event.index] = event.sequence
        report["images"][event.index] = json.loads(event.payload)
        active = sum(row["status"] == "running" for row in report["images"])
        diagnostics["peak_active_workers"] = max(diagnostics["peak_active_workers"], active)
        diagnostics.update(active_workers=active, reserved_bytes=scheduler.reserved_bytes)
        if publish:
            save_manifest(manifest, report)

    def collect(*, publish=True):
        while True:
            try:
                apply(events.get_nowait(), publish=publish)
            except Empty:
                break
        for future in list(futures):
            if future.done():
                index, cost = futures.pop(future)
                scheduler.release(cost)
                event = future.result()
                apply(event, publish=publish)
                if event.interrupted and publish:
                    raise KeyboardInterrupt

    pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="compression-preview")
    try:
        save_manifest(manifest, report)
        while scheduler.pending or futures:
            if cancelled.is_set():
                raise KeyboardInterrupt
            while len(futures) < workers:
                allowance = (
                    engine.memory_policy.admission_allowance() if engine.memory_policy and scheduler.pending else None
                )
                job = scheduler.next_job(available_limit=allowance)
                if job is None:
                    diagnostics["waiting_reason"] = (
                        "system memory pressure"
                        if allowance is not None and scheduler.pending and scheduler.pending[0][1] > allowance
                        else "memory reservations" if scheduler.pending else ""
                    )
                    break
                diagnostics["waiting_reason"] = ""
                index, cost = job
                futures[
                    pool.submit(
                        copy_context().run,
                        _source_preview,
                        index,
                        json.dumps(report["images"][index]),
                        selected[index],
                        run / f"{index + 1:04d}",
                        run,
                        args,
                        engine,
                        events,
                        cancelled,
                    )
                ] = (index, cost)
                diagnostics["peak_pending_futures"] = max(diagnostics["peak_pending_futures"], len(futures))
            try:
                apply(events.get(timeout=0.1))
            except Empty:
                pass
            collect()
            if live.enabled:
                done = sum(row["status"] in ("complete", "failed") for row in report["images"])
                active_row = next((row for row in report["images"] if row["status"] == "running"), None)
                label = (
                    f"{Path(active_row['source']).name}: "
                    + next(
                        (item["name"] for item in active_row["variants"] if item["status"] == "running"),
                        "copying/verifying",
                    )
                    if active_row
                    else "Waiting for source owner"
                )
                display = (
                    f"Preview: {done}/{len(selected)} sources | active {diagnostics.get('active_workers', 0)}/{workers}",
                    label,
                    f"Reserved {format_bytes_decimal(scheduler.reserved_bytes)} / {format_bytes_decimal(engine.memory_budget_bytes)} | Waiting: {diagnostics['waiting_reason'] or 'none'}",
                )
                if live.interactive:
                    live.update(lambda: [*display, f"Elapsed: {fmt_hms(time.monotonic() - started)}"])
                elif time.monotonic() - last_plain >= 5:
                    print(display[0] + " | " + display[2], file=sys.stderr, flush=True)
                    last_plain = time.monotonic()
        report["status"] = (
            "completed_with_errors" if any(row["status"] != "complete" for row in report["images"]) else "complete"
        )
    except BaseException as exc:
        failure = exc
        cancelled.set()
        report["status"] = "cancelled" if isinstance(exc, (KeyboardInterrupt, CancelledError)) else "failed"
    finally:
        if failure is not None:
            cancelled.set()
        while futures:
            try:
                collect(publish=False)
                cancelled.wait(0.05) if not cancelled.is_set() else threading.Event().wait(0.05)
            except KeyboardInterrupt:
                cancelled.set()
            except BaseException as exc:
                failure = failure or exc
                cancelled.set()
        pool.shutdown(wait=True, cancel_futures=True)
        live.close()
        for row in report["images"]:
            if row["status"] in ("pending", "running"):
                row["status"] = "cancelled" if cancelled.is_set() else "failed"
                for variant in row["variants"]:
                    if variant["status"] in ("pending", "running"):
                        variant["status"] = row["status"]
        diagnostics.update(peak_reserved_bytes=scheduler.peak_reserved_bytes, reserved_bytes=0, active_workers=0)
        try:
            save_manifest(manifest, report)
        finally:
            engine.cache.close()
    if failure is not None:
        raise failure
    return 1 if report["status"] != "complete" else 0
