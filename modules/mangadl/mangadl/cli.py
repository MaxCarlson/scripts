from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .backends import choose_backend
from .input import collect_inputs
from .manager import DownloadManager, RunOptions
from .repair import apply_repair, plan_loose_images
from .repair_ui import RepairDashboard
from .state import StateStore


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _add_state(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-s", "--state-db", type=_path, default=_path("mangadl-state.sqlite3"), help="Manager state database."
    )
    parser.add_argument("-R", "--run-id", help="Run identifier; defaults to the latest run where applicable.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mangadl", description="Concurrent, resumable manga/gallery download manager."
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Download URLs from files and command-line values.")
    run.add_argument("-i", "--input-file", action="append", type=_path, default=[], help="UTF-8 URL file; repeatable.")
    run.add_argument("-u", "--url", action="append", default=[], help="Direct gallery URL or nhentai ID; repeatable.")
    run.add_argument("-d", "--destination", type=_path, required=True, help="Destination library root.")
    run.add_argument("-a", "--archive", type=_path, required=True, help="gallery-dl SQLite archive path.")
    _add_state(run)
    run.add_argument("-w", "--workers", type=int, default=2, help="Concurrent worker count (default: 2).")
    run.add_argument("-b", "--backend", choices=("auto", "gallery-dl", "native-nhentai"), default="auto")
    run.add_argument("-c", "--config", type=_path, help="Reserved mangadl TOML configuration path.")
    run.add_argument("-g", "--gallery-config", type=_path, help="gallery-dl configuration file.")
    run.add_argument("-l", "--log-dir", type=_path, default=_path("mangadl-logs"), help="Run log root.")
    run.add_argument("-r", "--retries", type=int, default=3, help="Retry count for transient failures.")
    run.add_argument("-t", "--retry-wait", type=float, default=5.0, help="Initial retry delay in seconds.")
    run.add_argument("-x", "--max-rate", help="Per-worker gallery-dl rate limit, for example 2M.")
    run.add_argument("-C", "--cookies", type=_path, help="Netscape/Mozilla cookies file.")
    run.add_argument("-B", "--cookies-browser", help="Reserved browser cookie source for gallery-dl configuration.")
    run.add_argument("-n", "--dry-run", action="store_true", help="Parse, deduplicate, and route without downloading.")
    run.add_argument("-N", "--no-ui", action="store_true", help="Disable the in-place dashboard.")
    run.add_argument("-q", "--quiet", action="store_true", help="Only print the final machine-readable summary.")
    run.add_argument("-v", "--verbose", action="count", default=0, help="Increase manager diagnostics.")
    run.add_argument("-A", "--anonymize-logs", action="store_true", help="Reserve URL-anonymized log output.")

    inspect = subparsers.add_parser("inspect", help="Inspect URL routing or persisted jobs.")
    inspect.add_argument("-u", "--url", action="append", default=[], help="URL to probe; repeatable.")
    inspect.add_argument("-b", "--backend", choices=("auto", "gallery-dl", "native-nhentai"), default="auto")
    _add_state(inspect)
    inspect.add_argument("-j", "--json", action="store_true", help="Emit JSON.")

    status = subparsers.add_parser("status", help="Show the latest or selected persisted run.")
    _add_state(status)
    status.add_argument("-j", "--json", action="store_true", help="Emit JSON.")

    retry = subparsers.add_parser("retry", help="Requeue failed jobs in a persisted run.")
    _add_state(retry)
    retry.add_argument("-j", "--job-id", action="append", type=int, default=[], help="Job ID to retry; repeatable.")
    retry.add_argument("-f", "--all-failed", action="store_true", help="Requeue all failed jobs.")

    archive = subparsers.add_parser("archive", help="Inspect a gallery-dl SQLite archive.")
    archive.add_argument("-a", "--archive", required=True, type=_path, help="gallery-dl archive path.")
    archive.add_argument("-j", "--json", action="store_true", help="Emit JSON.")
    repair = subparsers.add_parser("repair-loose", help="Rebuild per-gallery folders from loose nhentai images.")
    repair.add_argument("-d", "--destination", required=True, type=_path, help="Directory containing loose images.")
    repair_mode = repair.add_mutually_exclusive_group()
    repair_mode.add_argument("-n", "--dry-run", action="store_true", help="Validate and preview only (default).")
    repair_mode.add_argument("-f", "--apply", action="store_true", help="Move files after complete validation.")
    repair.add_argument("-N", "--no-ui", action="store_true", help="Disable the in-place progress dashboard.")
    repair.add_argument("-j", "--json", action="store_true", help="Emit JSON repair details.")
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    if not args.input_file and not args.url:
        raise ValueError("provide at least one --input-file or --url")
    inputs, rejected = collect_inputs(args.input_file, args.url)
    routes: dict[str, str] = {}
    unsupported: list[dict[str, Any]] = []
    for item in inputs:
        try:
            routes[item.canonical_url] = choose_backend(item.canonical_url, args.backend)
        except ValueError as exc:
            unsupported.append({"url": item.url, "reason": str(exc)})
    inputs = [item for item in inputs if item.canonical_url in routes]
    preview = {"accepted": len(inputs), "rejected": rejected, "unsupported": unsupported, "routes": routes}
    if args.dry_run:
        print(json.dumps(preview, indent=2, sort_keys=True))
        return 1 if unsupported else 0
    if not inputs:
        print(json.dumps(preview, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    store = StateStore(args.state_db)
    try:
        config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
        run_id = store.create_run(config, args.run_id)
        store.add_jobs(run_id, inputs, routes)
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
            payload.append({"url": url, "backend": choose_backend(url, args.backend), "supported": True})
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
    if not args.archive.exists():
        raise ValueError(f"archive does not exist: {args.archive}")
    connection = sqlite3.connect(f"file:{args.archive}?mode=ro", uri=True)
    try:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        count = connection.execute("SELECT COUNT(*) FROM archive").fetchone()[0] if "archive" in tables else None
    finally:
        connection.close()
    payload = {"path": str(args.archive), "tables": tables, "archive_records": count}
    print(json.dumps(payload, indent=2, sort_keys=True) if args.json else f"{args.archive}: {count} archive records")
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
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return {
            "run": _run,
            "inspect": _inspect,
            "status": _show_state,
            "retry": _retry,
            "archive": _archive,
            "repair-loose": _repair_loose,
        }[args.command](args)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 2
