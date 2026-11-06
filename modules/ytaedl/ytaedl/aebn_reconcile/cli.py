"""Command dispatcher for ``ytaedl reconcile-aebn``."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .deletion import delete_approved
from .archive_sync import sync_verified_archives
from .downloader import download_missing
from .exporter import export_report
from .review import review_candidates
from .scanner import parse_scene_inputs, scan_reconciliation
from .store import ReconciliationStore
from .verifier import verify_replacements


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ytaedl reconcile-aebn",
                                     description="Reconcile historical AEBN full-movie downloads with requested scenes.")
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan", help="Resolve scene URLs and scan configured media roots (read-only).")
    scan.add_argument("-f", "--file", action="append", type=Path, required=True, help="Scene URL file (repeatable).")
    scan.add_argument("-L", "--download-root", action="append", type=Path, required=True, help="Media root to scan (repeatable).")
    scan.add_argument("-a", "--archive-dir", type=Path, help="Read existing archive history without modifying it.")
    scan.add_argument("-p", "--database", type=Path, required=True, help="Persistent reconciliation SQLite database.")
    scan.add_argument("-n", "--dry-run", action="store_true", help="Validate URL files without network or database writes.")
    scan.add_argument("-j", "--json", action="store_true", help="Print machine-readable summary.")
    scan.add_argument("--offline", action="store_true", help="Use cached metadata only; never contact AEBN.")
    scan.add_argument("--refresh-metadata", action="store_true", help="Fetch fresh AEBN metadata instead of using database cache.")

    status = commands.add_parser("status", help="Summarize durable reconciliation state.")
    _add_database(status)
    status.add_argument("-j", "--json", action="store_true")

    download = commands.add_parser("download", help="Preview or download missing replacement scenes.")
    _add_database(download)
    download.add_argument("-x", "--apply", action="store_true", help="Execute the planned scene downloads.")
    download.add_argument("-t", "--threads", type=int, default=1, help="Maximum concurrent scene downloads (1-16).")
    download.add_argument("-n", "--dry-run", action="store_true", help="Preview only; this is the default.")
    download.add_argument("-j", "--json", action="store_true")

    verify = commands.add_parser("verify", help="Probe outputs and validate scene identity and duration.")
    _add_database(verify)
    verify.add_argument("-n", "--dry-run", action="store_true", help="Report recorded output paths without probing or changing status.")
    verify.add_argument("-j", "--json", action="store_true")

    review = commands.add_parser("review", help="Review full movies and record per-file decisions.")
    _add_database(review)
    review.add_argument("-A", "--approve", action="append", default=[], metavar="PATH", help="Approve an exact candidate path.")
    review.add_argument("-D", "--decline", action="append", default=[], metavar="PATH", help="Decline an exact candidate path.")
    review.add_argument("-K", "--defer", action="append", default=[], metavar="PATH", help="Defer an exact candidate path.")
    review.add_argument("-C", "--confirm-identity", action="store_true", help="Confirm identity for the explicitly approved candidates.")
    review.add_argument("-n", "--dry-run", action="store_true", help="Display candidates without prompting or recording decisions.")
    review.add_argument("-j", "--json", action="store_true")

    delete = commands.add_parser("delete", help="Preview or apply explicitly approved original removals.")
    _add_database(delete)
    delete.add_argument("-x", "--apply", action="store_true", help="Execute approved removals after confirmation.")
    delete.add_argument("-C", "--confirm", help="Exact final confirmation: DELETE <eligible-count>.")
    delete.add_argument("-P", "--permanent", action="store_true", help="Permanently delete instead of reversible quarantine.")
    delete.add_argument("-K", "--confirm-permanent", help="Additional confirmation: PERMANENTLY DELETE <eligible-count>.")
    delete.add_argument("-n", "--dry-run", action="store_true", help="Preview only; this is the default.")
    delete.add_argument("-j", "--json", action="store_true")

    archive_sync = commands.add_parser("archive-sync", help="Update verified scene URLs in archives and domain index.")
    _add_database(archive_sync)
    archive_sync.add_argument("-x", "--apply", action="store_true", help="Apply targeted updates under existing locks.")
    archive_sync.add_argument("-n", "--dry-run", action="store_true", help="Preview updates only; this is the default.")
    archive_sync.add_argument("-j", "--json", action="store_true")

    export = commands.add_parser("export", help="Export report data as JSON or CSV.")
    _add_database(export)
    export.add_argument("-f", "--format", choices=("json", "csv"), default="json")
    export.add_argument("-o", "--output", type=Path, help="Write report to this file; default is stdout.")
    export.add_argument("-j", "--json", action="store_true", help="Shortcut for --format json.")
    return parser


def _add_database(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-p", "--database", type=Path, required=True, help="Reconciliation SQLite database.")


def _summary(store: ReconciliationStore) -> dict:
    def count(table: str, where: str = "1=1") -> int:
        return store.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
    return {
        "movies": count("movies"), "scenes": count("requested_scenes"),
        "verified_scenes": count("requested_scenes", "status='scene_verified'"),
        "missing_scenes": count("requested_scenes", "status IN ('scene_missing','scene_invalid','scene_candidate_unverified')"),
        "metadata_errors": count("movies", "metadata_status!='resolved'"),
        "full_movie_candidates": count("media_candidates", "classification='full_movie'"),
        "ambiguous_candidates": count("media_candidates", "classification='unknown'"),
        "approved_candidates": count("media_candidates", "approval='approved'"),
        "pending_jobs": count("download_jobs", "status IN ('pending','failed','interrupted')"),
    }


def _print(data, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    elif isinstance(data, dict):
        for key, value in data.items():
            print(f"{key.replace('_', ' ').title()}: {value}")
    else:
        for item in data:
            print(item)


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.command == "scan":
            parsed = parse_scene_inputs(args.file)
            if args.dry_run:
                result = {"valid_scene_requests": len(parsed.requests), "input_errors": [error.__dict__ for error in parsed.errors]}
                _print(result, args.json)
                return int(bool(parsed.errors))
            def progress(item: dict) -> None:
                stage = item.get("stage")
                if stage == "metadata" and (item["movies_done"] % 10 == 0
                                              or item["movies_done"] == item["movies_total"]):
                    print(f"Resolved metadata for {item['movies_done']}/{item['movies_total']} movies "
                          f"({item['scenes_done']} requested scenes)", file=sys.stderr)
                elif stage == "inventory" and (item.get("complete") or item["media_files_seen"] % 1000 == 0):
                    suffix = " (complete)" if item.get("complete") else ""
                    print(f"Inspected {item['media_files_seen']} media files{suffix}", file=sys.stderr)
            result = scan_reconciliation(files=args.file, download_roots=args.download_root, archive_dir=args.archive_dir,
                                         database_path=args.database, offline=args.offline,
                                         refresh_metadata=args.refresh_metadata, progress_callback=progress)
            _print({"database": str(result.database_path), **result.summary, "errors": result.errors}, args.json)
            return int(bool(result.errors) or bool(result.summary["metadata_errors"]) or bool(result.summary["mapping_errors"]))
        if args.command == "status":
            with ReconciliationStore(args.database) as store:
                _print(_summary(store), args.json)
            return 0
        if args.command == "download":
            result = download_missing(args.database, apply=args.apply, threads=args.threads)
            _print(result, args.json)
            return int(bool(result.get("failed")))
        if args.command == "verify":
            if args.dry_run:
                with ReconciliationStore(args.database) as store:
                    paths = [job["output_path"] for job in store.list_jobs() if job["output_path"]]
                _print({"verification_would_inspect": paths}, args.json)
                return 0
            result = verify_replacements(args.database)
            _print(result, args.json)
            return int(bool(result["failed"]))
        if args.command == "review":
            decisions = {}
            for path in args.approve:
                decisions[str(Path(path).expanduser().resolve())] = "approve"
            for path in args.decline:
                decisions[str(Path(path).expanduser().resolve())] = "decline"
            for path in args.defer:
                decisions[str(Path(path).expanduser().resolve())] = "defer"
            explicit = bool(decisions)
            if args.dry_run:
                with ReconciliationStore(args.database) as store:
                    _print([candidate for candidate in store.list_candidates()
                            if candidate["classification"] in {"full_movie", "unknown"}], args.json)
                return 0
            result = review_candidates(args.database, decisions=decisions if explicit else None,
                                       confirm_identity=args.confirm_identity,
                                       interactive=not explicit and not args.json)
            _print(result, args.json)
            return 0
        if args.command == "delete":
            result = delete_approved(args.database, apply=args.apply, confirm=args.confirm,
                                     permanent=args.permanent, confirm_permanent=args.confirm_permanent)
            _print(result, args.json)
            return int(bool(result.get("skipped")))
        if args.command == "archive-sync":
            result = sync_verified_archives(args.database, apply=args.apply)
            _print(result, args.json)
            return int(bool(result.get("deferred")))
        if args.command == "export":
            export_report(args.database, format="json" if args.json else args.format, output=args.output)
            return 0
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"ytaedl reconcile-aebn: {exc}", file=sys.stderr)
        return 1
    return 2
