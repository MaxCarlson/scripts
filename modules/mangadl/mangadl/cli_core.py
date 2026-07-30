from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__
from .archive_ui import ArchiveBrowser, filter_records, load_archive
from .backends import backend_classification, choose_backend
from .cli_structure import add_run_arguments, normalize_command_shape
from .concurrency import HARD_MAX_OUTER_WORKERS, MAX_OUTER_WORKERS_ENV
from .destination_audit import audit_destinations, write_audit_outputs
from .hdporncomics_patch import apply_patch, patch_status
from .input import collect_inputs
from .manager import DownloadManager, RunOptions
from .optimizer import (
    OptimizationDashboard,
    generate_optimization_states,
    run_online_optimization,
)
from .repair import apply_repair, plan_loose_images
from .repair_ui import RepairDashboard
from .state import StateStore

MANGA18FX_IMAGE_WORKERS_ENV = "MANGADL_MANGA18FX_IMAGE_WORKERS"
MAX_IMAGE_WORKERS = 8


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _add_state(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-s",
        "--state-db",
        type=_path,
        default=_path("mangadl-state.sqlite3"),
        help="Manager state database.",
    )
    parser.add_argument("-R", "--run-id", help="Run identifier; defaults to the latest run where applicable.")


def build_parser(argv_hint: list[str] | tuple[str, ...] | None = None) -> argparse.ArgumentParser:
    shape = normalize_command_shape(argv_hint or ())
    parser = argparse.ArgumentParser(
        prog="mangadl",
        description="Concurrent, resumable manga/gallery download manager.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    mode_descriptions = {
        "normal": "Download URL files with concise concurrency controls.",
        "optimize": "Adaptively find a fast Manga18FX worker/image-thread state, then run.",
        "benchmark": "Systematically benchmark bounded Manga18FX concurrency states, then run.",
    }
    run = subparsers.add_parser(
        "run",
        help="Download normally, optimize adaptively, or benchmark a bounded state matrix.",
        description=mode_descriptions[shape.run_mode],
    )
    add_run_arguments(
        run,
        mode=shape.run_mode,
        advanced=shape.advanced_config,
        path_type=_path,
    )

    inspect = subparsers.add_parser("inspect", help="Inspect URL routing or persisted jobs.")
    inspect.add_argument("-u", "--url", action="append", default=[], help="URL to probe; repeatable.")
    inspect.add_argument(
        "-b",
        "--backend",
        choices=("auto", "gallery-dl", "native-nhentai", "hdporncomics", "manga18fx"),
        default="auto",
    )
    _add_state(inspect)
    inspect.add_argument("-j", "--json", action="store_true", help="Emit JSON.")

    status = subparsers.add_parser("status", help="Show the latest or selected persisted run.")
    _add_state(status)
    status.add_argument("-j", "--json", action="store_true", help="Emit JSON.")

    retry = subparsers.add_parser("retry", help="Requeue failed jobs in a persisted run.")
    _add_state(retry)
    retry.add_argument("-j", "--job-id", action="append", type=int, default=[], help="Job ID to retry; repeatable.")
    retry.add_argument("-f", "--all-failed", action="store_true", help="Requeue all failed jobs.")

    archive = subparsers.add_parser(
        "archive",
        help="Browse a gallery-dl SQLite archive interactively.",
        description="Open an interactive archive browser; use `archive config` for JSON/export controls.",
    )
    archive.add_argument("-a", "--archive", required=True, type=_path, help="gallery-dl archive path.")
    archive.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit all archive records as JSON." if shape.archive_config else argparse.SUPPRESS,
    )
    archive.add_argument(
        "-N",
        "--no-ui",
        action="store_true",
        help="Print a summary instead of opening the browser." if shape.archive_config else argparse.SUPPRESS,
    )
    archive.add_argument(
        "-f",
        "--filter",
        default="",
        help="Initial case-insensitive record filter." if shape.archive_config else argparse.SUPPRESS,
    )
    archive.add_argument(
        "-e",
        "--export",
        type=_path,
        help="Export the filtered view to JSON." if shape.archive_config else argparse.SUPPRESS,
    )

    patch = subparsers.add_parser("patch-hdporncomics", help="Check or apply the HDPornComics Windows path patch.")
    patch.add_argument("-f", "--apply", action="store_true", help="Apply the known-safe compatibility patch.")

    audit = subparsers.add_parser(
        "audit",
        aliases=("audit-destinations",),
        help="Find URL-list items absent from all destination roots.",
    )
    audit.add_argument("-i", "--input-file", action="append", required=True, help="URL file or glob; repeatable.")
    audit.add_argument(
        "-d",
        "--destination",
        action="append",
        type=_path,
        required=True,
        help="Download root to inspect; repeatable.",
    )
    audit.add_argument(
        "-o",
        "--missing-output",
        type=_path,
        required=True,
        help="Write URLs not found in any destination here.",
    )
    audit.add_argument(
        "-p",
        "--duplicates-output",
        type=_path,
        required=True,
        help="Write duplicate folder locations as JSON here.",
    )
    audit.add_argument("-j", "--json", action="store_true", help="Emit the audit summary as JSON.")
    audit.add_argument("-q", "--quiet", action="store_true", help="Suppress progress messages on stderr.")

    repair = subparsers.add_parser("repair-loose", help="Rebuild per-gallery folders from loose nhentai images.")
    repair.add_argument("-d", "--destination", required=True, type=_path, help="Directory containing loose images.")
    repair_mode = repair.add_mutually_exclusive_group()
    repair_mode.add_argument("-n", "--dry-run", action="store_true", help="Validate and preview only (default).")
    repair_mode.add_argument("-f", "--apply", action="store_true", help="Move files after complete validation.")
    repair.add_argument("-N", "--no-ui", action="store_true", help="Disable the in-place progress dashboard.")
    repair.add_argument("-j", "--json", action="store_true", help="Emit JSON repair details.")
    return parser


def _inclusive_range(value: str) -> tuple[int, int]:
    parts = value.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"expected MIN:MAX, got {value!r}")
    try:
        minimum, maximum = (int(part.strip()) for part in parts)
    except ValueError as exc:
        raise ValueError(f"expected integer MIN:MAX, got {value!r}") from exc
    if minimum < 1 or maximum < minimum:
        raise ValueError(f"invalid inclusive range {value!r}; require 1 <= MIN <= MAX")
    return minimum, maximum


def _normalize_legacy_autotune(args: argparse.Namespace) -> None:
    if not getattr(args, "auto_tune", False):
        return
    args.run_mode = "benchmark"
    args.evaluation = "timed"
    args.trial_seconds = args.tune_seconds
    args.trials = args.tune_rounds
    args.optimization_report = args.tune_report
    args.report_only = False
    args.seed = None
    args.min_workers = 1
    args.min_image_workers = 1
    args.max_image_workers = MAX_IMAGE_WORKERS
    if args.tune_workers:
        args.min_workers, args.max_workers = _inclusive_range(args.tune_workers)
    if args.tune_image_workers:
        args.min_image_workers, args.max_image_workers = _inclusive_range(args.tune_image_workers)


def _optimization_preview(args: argparse.Namespace, manga18fx_urls: list[str]) -> dict[str, Any]:
    logical = max(1, int(os.cpu_count() or 1))
    states = generate_optimization_states(
        args.min_workers,
        args.max_workers,
        args.min_image_workers,
        args.max_image_workers,
        logical_cpus=logical,
        available_series=len(manga18fx_urls),
    )
    trials = args.trials if args.run_mode == "optimize" else len(states) * args.trials
    return {
        "mode": args.run_mode,
        "evaluation": args.evaluation,
        "worker_bounds": {"minimum": args.min_workers, "maximum": args.max_workers},
        "image_worker_bounds": {
            "minimum": args.min_image_workers,
            "maximum": args.max_image_workers,
        },
        "state_count": len(states),
        "planned_trials": trials,
        "trial_seconds": args.trial_seconds,
        "logical_cpus": logical,
        "budget": max(1, logical - 1),
    }


def _validate_run(args: argparse.Namespace) -> None:
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    if not 1 <= args.max_workers <= HARD_MAX_OUTER_WORKERS:
        raise ValueError(f"--max-workers must be between 1 and {HARD_MAX_OUTER_WORKERS}")
    if args.worker_start_delay < 0:
        raise ValueError("--worker-start-delay must be zero or greater")
    if not 1 <= args.image_workers <= MAX_IMAGE_WORKERS:
        raise ValueError(f"--image-workers must be between 1 and {MAX_IMAGE_WORKERS}")
    if args.hdporncomics_threads < 1:
        raise ValueError("--hdporncomics-threads must be at least 1")
    if not args.input_file and not args.url:
        raise ValueError("provide at least one --input-file or --url")

    if args.run_mode in {"optimize", "benchmark"}:
        if args.min_workers < 1 or args.min_workers > args.max_workers:
            raise ValueError("require 1 <= --min-workers <= --max-workers")
        if args.min_image_workers < 1 or args.min_image_workers > args.max_image_workers:
            raise ValueError("require 1 <= --min-image-workers <= --max-image-workers")
        if args.max_image_workers > MAX_IMAGE_WORKERS:
            raise ValueError(f"--max-image-workers must not exceed {MAX_IMAGE_WORKERS}")
        if args.trials < 1:
            raise ValueError("--trials must be at least 1")
        if args.evaluation == "timed" and args.trial_seconds <= 0:
            raise ValueError("--trial-seconds must be greater than zero for timed evaluation")


def _run(args: argparse.Namespace) -> int:
    _normalize_legacy_autotune(args)
    _validate_run(args)

    inputs, rejected = collect_inputs(args.input_file, args.url)
    routes: dict[str, str] = {}
    unsupported: list[dict[str, Any]] = []
    for item in inputs:
        try:
            routes[item.canonical_url] = choose_backend(item.canonical_url, args.backend)
        except ValueError as exc:
            unsupported.append({"url": item.url, "reason": str(exc)})
    inputs = [item for item in inputs if item.canonical_url in routes]
    manga18fx_urls = [item.canonical_url for item in inputs if routes[item.canonical_url] == "manga18fx"]

    preview: dict[str, Any] = {
        "accepted": len(inputs),
        "rejected": rejected,
        "unsupported": unsupported,
        "routes": routes,
        "mode": args.run_mode,
        "requested_workers": args.workers,
        "image_workers": args.image_workers,
        "max_workers": args.max_workers,
        "worker_start_delay": args.worker_start_delay,
    }
    if args.run_mode in {"optimize", "benchmark"}:
        preview["optimization"] = _optimization_preview(args, manga18fx_urls)
    if args.dry_run:
        print(json.dumps(preview, indent=2, sort_keys=True))
        return 1 if unsupported else 0
    if not inputs:
        print(json.dumps(preview, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    optimization_result = None
    if args.run_mode in {"optimize", "benchmark"}:
        if not manga18fx_urls:
            raise ValueError(f"run {args.run_mode} requires at least one routed Manga18FX series URL")
        logical = max(1, int(os.cpu_count() or 1))
        states = generate_optimization_states(
            args.min_workers,
            args.max_workers,
            args.min_image_workers,
            args.max_image_workers,
            logical_cpus=logical,
            available_series=len(manga18fx_urls),
        )
        if not states:
            raise ValueError("optimization bounds produced no valid states")
        planned_trials = args.trials if args.run_mode == "optimize" else len(states) * args.trials
        report_path = args.optimization_report or (
            args.log_dir / f"{args.run_mode}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        )
        dashboard = OptimizationDashboard(enabled=not args.no_ui and not args.quiet)
        optimization_result = run_online_optimization(
            manga18fx_urls,
            args.destination,
            report_path,
            minimum_workers=args.min_workers,
            maximum_workers=args.max_workers,
            minimum_image_workers=args.min_image_workers,
            maximum_image_workers=args.max_image_workers,
            evaluation=args.evaluation,
            strategy="adaptive" if args.run_mode == "optimize" else "grid",
            planned_trials=planned_trials,
            trial_seconds=args.trial_seconds,
            cookies=args.cookies,
            worker_start_delay=args.worker_start_delay,
            logical_cpus=logical,
            seed=args.seed,
            progress=dashboard.update,
            stop_requested=dashboard.request_stop,
        )
        args.workers = optimization_result.selected_workers
        args.image_workers = optimization_result.selected_image_workers
        if dashboard.enabled:
            print()
        summary = {
            "report": str(optimization_result.report_path),
            "selected_workers": args.workers,
            "selected_image_workers": args.image_workers,
            "state_count": len(optimization_result.states),
            "trial_count": len(optimization_result.trials),
            "elapsed": optimization_result.elapsed,
        }
        if args.report_only:
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0

    os.environ[MANGA18FX_IMAGE_WORKERS_ENV] = str(args.image_workers)
    os.environ[MAX_OUTER_WORKERS_ENV] = str(args.max_workers)
    store = StateStore(args.state_db)
    try:
        config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
        run_id = store.create_run(config)
        store.add_jobs(run_id, inputs, routes)
        if optimization_result is not None:
            run_log = args.log_dir / run_id
            run_log.mkdir(parents=True, exist_ok=True)
            (run_log / "optimization-selection.json").write_text(
                json.dumps(
                    {
                        "report": str(optimization_result.report_path),
                        "selected_workers": optimization_result.selected_workers,
                        "selected_image_workers": optimization_result.selected_image_workers,
                        "logical_cpus": optimization_result.logical_cpus,
                        "budget": optimization_result.budget,
                        "elapsed": optimization_result.elapsed,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        options = RunOptions(
            run_id=run_id,
            destination=args.destination,
            archive=args.archive,
            state_db=args.state_db,
            log_dir=args.log_dir,
            workers=args.workers,
            retries=args.retries,
            retry_wait=args.retry_wait,
            gallery_config=args.gallery_config,
            cookies=args.cookies,
            cookies_browser=args.cookies_browser,
            rate=args.max_rate,
            hdporncomics_executable=args.hdporncomics_executable,
            hdporncomics_threads=args.hdporncomics_threads,
            worker_start_delay=args.worker_start_delay,
            ui=not args.no_ui and not args.quiet,
        )
        return DownloadManager(options, store).run()
    finally:
        store.close()


def _run_id(store: StateStore, requested: str | None) -> str:
    run_id = requested or store.latest_run()
    if not run_id:
        raise ValueError("state database contains no runs")
    return run_id


def _show_state(args: argparse.Namespace) -> int:
    store = StateStore(args.state_db)
    try:
        run_id = _run_id(store, args.run_id)
        payload = {"run_id": run_id, "counts": store.counts(run_id), "jobs": store.jobs(run_id)}
    finally:
        store.close()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Run {run_id}: " + ", ".join(f"{key}={value}" for key, value in sorted(payload["counts"].items())))
        for job in payload["jobs"]:
            print(f"{job['id']:4} {job['state']:24} {job['backend']:16} {job['canonical_url']}")
    return 0


def _inspect(args: argparse.Namespace) -> int:
    if not args.url:
        return _show_state(args)
    payload = []
    for url in args.url:
        try:
            backend = choose_backend(url, args.backend)
            payload.append(
                {
                    "url": url,
                    "backend": backend,
                    "classification": backend_classification(url, backend),
                    "supported": True,
                }
            )
        except ValueError as exc:
            payload.append({"url": url, "supported": False, "reason": str(exc)})
    print(
        json.dumps(payload, indent=2, sort_keys=True)
        if args.json
        else "\n".join(f"{row['url']}: {row.get('backend', row.get('reason'))}" for row in payload)
    )
    return 0 if all(row["supported"] for row in payload) else 1


def _retry(args: argparse.Namespace) -> int:
    store = StateStore(args.state_db)
    try:
        run_id = _run_id(store, args.run_id)
        if not args.job_id and not args.all_failed:
            raise ValueError("provide --job-id or --all-failed")
        params: list[Any] = [run_id]
        where = "run_id=? AND state LIKE 'failed_%'"
        if args.job_id:
            where += " AND id IN (" + ",".join("?" for _ in args.job_id) + ")"
            params.extend(args.job_id)
        cursor = store.connection.execute(
            f"UPDATE jobs SET state='queued',next_attempt=0,error_category=NULL,error_message=NULL WHERE {where}",
            params,
        )
        print(f"Requeued {cursor.rowcount} job(s) in {run_id}")
        return 0
    finally:
        store.close()


def _archive(args: argparse.Namespace) -> int:
    snapshot = load_archive(args.archive)
    records = filter_records(snapshot.records, args.filter)
    browser = ArchiveBrowser(snapshot)
    browser.set_filter(args.filter)
    if args.export:
        browser.export(args.export)
    if args.json:
        payload = {
            "path": str(snapshot.path),
            "tables": list(snapshot.tables),
            "columns": list(snapshot.columns),
            "filter": args.filter,
            "records": [{"rowid": record.rowid, **record.values} for record in records],
        }
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0
    if args.no_ui:
        print(f"{snapshot.path}: {len(records)}/{len(snapshot.records)} archive records")
        return 0
    return browser.run()


def _patch_hdporncomics(args: argparse.Namespace) -> int:
    status = apply_patch() if args.apply else patch_status()
    print(status.message)
    return 0 if status.state == "patched" else 1


def _expand_audit_input_files(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        expanded = glob.glob(str(Path(pattern).expanduser()), recursive=False)
        if not expanded:
            raise ValueError(f"input file or glob matched no files: {pattern}")
        for value in expanded:
            path = Path(value).resolve()
            if not path.is_file():
                raise ValueError(f"input path is not a file: {path}")
            if path not in seen:
                seen.add(path)
                files.append(path)
    return files


def _audit_destinations(args: argparse.Namespace) -> int:
    files = _expand_audit_input_files(args.input_file)
    progress = None if args.quiet else lambda message: print(f"Audit: {message}", file=sys.stderr, flush=True)
    if progress:
        progress(f"Loading {len(files)} URL file(s)")
    inputs, rejected = collect_inputs(files, [])
    if progress:
        progress(f"Loaded {len(inputs)} unique URL(s); {len(rejected)} rejected/duplicate line(s)")
    audit = audit_destinations(inputs, args.destination, progress)
    write_audit_outputs(audit, args.missing_output, args.duplicates_output)
    payload = {
        "input_urls": len(inputs),
        "rejected": rejected,
        "resolved": len(audit.resolved),
        "unresolved": len(audit.unresolved),
        "duplicates": len(audit.duplicates),
        "missing_output": str(args.missing_output),
        "duplicates_output": str(args.duplicates_output),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"Audited {payload['input_urls']} URL(s): {payload['resolved']} found, "
            f"{payload['unresolved']} missing, {payload['duplicates']} duplicate folder group(s)."
        )
    if progress:
        progress(f"Wrote missing URLs: {args.missing_output}")
        progress(f"Wrote duplicate folders: {args.duplicates_output}")
    return 0


def _repair_loose(args: argparse.Namespace) -> int:
    mode = "apply" if args.apply else "dry-run"
    dashboard = RepairDashboard(enabled=not args.no_ui and not args.json, mode=mode)
    try:
        plan = plan_loose_images(args.destination, progress=dashboard)
        moved = apply_repair(plan, progress=dashboard) if args.apply else None
    finally:
        dashboard.close()
    payload = {
        "destination": str(args.destination),
        "mode": mode,
        "valid": plan.valid,
        "move_count": len(plan.moves),
        "ignored": plan.ignored,
        "conflicts": list(plan.conflicts),
        "galleries": [
            {
                "id": gallery.gallery_id,
                "folder": str(gallery.folder),
                "expected": gallery.expected,
                "present_after_repair": gallery.present_after_repair,
                "missing_pages": list(gallery.missing_pages),
            }
            for gallery in plan.galleries
        ],
    }
    if moved is not None:
        payload["moved"] = moved
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['mode'].upper()}: {len(plan.moves)} files across {len(plan.galleries)} galleries")
        for gallery in plan.galleries:
            state = "COMPLETE" if not gallery.missing_pages else f"MISSING {len(gallery.missing_pages)}"
            print(f"  nhentai {gallery.gallery_id}: {state} -> {gallery.folder.name}")
        for conflict in plan.conflicts:
            print(f"  CONFLICT: {conflict}")
        if not args.apply and plan.valid and plan.moves:
            print("Validated. Re-run with -f/--apply to move and verify the files.")
    return 0 if plan.valid else 1


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    shape = normalize_command_shape(raw_argv)
    parser = build_parser(raw_argv)
    args = parser.parse_args(list(shape.argv))
    if args.command == "run":
        args.run_mode = shape.run_mode
        args.advanced_config = shape.advanced_config
    try:
        return {
            "run": _run,
            "inspect": _inspect,
            "status": _show_state,
            "retry": _retry,
            "archive": _archive,
            "patch-hdporncomics": _patch_hdporncomics,
            "audit": _audit_destinations,
            "audit-destinations": _audit_destinations,
            "repair-loose": _repair_loose,
        }[args.command](args)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 2
