from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sqlite3
import sys
import time
import hashlib
import tempfile
from contextlib import nullcontext, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cross_platform import StorageMediaKind, storage_media_for_path
from kavita import KavitaClient, KavitaConfig, PendingAssignmentStore, match_series_by_path, parse_path_maps
from kavita.assignments import reconcile_assignments

from . import __version__
from .archive_ui import ArchiveBrowser, filter_records, load_archive
from .audit_console import AuditProgress, field, styled
from .backends import backend_classification, choose_backend, gallery_dl_scope
from .cli_structure import add_run_arguments, normalize_command_shape
from .concurrency import configured_maximum_workers
from .destination_audit import audit_destinations, audit_library, write_audit_outputs
from .favorites import crawl_favorites, format_result as format_favorites_result
from .favorites import result_payload as favorites_result_payload
from .favorites import write_url_file
from .file_io import replace_file
from .gallery_auth import (
    BROWSERS,
    DEFAULT_AUTH_SITE,
    ProfileStore,
    TargetStore,
    cookie_summary,
    domain_for,
    gallery_sites,
    refresh_profile,
    site_for_url,
)
from .hdporncomics_patch import apply_patch, patch_status
from .input import collect_inputs
from .library_index import backfill_source_indexes, resolve_url_folders, scan_library
from .manager import DownloadManager, RunOptions
from .optimizer import (
    OptimizationDashboard,
    generate_optimization_states,
    run_online_optimization,
)
from .partial_safety import apply_cleanup, cleanup_preview, plan_cleanup
from .repair import resolve_nhentai_metadata
from .partial_reconcile import reconstruct_archive_keys, reconstruct_archive_page_keys, resolve_owner_urls
from .repair_pages import (
    apply_page_repair, apply_page_repairs, clear_page_repair_archive,
    make_page_repair_plan, repair_confirmation_token,
)
from .partial_ui import select_partial_owners
from .page_adapters import resolve_expected_pages
from .scratch import partial_root_for
from .scratch_controls import ScratchControls, archive_cleanup_checkpoint
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

    kavita = subparsers.add_parser("kavita", help="Preview or reconcile pending Kavita collection assignments.")
    kavita_subparsers = kavita.add_subparsers(dest="kavita_command", required=True)
    reconcile = kavita_subparsers.add_parser("reconcile", help="Match pending URLs to scanned Kavita series.")
    reconcile.add_argument("-d", "--destination", type=_path, required=True, help="MangaDL destination root.")
    reconcile.add_argument("-Z", "--kavita-url", required=True, help="Kavita base URL.")
    reconcile.add_argument(
        "-E", "--kavita-api-key-env", default="KAVITA_API_KEY", help="Environment variable containing the Auth Key."
    )
    reconcile.add_argument(
        "-P", "--kavita-path-map", action="append", default=[], metavar="LOCAL=KAVITA", help="Path mapping; repeatable."
    )
    reconcile.add_argument("-f", "--apply", action="store_true", help="Write collection changes; default is preview only.")
    reconcile.add_argument("-j", "--json", action="store_true", help="Emit JSON.")

    def add_kavita_batch_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("-Z", "--kavita-url", required=True, help="Kavita base URL.")
        command.add_argument("-E", "--kavita-api-key-env", default="KAVITA_API_KEY", help="Environment variable containing the Auth Key.")
        command.add_argument("-P", "--kavita-path-map", action="append", default=[], metavar="LOCAL=KAVITA", help="Path mapping; repeatable.")
        command.add_argument("-c", "--collection", action="append", required=True, help="Collection name; repeatable.")
        command.add_argument("-f", "--apply", action="store_true", help="Apply the previewed assignment set.")
        command.add_argument("-j", "--json", action="store_true", help="Emit JSON.")

    assign_file = kavita_subparsers.add_parser("assign-file", help="Assign already-downloaded URL-file manga to collections.")
    assign_file.add_argument("-i", "--input-file", required=True, type=_path, help="Processed URL file.")
    assign_file.add_argument("-d", "--destination", required=True, type=_path, help="MangaDL library root.")
    assign_file.add_argument(
        "-x", "--no-index-backfill", action="store_true",
        help="Do not create missing per-folder source indexes while resolving this URL file.",
    )
    add_kavita_batch_arguments(assign_file)

    assign_name = kavita_subparsers.add_parser("assign-name", help="Assign a uniquely named scanned Kavita series.")
    assign_name.add_argument("-n", "--name", action="append", required=True, help="Exact series name; repeatable.")
    add_kavita_batch_arguments(assign_name)

    assign_pattern = kavita_subparsers.add_parser("assign-pattern", help="Preview a regex-selected set of Kavita series.")
    assign_pattern.add_argument("-p", "--pattern", required=True, help="Bounded Python regex searched against series names.")
    assign_pattern.add_argument("-C", "--confirm-matches", help="Match-set token printed by preview; required with --apply.")
    add_kavita_batch_arguments(assign_pattern)

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
        help="Audit URL-file identities or every manga folder; URL matches backfill missing source indexes.",
    )
    audit.add_argument(
        "-i", "--input-file", "-u", "--url-file", dest="input_file", action="append",
        help="Optional URL file or glob; repeatable (-u/--url-file is an audit-only alias). Omit for folder-only audit.",
    )
    audit.add_argument(
        "-F", "--url-directory", action="append", type=_path,
        help="Add every top-level text file whose name starts with 'url' from this directory; repeatable.",
    )
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
        help="Write URLs not found in any destination here.",
    )
    audit.add_argument(
        "-p",
        "--duplicates-output",
        type=_path,
        help="Write duplicate folder locations as JSON here.",
    )
    audit.add_argument("-j", "--json", action="store_true", help="Emit the audit summary as JSON.")
    audit.add_argument(
        "-r", "--report-output", type=_path,
        help="Report filename base; automatically includes input names and avoids overwrites. "
        "Default: mangadl-<URL-file>-audit-report.json in the first destination root.",
    )
    audit.add_argument("-q", "--quiet", action="store_true", help="Suppress progress messages on stderr.")
    audit.add_argument("-a", "--all-findings", action="store_true", help="Include defect-free unknown/ambiguous entries in console details.")
    audit.add_argument(
        "-x", "--no-index-backfill", action="store_true",
        help="Do not create missing per-folder source indexes; audit reports are still written.",
    )

    repair = subparsers.add_parser("repair-loose", help="Rebuild per-gallery folders from loose nhentai images.")
    repair.add_argument("-d", "--destination", required=True, type=_path, help="Directory containing loose images.")
    repair_mode = repair.add_mutually_exclusive_group()
    repair_mode.add_argument("-n", "--dry-run", action="store_true", help="Validate and preview only (default).")
    repair_mode.add_argument("-f", "--apply", action="store_true", help="Move files after complete validation.")
    repair.add_argument("-N", "--no-ui", action="store_true", help="Disable the in-place progress dashboard.")
    repair.add_argument("-j", "--json", action="store_true", help="Emit JSON repair details.")

    repair_pages = subparsers.add_parser(
        "repair-pages", help="Repair exact missing/corrupt gallery-dl nhentai pages (preview first)."
    )
    repair_pages.add_argument("-u", "--url", required=True, help="One nhentai gallery URL.")
    repair_pages.add_argument("-d", "--destination", required=True, type=_path, help="MangaDL library root.")
    repair_pages.add_argument("-S", "--scratch", type=_path, help="Optional scratch volume for the targeted download.")
    repair_pages.add_argument("-a", "--archive", type=_path, help="gallery-dl archive (default: destination control archive).")
    repair_pages.add_argument("-g", "--gallery-config", type=_path, help="gallery-dl config used for the repair.")
    repair_pages.add_argument("-c", "--cookies", type=_path, help="Cookie file for the gallery request.")
    repair_pages.add_argument("-B", "--cookies-browser", help="Browser cookie source.")
    repair_pages.add_argument("-U", "--user-agent", help="Optional gallery-dl user agent.")
    repair_pages.add_argument("-x", "--rate", help="Optional gallery-dl transfer-rate limit.")
    repair_pages.add_argument("-f", "--apply", action="store_true", help="Apply the reviewed targeted repair.")
    repair_pages.add_argument("-C", "--confirm-plan", help="Preview token required with --apply.")
    repair_pages.add_argument("-j", "--json", action="store_true", help="Emit JSON.")

    batch_repair = subparsers.add_parser(
        "repair", help="Build, preview, or apply a guarded batch repair from an audit report."
    )
    batch_repair.add_argument("-r", "--report", required=True, type=_path, help="Audit report produced by mangadl audit.")
    batch_repair.add_argument(
        "-d", "--destination", type=_path,
        help="Destination for wholly missing galleries; required when the report contains multiple roots.",
    )
    batch_repair.add_argument("-p", "--plan-output", type=_path, help="Optionally save the displayed repair plan as JSON.")
    batch_repair.add_argument("-S", "--scratch", type=_path, help="Optional scratch volume for downloads.")
    batch_repair.add_argument("-a", "--archive", type=_path, help="gallery-dl archive (default: destination control archive).")
    batch_repair.add_argument("-g", "--gallery-config", type=_path, help="gallery-dl config used for downloads.")
    batch_repair.add_argument("-c", "--cookies", type=_path, help="Cookie file for gallery requests.")
    batch_repair.add_argument("-B", "--cookies-browser", help="Browser cookie source.")
    batch_repair.add_argument("-U", "--user-agent", help="Optional gallery-dl user agent.")
    batch_repair.add_argument("-x", "--rate", help="Optional transfer-rate limit.")
    batch_repair.add_argument("-f", "--apply", action="store_true", help="Apply the exact displayed repair plan.")
    batch_repair.add_argument("-C", "--confirm-plan", help="Exact plan token required with --apply.")
    batch_repair.add_argument("-j", "--json", action="store_true", help="Emit the plan/result as JSON.")
    batch_repair.add_argument("-w", "--workers", type=int, default=2, help="Initial normal downloader workers (default: 2).")
    batch_repair.add_argument("-m", "--max-workers", type=int, help="Normal downloader outer-worker ceiling.")
    batch_repair.add_argument("-N", "--no-ui", action="store_true", help="Disable the normal download dashboard.")
    batch_repair.add_argument("-L", "--worker-start-delay", type=float, default=2.0,
                              help="Seconds between worker launches (normal default: 2).")

    partials = subparsers.add_parser("partials", help="Inspect or safely remove resumable partial data.")
    partial_commands = partials.add_subparsers(dest="partials_command", required=True)
    partial_clean = partial_commands.add_parser(
        "clean",
        aliases=("cleanup",),
        help="Remove selected partial data and its recorded gallery-dl archive entries.",
    )
    partial_clean.add_argument("-d", "--destination", required=True, type=_path, help="Destination library root.")
    partial_clean.add_argument(
        "-S", "--scratch", "--scratch-dir", dest="scratch_dir", type=_path,
        help="Scratch directory used for the run; inspect staged partials instead of <destination>/_partial.",
    )
    partial_clean.add_argument(
        "-t",
        "--target",
        action="append",
        default=[],
        help="Path beneath <destination>/_partial to remove; repeatable. Omit to open the UI.",
    )
    partial_clean.add_argument(
        "-a",
        "--archive",
        type=_path,
        help="Require tracked partials to use this exact gallery-dl archive.",
    )
    partial_clean.add_argument("-f", "--apply", action="store_true", help="Apply the cleanup (default: preview only).")
    partial_clean.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the typed DELETE confirmation for interactive apply mode.",
    )
    partial_clean.add_argument(
        "-F",
        "--files-only",
        action="store_true",
        help="Allow legacy cleanup without changing an archive; may leave stale archive entries.",
    )
    partial_clean.add_argument(
        "-B",
        "--no-backup",
        action="store_true",
        help="Do not create a timestamped archive backup before applying tracked cleanup.",
    )
    partial_clean.add_argument("-j", "--json", action="store_true", help="Emit JSON cleanup details.")
    partial_clean.add_argument(
        "-s",
        "--state-db",
        action="append",
        type=_path,
        default=[],
        help="Additional mangadl state database used to recover legacy partial URLs; repeatable.",
    )
    partial_clean.add_argument(
        "-u",
        "--url",
        action="append",
        default=[],
        help="Legacy URL override as URL or PARTIAL_KEY=URL; repeatable.",
    )
    partial_clean.add_argument("-g", "--gallery-config", type=_path, help="gallery-dl config for legacy key recovery.")
    partial_clean.add_argument("-c", "--cookies", type=_path, help="Cookie file for legacy key recovery.")
    partial_clean.add_argument("-b", "--cookies-browser", help="Browser cookie source for legacy key recovery.")
    partial_clean.add_argument("-U", "--user-agent", help="User-Agent for legacy key recovery.")
    partial_clean.add_argument("-A", "--auth-dir", type=_path, help="Managed-auth directory for legacy key recovery.")

    auth = subparsers.add_parser("auth", help="Manage per-domain gallery-dl browser authentication.")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)

    auth_status = auth_commands.add_parser("status", help="Show a managed authentication profile.")
    status_target = auth_status.add_mutually_exclusive_group(required=True)
    status_target.add_argument("-u", "--url", help="Gallery URL whose domain should be inspected.")
    status_target.add_argument("-d", "--domain", help="Domain to inspect.")
    auth_status.add_argument("-A", "--auth-dir", type=_path, help="Managed authentication root.")
    auth_status.add_argument("-j", "--json", action="store_true", help="Emit JSON.")

    auth_refresh = auth_commands.add_parser("refresh", help="Extract browser cookies and validate them.")
    auth_refresh.add_argument(
        "-u", "--url", help="Actual gallery or series URL; validates and replaces the saved site target."
    )
    auth_refresh.add_argument(
        "-s", "--site", help=f"gallery-dl site/module name (default: {DEFAULT_AUTH_SITE})."
    )
    auth_refresh.add_argument(
        "-S", "--select-site", action="store_true", help="Interactively select from installed gallery-dl sites."
    )
    auth_refresh.add_argument(
        "-q", "--site-filter", help="Filter the interactive gallery-dl site list."
    )
    auth_refresh.add_argument(
        "-b", "--browser", choices=BROWSERS, default="chrome", help="Cookie source (default: chrome)."
    )
    auth_refresh.add_argument("-p", "--debug-port", type=int, help="Chrome/Edge DevTools port.")
    auth_refresh.add_argument("-t", "--timeout", type=float, default=180.0, help="Browser verification timeout.")
    auth_refresh.add_argument("-A", "--auth-dir", type=_path, help="Managed authentication root.")
    auth_refresh.add_argument(
        "-c", "--cookie-file", type=_path, help="Write the generated Netscape cookie file here."
    )
    auth_refresh.add_argument(
        "-U", "--user-agent", help="Override the captured User-Agent (useful with Firefox)."
    )
    auth_refresh.add_argument(
        "-n", "--no-launch-browser", action="store_true", help="Require an existing browser debugger."
    )
    auth_refresh.add_argument("-j", "--json", action="store_true", help="Emit JSON.")

    auth_clear = auth_commands.add_parser("clear", help="Remove a managed authentication profile.")
    clear_target = auth_clear.add_mutually_exclusive_group(required=True)
    clear_target.add_argument("-u", "--url", help="Gallery URL whose profile should be removed.")
    clear_target.add_argument("-d", "--domain", help="Domain profile to remove.")
    auth_clear.add_argument("-A", "--auth-dir", type=_path, help="Managed authentication root.")
    auth_clear.add_argument("-j", "--json", action="store_true", help="Emit JSON.")

    auth_sites = auth_commands.add_parser("sites", help="List sites from the installed gallery-dl registry.")
    auth_sites.add_argument("-f", "--filter", default="", help="Case-insensitive site-name filter.")
    auth_sites.add_argument("-k", "--known-only", action="store_true", help="Show only sites with saved targets.")
    auth_sites.add_argument("-A", "--auth-dir", type=_path, help="Managed authentication root.")
    auth_sites.add_argument("-j", "--json", action="store_true", help="Emit JSON.")

    favorites = subparsers.add_parser(
        "favorites",
        help="Extract downloadable gallery URLs from a favorites/listing page.",
        description=(
            "Fetch a favorites or listing page with mangadl's managed cookies, follow explicit "
            "next-page links, and keep only non-collection URLs recognized by mangadl/gallery-dl. "
            "Dry-run is the default; use --apply to write the URL file."
        ),
    )
    favorites.add_argument("-u", "--url", required=True, help="Favorites/listing page URL to scan.")
    favorites.add_argument("-o", "--output", required=True, type=_path, help="Destination UTF-8 URL file.")
    favorites.add_argument("-A", "--auth-dir", type=_path, help="Managed authentication root.")
    favorites.add_argument("-C", "--cookies", type=_path, help="Explicit Netscape cookie file; overrides managed cookies.")
    favorites.add_argument(
        "-B",
        "--cookies-browser",
        help="Load cookies directly from a browser using gallery-dl syntax, e.g. firefox.",
    )
    favorites.add_argument("-U", "--user-agent", help="Override the managed/browser User-Agent.")
    favorites.add_argument("-P", "--max-pages", type=int, default=20, help="Maximum listing pages to fetch (default: 20).")
    favorites.add_argument("-D", "--page-delay", type=float, default=1.0, help="Delay between listing pages in seconds.")
    favorites.add_argument("-t", "--timeout", type=float, default=30.0, help="HTTP timeout per listing page in seconds.")
    favorites.add_argument("-f", "--apply", action="store_true", help="Write/replace the output URL file.")
    favorites.add_argument("-j", "--json", action="store_true", help="Emit JSON.")
    favorites.add_argument("-q", "--quiet", action="store_true", help="Suppress fetch progress on stderr.")

    compress = subparsers.add_parser(
        "compress",
        help="Manage compression inventory, estimates, analysis, previews and recovery.",
        description="Choose an explicit compression operation. Bare `mangadl compress` only prints help.",
    )
    from compresser.arguments import build_operation_parsers

    build_operation_parsers(compress, owner="mangadl")
    lock = subparsers.add_parser(
        "lock",
        help="Inspect or unlock read/write locks and active processes for a target folder.",
        description=(
            "Inspect OS byte-range write locks, shared read locks, repair token locks, "
            "state database running records, and live mangadl/compresser processes for a folder."
        ),
    )
    lock.add_argument(
        "-d",
        "--destination",
        type=_path,
        required=True,
        help="Target library or gallery folder to inspect.",
    )
    lock_action = lock.add_mutually_exclusive_group()
    lock_action.add_argument(
        "-s",
        "--status",
        action="store_true",
        help="Show lock status and auto-clean harmless stale metadata (default).",
    )
    lock_action.add_argument(
        "-u",
        "--unlock",
        action="store_true",
        help="Clear stale repair.lock and stale running state rows if no live process holds a lock.",
    )
    lock.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
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
    if args.worker_start_delay < 0:
        raise ValueError("--worker-start-delay must be zero or greater")
    if not 1 <= args.image_workers <= MAX_IMAGE_WORKERS:
        raise ValueError(f"--image-workers must be between 1 and {MAX_IMAGE_WORKERS}")
    if args.hdporncomics_threads < 1:
        raise ValueError("--hdporncomics-threads must be at least 1")
    if not args.input_file and not args.url:
        raise ValueError("provide at least one --input-file or --url")
    if args.file_range:
        if os.environ.get("MANGADL_REPAIR_TOKEN") is None:
            raise ValueError("--file-range is reserved for the guarded repair workflow")
        if not re.fullmatch(r"\d+(?:,\d+)*", args.file_range):
            raise ValueError("invalid internal file range")
    repair_ranges = getattr(args, "repair_file_ranges", {})
    if repair_ranges and (
        not os.environ.get("MANGADL_REPAIR_TOKEN")
        or any(not re.fullmatch(r"\d+(?:,\d+)*", value) for value in repair_ranges.values())
    ):
        raise ValueError("per-URL file ranges require the guarded repair workflow")

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


def _resolve_run_paths(args: argparse.Namespace) -> None:
    """Fill control paths from the selected destination without shell setup."""
    control_root = args.destination / ".mangadl"
    args.archive = args.archive or control_root / "archive.sqlite3"
    args.state_db = args.state_db or control_root / "state.sqlite3"
    args.log_dir = args.log_dir or control_root / "logs"


def _resolve_storage_policy(args: argparse.Namespace) -> None:
    destination_media = storage_media_for_path(args.destination)
    scratch_media = storage_media_for_path(args.scratch_dir) if args.scratch_dir is not None else None
    fast_storage = (
        destination_media.kind == StorageMediaKind.SOLID_STATE
        or (scratch_media is not None and scratch_media.kind == StorageMediaKind.SOLID_STATE)
    )
    if args.scratch_dir is not None:
        args.storage_media = "scratch"
        args.storage_media_detail = (
            f"destination {destination_media.kind.value}; scratch {scratch_media.kind.value}: "
            f"{scratch_media.detail}; {destination_media.detail}"
        )
    else:
        args.storage_media = destination_media.kind.value
        args.storage_media_detail = destination_media.detail
    args.destination_storage_media = destination_media.kind.value
    args.scratch_storage_media = scratch_media.kind.value if scratch_media is not None else None
    args.fast_storage = fast_storage
    args.max_workers = configured_maximum_workers(
        args.max_workers,
        fast_storage=fast_storage,
        logical_cpus=os.cpu_count(),
    )


def _format_run_preview(preview: dict[str, Any]) -> str:
    routes = preview["routes"]
    route_counts: dict[str, int] = {}
    for backend in routes.values():
        route_counts[backend] = route_counts.get(backend, 0) + 1
    lines = [
        "mangadl dry run — no downloads or control files were created",
        f"Accepted: {preview['accepted']} unique URL(s)",
        f"Rejected: {len(preview['rejected'])} duplicate/invalid line(s)",
        f"Unsupported: {len(preview['unsupported'])} URL(s)",
        f"Destination: {preview['destination']}",
        f"Control directory: {preview['control_directory']}",
        f"Partial staging: {preview['partial_root']}",
        f"Workers: {preview['requested_workers']} (maximum {preview['max_workers']}); "
        f"image workers: {preview['image_workers']}",
        "Routes: " + (", ".join(f"{name}={count}" for name, count in sorted(route_counts.items())) or "none"),
    ]
    if preview.get("destination_partial_owners"):
        lines.append(
            f"Existing destination partial owners: {preview['destination_partial_owners']} "
            "(finish or inspect before enabling scratch)"
        )
    if preview["rejected"]:
        lines.append("Rejected input:")
        lines.extend(
            f"  line {item.get('line', '?')}: {item.get('reason', 'rejected')} — {item.get('value', '')}"
            for item in preview["rejected"]
        )
    if preview["unsupported"]:
        lines.append("Unsupported input:")
        lines.extend(f"  {item['url']} — {item['reason']}" for item in preview["unsupported"])
    return "\n".join(lines)


def _run(args: argparse.Namespace) -> int:
    from .library_guard import library_write_guard

    _normalize_legacy_autotune(args)
    _resolve_run_paths(args)
    _resolve_storage_policy(args)
    _validate_run(args)
    with library_write_guard(args.destination, operation="mangadl run") if not args.dry_run else nullcontext():
        return _run_owned(args)


def _run_owned(args: argparse.Namespace) -> int:
    repair_lock = args.destination / ".mangadl" / "repair.lock"
    if repair_lock.exists() and os.environ.get("MANGADL_REPAIR_TOKEN") != repair_lock.read_text(encoding="utf-8"):
        raise ValueError(f"a guarded page repair is active for this library: {repair_lock}")
    inputs, rejected = collect_inputs(args.input_file, args.url)
    routes: dict[str, str] = {}
    unsupported: list[dict[str, Any]] = []
    blocked_collections: list[str] = []
    for item in inputs:
        try:
            backend = choose_backend(item.canonical_url, args.backend)
            scope = gallery_dl_scope(item.canonical_url) if backend == "gallery-dl" else None
            if args.scratch_dir is not None and backend in {"hdporncomics", "native-nhentai"}:
                raise ValueError(
                    f"scratch mode cannot safely check existing destination files for {backend}; "
                    "run without --scratch for this backend"
                )
            if args.scratch_dir is not None and scope is not None and scope.broad_collection:
                raise ValueError(
                    "scratch mode does not support broad gallery-dl collections with mixed output layouts"
                )
            if scope is not None and scope.broad_collection and not args.allow_collection:
                blocked_collections.append(item.canonical_url)
                raise ValueError(
                    f"broad gallery-dl collection ({scope.category}:{scope.subcategory}, "
                    f"{scope.extractor}) requires --allow-collection"
                )
            routes[item.canonical_url] = backend
        except ValueError as exc:
            unsupported.append({"url": item.url, "reason": str(exc)})
    inputs = [item for item in inputs if item.canonical_url in routes]
    if args.file_range and (len(inputs) != 1 or set(routes.values()) != {"gallery-dl"}):
        raise ValueError("internal targeted file range requires exactly one gallery-dl URL")
    repair_ranges = getattr(args, "repair_file_ranges", {})
    if any(routes.get(url) != "gallery-dl" for url in repair_ranges):
        raise ValueError("every targeted repair URL must be accepted by gallery-dl")
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
        "storage_media": args.storage_media,
        "storage_media_detail": args.storage_media_detail,
        "destination_storage_media": args.destination_storage_media,
        "scratch_storage_media": args.scratch_storage_media,
        "worker_start_delay": args.worker_start_delay,
        "destination": str(args.destination),
        "control_directory": str(args.destination / ".mangadl"),
        "archive": str(args.archive),
        "state_db": str(args.state_db),
        "log_dir": str(args.log_dir),
        "scratch_dir": str(args.scratch_dir) if args.scratch_dir else None,
        "partial_root": str(partial_root_for(args.destination, args.scratch_dir)),
    }
    if getattr(args, "collections", []):
        preview["kavita_collections"] = list(dict.fromkeys(name.strip() for name in args.collections if name.strip()))
        preview["kavita_write_mode"] = "apply after download" if getattr(args, "apply_kavita", False) else "queue only"
    controls = (
        ScratchControls(args.destination, args.scratch_dir, args.archive, args.state_db, args.log_dir)
        if args.scratch_dir is not None else None
    )
    if controls is not None:
        preview["scratch_archive"] = str(controls.archive)
        preview["scratch_state_db"] = str(controls.state_db)
        preview["scratch_log_dir"] = str(controls.log_dir)
        old_partial_root = args.destination / "_partial"
        preview["destination_partial_owners"] = (
            sum(1 for child in old_partial_root.iterdir() if child.is_dir())
            if old_partial_root.is_dir() else 0
        )
    if args.run_mode in {"optimize", "benchmark"}:
        preview["optimization"] = _optimization_preview(args, manga18fx_urls)
    if args.dry_run:
        print(json.dumps(preview, indent=2, sort_keys=True) if args.json else _format_run_preview(preview))
        return 1 if unsupported else 0
    if blocked_collections:
        raise ValueError(
            "refusing broad collection URL(s) because they may expand into thousands of images; "
            "inspect with --dry-run, then rerun with --allow-collection if intentional: "
            + ", ".join(blocked_collections)
        )
    if preview.get("destination_partial_owners"):
        raise ValueError(
            f"{preview['destination_partial_owners']} existing partial owner(s) remain under "
            f"{args.destination / '_partial'}; finish or inspect them before enabling --scratch"
        )
    if not inputs:
        print(json.dumps(preview, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    requested_collections = list(dict.fromkeys(name.strip() for name in getattr(args, "collections", []) if name.strip()))
    kavita_url = str(getattr(args, "kavita_url", "") or "").strip().rstrip("/")
    if requested_collections and not kavita_url:
        raise ValueError("--collections requires --kavita-url")
    if requested_collections and getattr(args, "apply_kavita", False):
        key_env = str(getattr(args, "kavita_api_key_env", "KAVITA_API_KEY"))
        KavitaConfig.from_env(kavita_url, api_key_env=key_env)
    if getattr(args, "apply_kavita", False) and not requested_collections:
        raise ValueError("--apply-kavita requires at least one --collections value")
    path_maps = parse_path_maps(getattr(args, "kavita_path_map", []))

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
    if controls is not None:
        controls.prepare()
    store = StateStore(controls.state_db if controls is not None else args.state_db)
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
            archive=controls.archive if controls is not None else args.archive,
            state_db=controls.state_db if controls is not None else args.state_db,
            log_dir=controls.log_dir if controls is not None else args.log_dir,
            scratch_dir=args.scratch_dir,
            canonical_archive=args.archive if controls is not None else None,
            maximum_workers=args.max_workers,
            fast_storage=args.fast_storage,
            file_range=args.file_range,
            repair_file_ranges=repair_ranges or None,
            workers=args.workers,
            retries=args.retries,
            retry_wait=args.retry_wait,
            gallery_config=args.gallery_config,
            cookies=args.cookies,
            cookies_browser=args.cookies_browser,
            gallery_user_agent=args.gallery_user_agent,
            auth_dir=args.auth_dir,
            auth_browser=args.auth_browser,
            auto_auth_refresh=not args.no_auth_refresh,
            rate=args.max_rate,
            hdporncomics_executable=args.hdporncomics_executable,
            hdporncomics_threads=args.hdporncomics_threads,
            worker_start_delay=args.worker_start_delay,
            ui=not args.no_ui and not args.quiet,
        )
        result = DownloadManager(options, store).run()
        if requested_collections:
            try:
                _record_kavita_assignments(
                    args,
                    run_id,
                    requested_collections,
                    kavita_url,
                    path_maps,
                    log_dir=controls.log_dir if controls is not None else args.log_dir,
                    apply=bool(getattr(args, "apply_kavita", False)),
                )
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                print(f"Kavita assignment was not recorded: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        store.close()
    if controls is not None:
        partial_root = partial_root_for(args.destination, args.scratch_dir)
        archive_safe = result == 0 and (
            not partial_root.is_dir() or not any(child.is_dir() for child in partial_root.iterdir())
        )
        controls.sync(run_id, archive_safe=archive_safe)
        if not archive_safe:
            print(
                f"Scratch partials remain at {partial_root}; canonical archive was not updated. "
                "Resume with the same --scratch path or clean the partials safely.",
                file=sys.stderr,
            )
    return result


def _record_kavita_assignments(
    args: argparse.Namespace,
    run_id: str,
    collections: list[str],
    kavita_url: str,
    path_maps: list[tuple[str, str]],
    *,
    log_dir: Path | None = None,
    apply: bool,
) -> None:
    event_path = (log_dir or args.log_dir) / run_id / "events.jsonl"
    store = PendingAssignmentStore(args.destination / ".mangadl" / "kavita-assignments.json")
    library = scan_library([args.destination])
    accepted = {"succeeded", "succeeded_incomplete"}
    queued = 0
    missing_path = 0
    for raw in event_path.read_text(encoding="utf-8", errors="replace").splitlines() if event_path.is_file() else []:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        data = event.get("data", {})
        if event.get("event") != "job_complete" or data.get("state") not in accepted:
            continue
        series_path = str(data.get("series_path") or "").strip()
        if not series_path:
            missing_path += 1
            continue
        source_url = str(event.get("url") or "")
        resolved = resolve_url_folders(source_url, library)
        if (
            len(resolved) != 1
            or resolved[0].identity_status != "matched"
            or resolved[0].path.resolve() != Path(series_path).resolve()
        ):
            missing_path += 1
            continue
        store.enqueue(source_url, series_path, collections, kavita_url=kavita_url)
        queued += 1
    if not queued:
        print("Kavita: no successful jobs had one unambiguous series folder; no assignments were queued.", file=sys.stderr)
        return
    if not apply:
        print(
            f"Kavita: saved {queued} URL-to-series assignment(s); preview with `mangadl kavita reconcile` "
            "and use `--apply` to write.",
            file=sys.stderr,
        )
        if missing_path:
            print(f"Kavita: {missing_path} successful job(s) had ambiguous output folders and were left unassigned.", file=sys.stderr)
        return
    try:
        client = KavitaClient(KavitaConfig.from_env(kavita_url, api_key_env=args.kavita_api_key_env))
        outcomes = reconcile_assignments(
            store, client, kavita_url=kavita_url, path_maps=path_maps, apply=True
        )
        pending = sum(row["status"] == "pending" for row in outcomes)
        applied = sum(row["status"] == "applied" for row in outcomes)
        print(f"Kavita: applied {applied} assignment(s); {pending} remain pending for a later library scan.", file=sys.stderr)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Kavita assignment deferred: {type(exc).__name__}: {exc}", file=sys.stderr)


def _kavita_reconcile(args: argparse.Namespace) -> int:
    config = KavitaConfig.from_env(args.kavita_url, api_key_env=args.kavita_api_key_env)
    store = PendingAssignmentStore(args.destination / ".mangadl" / "kavita-assignments.json")
    outcomes = reconcile_assignments(
        store,
        KavitaClient(config),
        kavita_url=args.kavita_url,
        path_maps=parse_path_maps(args.kavita_path_map),
        apply=args.apply,
    )
    payload = {"mode": "apply" if args.apply else "dry-run", "assignments": outcomes}
    print(json.dumps(payload, indent=2, sort_keys=True) if args.json else _format_kavita_reconcile(payload))
    return 0


def _safe_regex(pattern: str) -> re.Pattern[str]:
    if len(pattern) > 256:
        raise ValueError("pattern is too long (maximum 256 characters)")
    if (
        re.search(r"\\[1-9]|\(\?", pattern)
        or re.search(r"\([^)]*[+*][^)]*\)[+*{]", pattern)
        or re.search(r"\([^)]*\|[^)]*\)[+*{]", pattern)
    ):
        raise ValueError("pattern uses unsupported backreferences, lookarounds, or ambiguous repetition")
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"invalid series regex: {exc}") from exc


def _kavita_batch(args: argparse.Namespace) -> int:
    client = KavitaClient(KavitaConfig.from_env(args.kavita_url, api_key_env=args.kavita_api_key_env))
    series = client.list_series()
    path_maps = parse_path_maps(args.kavita_path_map)
    selected: dict[int, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    sources_by_id: dict[int, list[str]] = {}

    if args.kavita_command == "assign-file":
        inputs, rejected = collect_inputs([args.input_file], [])
        library = scan_library([args.destination])
        index_backfill = (
            backfill_source_indexes(
                (item.canonical_url for item in inputs),
                library,
            )
            if not args.no_index_backfill
            else None
        )
        for item in inputs:
            folders = resolve_url_folders(item.canonical_url, library)
            matched = [
                match_series_by_path(folder.path, series, path_maps=path_maps)
                if folder.identity_status != "ambiguous"
                else None
                for folder in folders
            ]
            unique = {int(row["id"]): row for row in matched if row and row.get("id") is not None}
            if len(folders) != 1 or len(unique) != 1:
                excluded.append({"url": item.url, "status": "ambiguous_or_unresolved", "folders": [str(row.path) for row in folders]})
                continue
            row = next(iter(unique.values()))
            series_id = int(row["id"])
            selected[series_id] = row
            sources_by_id.setdefault(series_id, []).append(item.canonical_url)
        excluded.extend({"url": row.get("value"), "status": "rejected", "reason": row.get("reason")} for row in rejected)
    elif args.kavita_command == "assign-name":
        for requested in args.name:
            matches = [row for row in series if str(row.get("name") or row.get("title") or "").casefold() == requested.casefold()]
            if len(matches) != 1 or not matches[0].get("id"):
                excluded.append({"name": requested, "status": "missing_or_ambiguous", "matches": len(matches)})
                continue
            selected[int(matches[0]["id"])] = matches[0]
    else:
        matcher = _safe_regex(args.pattern)
        by_name: dict[str, list[dict[str, Any]]] = {}
        for row in series:
            name = str(row.get("name") or row.get("title") or "")
            if matcher.search(name):
                by_name.setdefault(name.casefold(), []).append(row)
        for name, rows in by_name.items():
            if len(rows) != 1 or not rows[0].get("id"):
                excluded.append({"name": name, "status": "duplicate_name_excluded", "matches": len(rows)})
                continue
            selected[int(rows[0]["id"])] = rows[0]

    matches = []
    for series_id, row in sorted(selected.items(), key=lambda pair: (str(pair[1].get("name") or pair[1].get("title") or "").casefold(), pair[0])):
        matches.append({
            "id": series_id,
            "name": str(row.get("name") or row.get("title") or ""),
            "path": str(row.get("folderPath") or row.get("lowestFolderPath") or ""),
            "source_urls": sorted(set(sources_by_id.get(series_id, []))),
        })
    collections = list(dict.fromkeys(name.strip() for name in args.collection if name.strip()))
    if not collections:
        raise ValueError("at least one non-empty --collection is required")
    token_data = json.dumps({"matches": matches, "collections": collections}, sort_keys=True)
    token = hashlib.sha256(token_data.encode("utf-8")).hexdigest()[:16]
    apply = bool(args.apply)
    if args.kavita_command == "assign-pattern" and apply and args.confirm_matches != token:
        raise ValueError(f"pattern apply requires --confirm-matches {token} from this exact preview")
    operations = []
    if apply:
        ids = [row["id"] for row in matches]
        if ids:
            for collection in collections:
                operations.append(client.add_series_to_collection(collection, ids, apply=True))
    payload = {
        "mode": "apply" if apply else "preview",
        "selection": args.kavita_command,
        "collections": collections,
        "matches": matches,
        "excluded": excluded,
        "match_token": token,
        "index_backfill": index_backfill if args.kavita_command == "assign-file" else None,
        "operations": operations,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Kavita {payload['mode']}: {len(matches)} series -> {', '.join(collections)}")
        if index_backfill is not None:
            print(
                "Source indexes: "
                f"{index_backfill['created']} added, "
                f"{index_backfill['already_indexed']} already indexed, "
                f"{index_backfill['ambiguous']} ambiguous, "
                f"{index_backfill['empty_folder']} empty, "
                f"{index_backfill['unresolved']} unresolved, "
                f"{index_backfill['conflict']} conflicts."
            )
        for row in matches:
            print(f"- {row['id']} | {row['name']} | {row['path']}")
        for row in excluded:
            print(f"! Excluded: {row}")
        if args.kavita_command == "assign-pattern":
            print(f"Reviewed match token: {token}")
        if not apply:
            print("Preview only; use --apply to write." + (" Pattern apply also requires --confirm-matches TOKEN." if args.kavita_command == "assign-pattern" else ""))
    return 0


def _format_kavita_reconcile(payload: dict[str, Any]) -> str:
    assignments = payload["assignments"]
    if not assignments:
        return "No pending Kavita collection assignments."
    lines = [f"Kavita assignment {payload['mode']}: {len(assignments)} pending record(s)"]
    for item in assignments:
        series = item.get("series_name") or "no unique scanned series match"
        lines.append(f"- {item['source_url']} -> {series}: {', '.join(item['collections'])} ({item['status']})")
    if payload["mode"] == "dry-run":
        lines.append("Use -f/--apply to write the collection changes.")
    return "\n".join(lines)


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


def _partials(args: argparse.Namespace) -> int:
    interactive = not args.target
    selected_values = list(args.target)
    if interactive:
        selected = select_partial_owners(
            args.destination,
            state_databases=tuple(args.state_db),
            partial_root_override=partial_root_for(args.destination, args.scratch_dir) if args.scratch_dir else None,
        )
        if selected is None:
            return 0
        if not selected:
            print("No partial owners selected; nothing to clean.")
            return 0
        selected_values = [str(path) for path in selected]

    legacy_keys: dict[Path, set[str]] = {}
    if not args.files_only:
        _root, probe_targets = plan_cleanup(
            args.destination,
            selected_values,
            files_only=True,
            partial_root_override=partial_root_for(args.destination, args.scratch_dir) if args.scratch_dir else None,
        )
        legacy_owners = tuple(
            dict.fromkeys(
                target.owner.resolve()
                for target in probe_targets
                if not (target.owner / ".mangadl-partial.json").is_file()
            )
        )
        for target in probe_targets:
            if target.owner.resolve() in legacy_owners and target.path != target.owner:
                raise ValueError(
                    "legacy archive reconciliation requires selecting the whole partial owner: "
                    f"{target.owner}"
                )
        if legacy_owners:
            if args.archive is None:
                raise ValueError(
                    "legacy partial cleanup requires -a/--archive for exact URL-key reconciliation; "
                    "use --files-only only when stale archive entries are acceptable"
                )
            urls = resolve_owner_urls(
                args.destination,
                legacy_owners,
                state_databases=args.state_db,
                overrides=args.url,
            )
            for owner, url in urls.items():
                print(f"Reconstructing archive keys for {owner.name}: {url}", file=sys.stderr)
                legacy_keys[owner] = reconstruct_archive_keys(
                    url,
                    gallery_config=args.gallery_config,
                    cookies=args.cookies,
                    cookies_browser=args.cookies_browser,
                    user_agent=args.user_agent,
                    auth_dir=args.auth_dir,
                    progress=lambda message: print(message, file=sys.stderr),
                )

    partial_root, targets = plan_cleanup(
        args.destination,
        selected_values,
        archive_override=args.archive,
        files_only=args.files_only,
        legacy_archive_keys=legacy_keys,
        partial_root_override=partial_root_for(args.destination, args.scratch_dir) if args.scratch_dir else None,
    )
    preview = cleanup_preview(partial_root, targets)
    if interactive and args.apply and not args.yes:
        print(
            f"Selected {len(targets)} partial owner(s): {preview['files']} files, "
            f"{preview['bytes']} bytes, {preview['archive_matches']} archive entries.",
            file=sys.stderr,
        )
        print("Type DELETE to apply this cleanup: ", end="", file=sys.stderr, flush=True)
        if input().strip() != "DELETE":
            print("Cleanup cancelled; no files or archive entries were changed.")
            return 1
    if args.apply:
        payload = {**preview, **apply_cleanup(targets, backup=not args.no_backup), "status": "applied"}
    else:
        payload = {**preview, "status": "dry-run"}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        action = "REMOVED" if args.apply else "DRY-RUN"
        print(
            f"{action}: {payload['files']} file(s), {payload['bytes']} byte(s), "
            f"{payload['archive_matches']} matching archive entry/entries"
        )
        for target in payload["targets"]:
            print(f"  {target}")
        if args.files_only:
            print("WARNING: files-only cleanup does not remove stale gallery-dl archive entries.")
        for backup in payload.get("archive_backups", []):
            print(f"Archive backup: {backup}")
    return 0


def _patch_hdporncomics(args: argparse.Namespace) -> int:
    status = apply_patch() if args.apply else patch_status()
    print(status.message)
    return 0 if status.state == "patched" else 1


AUDIT_REPORT_SCHEMA = 1
REPAIR_PLAN_SCHEMA = 1


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _audit_report_path(args: argparse.Namespace, files: list[Path]) -> Path:
    label = files[0].stem if files else "folder"
    if len(files) > 1:
        label += f"-and-{len(files) - 1}-more"
    if args.report_output:
        path = args.report_output
        if label.casefold() not in path.stem.casefold():
            path = path.with_name(f"{path.stem}-{label}{path.suffix or '.json'}")
        return path
    return args.destination[0] / f"mangadl-{label}-audit-report.json"


def _write_audit_report(path: Path, payload: dict[str, Any]) -> Path:
    """Reserve an unused name, then publish the complete report atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = path
    number = 0
    while True:
        try:
            with candidate.open("x", encoding="utf-8"):
                pass
            break
        except FileExistsError:
            number += 1
            candidate = path.with_name(f"{path.stem}-{number}{path.suffix}")
    payload["report_output"] = str(candidate)
    try:
        _write_json_atomic(candidate, payload)
    except BaseException:
        candidate.unlink(missing_ok=True)
        raise
    return candidate


def _format_audit_page_ranges(pages: list[int]) -> str:
    ranges: list[str] = []
    for page in sorted(set(pages)):
        if not ranges:
            start = end = page
            ranges.append(str(page))
        elif page == end + 1:
            end = page
            ranges[-1] = f"{start}-{end}"
        else:
            start = end = page
            ranges.append(str(page))
    return ", ".join(ranges)


def _format_audit_findings(items: list[dict[str, Any]], *, all_findings: bool = False) -> str:
    lines: list[str] = []
    for item in items:
        status = item.get("status", item.get("identity_status", "unknown"))
        defects = any(item.get(key) for key in ("missing_pages", "corrupt_pages", "duplicate_pages", "extra_pages", "corrupt_files", "missing_image_count"))
        if not all_findings and status in {"unknown", "ambiguous"} and not defects:
            continue
        if status == "matched" and item["completeness"] == "complete" and item["image_integrity"] != "issues":
            continue
        state = status if status != "matched" else item["completeness"]
        if state == "complete":
            state = "image issues"
        url = item.get("canonical_url") or item.get("source_url") or "unknown source"
        color = "red" if state in {"missing", "incomplete", "image issues"} else "yellow"
        if lines:
            lines.append("")
        lines.append(styled(f"  {state.upper()}: {url}", color))
        folders = item.get("folders") or ([item["folder"]] if item.get("folder") else [])
        for folder in folders:
            lines.append(field("Folder", Path(folder).name))
            lines.append(field("Root", Path(folder).parent))
        if status == "missing":
            lines.append("    No matching gallery folder was found.")
            continue
        if status == "ambiguous":
            lines.append("    Identity: multiple or conflicting source candidates; source completeness is unverified.")
        expected = item.get("expected_images")
        lines.append(
            f"    Images: {item.get('valid_images', 0)}/{expected if expected is not None else 'unknown'} valid, "
            f"{item.get('present_images', 0)} files present"
        )
        for key, label in (
            ("missing_pages", "Missing pages"), ("corrupt_pages", "Corrupt pages"),
            ("duplicate_pages", "Duplicate page numbers"), ("extra_pages", "Extra pages"),
        ):
            if pages := item.get(key):
                if key == "missing_pages" and (expected is None or item.get("missing_page_evidence") == "inferred numbering gaps"):
                    lines.append("    Evidence: inferred numbering gaps, not a source-confirmed page list; trailing pages unknown.")
                lines.append(field(label, f"{_format_audit_page_ranges(pages)} ({len(pages)})", color="red"))
        if files := item.get("corrupt_files"):
            lines.append(f"    Corrupt files: {', '.join(files)}")
        if item.get("missing_image_count") and not item.get("missing_pages"):
            lines.append(f"    Missing images by count: {item['missing_image_count']}; exact page identities unavailable")
        if error := item.get("metadata_error"):
            lines.append(f"    Metadata: {error}")
    return "URLs/folders requiring attention\n" + "\n".join(lines) if lines else "No concrete gallery defects found; see summary for unresolved evidence."


def _format_audit_totals(items: list[dict[str, Any]]) -> str:
    confirmed = sum(len(item.get("missing_pages", [])) for item in items
                    if item.get("missing_page_evidence") == "source-confirmed")
    inferred = sum(len(item.get("missing_pages", [])) for item in items
                   if item.get("missing_page_evidence") != "source-confirmed")
    ambiguous = sum(item.get("status", item.get("identity_status")) == "ambiguous" for item in items)
    unknown_identity = sum(item.get("status", item.get("identity_status")) == "unknown" for item in items)
    return (
        f"  Page findings: {confirmed} source-confirmed missing, {inferred} inferred numbering gaps, "
        f"{sum(len(item.get('corrupt_files', [])) for item in items)} corrupt files, "
        f"{sum(len(item.get('duplicate_pages', [])) for item in items)} duplicate page numbers, "
        f"{sum(len(item.get('extra_pages', [])) for item in items)} extra pages\n"
        f"  Identity evidence: {ambiguous} ambiguous, {unknown_identity} unknown (overlaps completeness counts)."
    )


def _expand_audit_input_files(patterns: list[str], directories: list[Path] | None = None) -> list[Path]:
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
    for directory in directories or []:
        if not directory.is_dir():
            raise ValueError(f"URL-file directory was not found: {directory}")
        matches = sorted(
            (
                path.resolve()
                for path in directory.iterdir()
                if path.is_file() and path.suffix.casefold() == ".txt" and path.name.casefold().startswith("url")
            ),
            key=lambda path: path.name.casefold(),
        )
        if not matches:
            raise ValueError(f"URL-file directory contains no top-level url*.txt files: {directory}")
        for path in matches:
            if path not in seen:
                seen.add(path)
                files.append(path)
    return files


def _audit_destinations(args: argparse.Namespace) -> int:
    display = AuditProgress(enabled=not args.quiet)
    try:
        return _audit_destinations_impl(args, display)
    finally:
        display.close()


def _audit_destinations_impl(args: argparse.Namespace, display: AuditProgress) -> int:
    progress = None if args.quiet else display.log
    if not args.input_file and not args.url_directory:
        if progress:
            progress(f"Scanning {len(args.destination)} destination root(s) without a URL file")
        items = audit_library(
            args.destination,
            progress,
            metadata_resolver=resolve_nhentai_metadata,
            page_resolver=lambda url: resolve_expected_pages(url, progress=progress),
            item_progress=display.update,
        )
        display.close()
        payload = {
            "schema": AUDIT_REPORT_SCHEMA,
            "kind": "mangadl-audit-report",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mangadl_version": __version__,
            "mode": "folder-only",
            "destinations": [str(path) for path in args.destination],
            "folders": len(items),
            "complete": sum(item["completeness"] == "complete" for item in items),
            "incomplete": sum(item["completeness"] == "incomplete" for item in items),
            "unknown": sum(item["completeness"] == "unknown" for item in items),
            "ambiguous_identity": sum(item["identity_status"] == "ambiguous" for item in items),
            "items": items,
        }
        report_output = _write_audit_report(_audit_report_path(args, []), payload)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        if not args.json:
            print(_format_audit_findings(items, all_findings=args.all_findings))
            print(styled("\nAudit summary", "bright"))
            print(f"  Audited {payload['folders']} folder(s): " + styled(f"{payload['complete']} complete", "green") + ", "
                  + styled(f"{payload['incomplete']} incomplete", "red") + ", " + styled(f"{payload['unknown']} unknown", "yellow") + ".")
            print(_format_audit_totals(items))
            present = sum(item["association_present"] for item in items)
            print(f"  Source associations: {present} present, {len(items) - present} missing; folder audit creates none.")
            print(f"Audit report: {report_output}")
        elif progress:
            progress(f"Wrote audit report: {report_output}")
        return 0
    files = _expand_audit_input_files(args.input_file or [], args.url_directory)
    if progress:
        progress(f"Loading {len(files)} URL file(s)")
    inputs, rejected = collect_inputs(files, [])
    duplicate_lines = sum(row["reason"] == "duplicate" for row in rejected)
    invalid_lines = len(rejected) - duplicate_lines
    if progress:
        progress(
            f"Loaded {len(inputs)} unique URL(s); {duplicate_lines} duplicate line(s); "
            f"{invalid_lines} rejected/invalid line(s)"
        )
    audit = audit_destinations(
        inputs,
        args.destination,
        progress,
        metadata_resolver=resolve_nhentai_metadata,
        page_resolver=lambda url: resolve_expected_pages(url, progress=progress),
        backfill_index=not args.no_index_backfill,
        item_progress=display.update,
    )
    display.close()
    write_audit_outputs(audit, args.missing_output, args.duplicates_output)
    item_results = []
    for item in inputs:
        folders = audit.resolved.get(item.canonical_url, [])
        detail = audit.details[item.canonical_url]
        item_results.append(
            {
                "url": item.url,
                "canonical_url": item.canonical_url,
                "source": item.source,
                "line": item.line,
                "status": detail["folder_status"],
                "folders": [str(path) for path in folders],
                **detail,
                "reason": detail.get("metadata_error"),
            }
        )
    payload = {
        "schema": AUDIT_REPORT_SCHEMA,
        "kind": "mangadl-audit-report",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mangadl_version": __version__,
        "mode": "url-file",
        "input_files": [str(path) for path in files],
        "destinations": [str(path) for path in args.destination],
        "input_entries": len(inputs) + len(rejected),
        "input_urls": len(inputs),
        "rejected": rejected,
        "duplicate_url_lines": duplicate_lines,
        "invalid_url_lines": invalid_lines,
        "resolved": len(audit.resolved),
        "unresolved": len(audit.unresolved),
        "duplicates": len(audit.duplicates),
        "duplicate_folder_groups": len(audit.duplicates),
        "index_backfill": audit.index_backfill,
        "association_inventory": audit.association_inventory,
        "untracked_folders": [str(path) for path in audit.untracked_folders],
        "complete": sum(item["completeness"] == "complete" for item in item_results),
        "incomplete": sum(item["completeness"] == "incomplete" for item in item_results),
        "unknown": sum(item["completeness"] == "unknown" for item in item_results),
        "corrupt": sum(bool(item.get("corrupt_files")) for item in item_results),
        "issue_urls": sum(
            item["status"] != "matched"
            or item["completeness"] != "complete"
            or item["image_integrity"] == "issues"
            for item in item_results
        ),
        "items": item_results,
        "missing_output": str(args.missing_output) if args.missing_output else None,
        "duplicates_output": str(args.duplicates_output) if args.duplicates_output else None,
    }
    report_output = _write_audit_report(_audit_report_path(args, files), payload)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_audit_findings(item_results, all_findings=args.all_findings))
        invalid = [row for row in rejected if row["reason"] != "duplicate"]
        if invalid:
            print("Rejected/invalid input lines")
            for row in invalid:
                print(f"  {row['source']}:{row['line']}: {row['value']} — {row['reason']}")
        print(styled("\nAudit summary", "bright"))
        print(f"  URL files: {len(files)}")
        print(
            f"  Input entries: {payload['input_entries']} ({payload['input_urls']} unique, "
            f"{payload['duplicate_url_lines']} duplicate, {payload['invalid_url_lines']} rejected/invalid)"
        )
        print(
            f"  Identity: {payload['resolved']} found, {payload['unresolved']} missing, "
            f"{payload['duplicate_folder_groups']} duplicate folder group(s), "
            f"{len(payload['untracked_folders'])} untracked folder(s)"
        )
        print(
            "  Verification: " + styled(f"{payload['complete']} complete", "green") + ", "
            + styled(f"{payload['incomplete']} incomplete", "red") + ", "
            + styled(f"{payload['unknown']} unknown", "yellow") + ", "
            + styled(f"{payload['corrupt']} with corrupt pages", "red")
        )
        print(styled(f"  URLs requiring attention: {payload['issue_urls']}", "red" if payload['issue_urls'] else "green"))
        print(_format_audit_totals(item_results))
        inventory = audit.association_inventory or {}
        print(f"  Source associations before audit: {inventory.get('already_indexed', 0)} present, "
              f"{inventory.get('missing', 0)} safely creatable/missing, {inventory.get('conflict', 0)} conflicts, "
              f"{inventory.get('ambiguous', 0)} ambiguous, {inventory.get('unresolved', 0)} unresolved.")
        if audit.index_backfill is not None:
            print(
                f"Source indexes: {audit.index_backfill['created']} added, "
                f"{audit.index_backfill['already_indexed']} already indexed, "
                f"{audit.index_backfill['ambiguous']} ambiguous, "
                f"{audit.index_backfill['empty_folder']} empty, "
                f"{audit.index_backfill['unresolved']} unresolved, "
                f"{audit.index_backfill['conflict']} conflicts."
            )
        else:
            print("  Source association writes disabled (-x); no source indexes created.")
        print(field("Audit report", report_output, indent=0, color="cyan"))
    if progress and args.missing_output:
        progress(f"Wrote missing URLs: {args.missing_output}")
    if progress and args.duplicates_output:
        progress(f"Wrote duplicate folders: {args.duplicates_output}")
    if progress and args.json:
        progress(f"Wrote audit report: {report_output}")
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


def _repair_pages(args: argparse.Namespace) -> int:
    from .library_guard import library_write_guard

    with library_write_guard(args.destination) if args.apply else nullcontext():
        return _repair_pages_owned(args)


def _repair_pages_owned(args: argparse.Namespace) -> int:
    inputs, rejected = collect_inputs([], [args.url])
    if rejected or len(inputs) != 1:
        raise ValueError("repair-pages requires exactly one valid gallery URL")
    item = inputs[0]
    if not re.fullmatch(r"https?://(?:www\.)?nhentai\.net/g/\d+/?", item.canonical_url):
        raise ValueError("targeted repair is currently supported only for individual nhentai galleries")
    if args.gallery_config:
        raise ValueError(
            "targeted repair refuses custom gallery-dl configuration because its archive table and "
            "key overrides cannot be proven; use explicit cookies/browser/user-agent options instead"
        )
    archive = args.archive or (args.destination / ".mangadl" / "archive.sqlite3")
    def progress(message: str) -> None:
        print(f"Repair: {message}", file=sys.stderr, flush=True)

    audit = audit_destinations(
        [item], [args.destination], progress, metadata_resolver=resolve_nhentai_metadata
    )
    detail = audit.details[item.canonical_url]
    folders = audit.resolved.get(item.canonical_url, [])
    if detail["folder_status"] != "matched" or len(folders) != 1:
        raise ValueError("repair requires one unambiguous source-to-folder match")
    if detail["expected_images"] is None:
        raise ValueError("expected page count is unavailable; repair remains report-only")
    page_set = resolve_expected_pages(item.canonical_url, progress=progress)
    if page_set is None or not page_set.complete_identity_set:
        raise ValueError("source page identities are unavailable; repair remains report-only")
    page_keys = reconstruct_archive_page_keys(
        item.canonical_url,
        gallery_config=args.gallery_config,
        cookies=args.cookies,
        cookies_browser=args.cookies_browser,
        user_agent=args.user_agent,
        auth_dir=args.destination / ".mangadl" / "auth",
    )
    plan = make_page_repair_plan(
        item.canonical_url,
        folders[0],
        int(detail["expected_images"]),
        list(detail["missing_pages"]),
        list(detail.get("corrupt_files", [])),
        page_keys,
        archive,
    )
    payload: dict[str, Any] = {
        "mode": "apply" if args.apply else "preview",
        "url": plan.url,
        "folder": str(plan.folder),
        "expected_pages": plan.expected_count,
        "damaged_pages": list(plan.damaged_pages),
        "archive_keys_to_reconcile": [plan.page_keys[page] for page in plan.damaged_pages if page in plan.page_keys],
        "archive_rows_present": list(plan.archive_rows_found),
        "corrupt_files_to_quarantine": [str(path) for path in plan.corrupt_files],
        "eligible": plan.eligible,
    }
    confirmation_token = repair_confirmation_token(plan)
    payload["confirmation_token"] = confirmation_token
    if not plan.damaged_pages:
        payload["verified"] = detail["completeness"] == "complete"
        print(json.dumps(payload, indent=2, sort_keys=True) if args.json else "No missing or corrupt pages were found.")
        return 0
    if not plan.eligible:
        raise ValueError("not every damaged page has an exact gallery-dl archive identity")
    if not args.apply:
        print(json.dumps(payload, indent=2, sort_keys=True) if args.json else (
            f"DRY-RUN: {len(plan.damaged_pages)} damaged page(s) for {plan.url} in {plan.folder}. "
            "Use -f/--apply to quarantine corrupt files and redownload only these pages."
        ))
        return 0
    if args.confirm_plan != confirmation_token:
        raise ValueError(
            "--apply requires --confirm-plan with the token from the current exact preview"
        )

    _assert_no_active_mangadl_run(args.destination)

    def run_download(file_range: str, token: str) -> None:
        old_token = os.environ.get("MANGADL_REPAIR_TOKEN")
        os.environ["MANGADL_REPAIR_TOKEN"] = token
        run_args = [
            "run", "-u", item.canonical_url, "-d", str(args.destination), "-a", str(archive),
            "-b", "gallery-dl", "-w", "1", "-m", "1", "-0", file_range, "-N",
        ]
        if args.gallery_config:
            run_args.extend(["-g", str(args.gallery_config)])
        if args.cookies:
            run_args.extend(["-c", str(args.cookies)])
        if args.cookies_browser:
            run_args.extend(["-B", args.cookies_browser])
        if args.user_agent:
            run_args.extend(["-U", args.user_agent])
        if args.rate:
            run_args.extend(["-r", args.rate])
        if args.scratch:
            run_args.extend(["-S", str(args.scratch)])
        try:
            try:
                result = main(run_args)
            except SystemExit as exc:
                raise RuntimeError(f"targeted download manager exited: {exc.code}") from exc
        finally:
            if old_token is None:
                os.environ.pop("MANGADL_REPAIR_TOKEN", None)
            else:
                os.environ["MANGADL_REPAIR_TOKEN"] = old_token
        if result != 0:
            raise RuntimeError(f"targeted download manager returned exit status {result}")

    def verify_repair() -> tuple[bool, set[int]]:
        verified = audit_destinations(
            [item], [args.destination], None, metadata_resolver=resolve_nhentai_metadata
        ).details[item.canonical_url]
        return verified["completeness"] == "complete", set(verified["missing_pages"])

    result = apply_page_repair(
        plan,
        archive,
        args.destination / ".mangadl" / "repair-quarantine",
        run_download,
        verify_repair,
    )
    payload.update(result)
    print(json.dumps(payload, indent=2, sort_keys=True) if args.json else (
        f"{'REPAIRED' if result['verified'] else 'INCOMPLETE'}: "
        f"{len(plan.damaged_pages) - len(result['remaining_pages'])}/{len(plan.damaged_pages)} target page(s) verified; "
        f"backup={result['archive_backup'] or 'not needed'}"
    ))
    return 0 if result["verified"] else 1


def _assert_no_active_mangadl_run(destination: Path) -> None:
    state_db = destination / ".mangadl" / "state.sqlite3"
    if state_db.is_file():
        connection = sqlite3.connect(state_db.as_uri() + "?mode=ro", uri=True)
        try:
            has_runs = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
            ).fetchone()
            if has_runs is None:
                raise ValueError(f"state database does not contain MangaDL run history: {state_db}")
            active = connection.execute(
                "SELECT id FROM runs WHERE status='running' AND finished IS NULL LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        if active:
            raise ValueError(f"MangaDL run {active[0]} is active; wait for it to finish before repair")


def _load_audit_report(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read audit report {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("kind") != "mangadl-audit-report":
        raise ValueError(f"not a MangaDL audit report: {path}")
    if payload.get("schema") != AUDIT_REPORT_SCHEMA:
        raise ValueError(f"unsupported MangaDL audit report schema: {payload.get('schema')!r}")
    if payload.get("mode") != "url-file":
        raise ValueError("batch repair requires a URL-file audit report")
    if not isinstance(payload.get("items"), list) or not isinstance(payload.get("destinations"), list):
        raise ValueError("audit report is missing items or destinations")
    return payload, hashlib.sha256(raw).hexdigest()


def _containing_destination(folder: Path, destinations: list[Path]) -> Path | None:
    resolved = folder.resolve()
    matches = [root for root in destinations if resolved == root or root in resolved.parents]
    return max(matches, key=lambda root: len(root.parts)) if matches else None


def _archive_for_destination(args: argparse.Namespace, destination: Path, action_roots: set[Path]) -> Path:
    if args.archive:
        if len(action_roots) > 1:
            raise ValueError("--archive cannot be shared across repair actions in multiple destination roots")
        return args.archive
    return destination / ".mangadl" / "archive.sqlite3"


def _fresh_page_plan(
    item: dict[str, Any],
    destination: Path,
    args: argparse.Namespace,
    progress,
):
    url = str(item["canonical_url"])
    if not re.fullmatch(r"https?://(?:www\.)?nhentai\.net/g/\d+/?", url):
        raise ValueError("exact-page repair is currently proven only for individual nhentai galleries")
    if args.gallery_config:
        raise ValueError("exact-page repair cannot prove archive keys with a custom gallery-dl configuration")
    inputs, rejected = collect_inputs([], [url])
    if rejected or len(inputs) != 1:
        raise ValueError("audit report contains an invalid repair URL")
    fresh = audit_destinations(
        inputs,
        [destination],
        progress,
        metadata_resolver=resolve_nhentai_metadata,
    )
    detail = fresh.details[url]
    folders = fresh.resolved.get(url, [])
    if detail["folder_status"] != "matched" or len(folders) != 1:
        raise ValueError("repair requires one current unambiguous source-to-folder match")
    if detail["expected_images"] is None:
        raise ValueError("expected page count is unavailable")
    # The fresh count plus the complete unique archive page map below prove
    # the nhentai target set; a second page enumeration is redundant.
    page_keys = reconstruct_archive_page_keys(
        url,
        cookies=args.cookies,
        cookies_browser=args.cookies_browser,
        user_agent=args.user_agent,
        auth_dir=destination / ".mangadl" / "auth",
    )
    archive = _archive_for_destination(args, destination, {destination})
    plan = make_page_repair_plan(
        url,
        folders[0],
        int(detail["expected_images"]),
        list(detail["missing_pages"]),
        list(detail.get("corrupt_files", [])),
        page_keys,
        archive,
    )
    if plan.damaged_pages and not plan.eligible:
        raise ValueError("not every damaged page has an exact gallery-dl archive identity")
    return plan, archive


def _build_batch_repair_plan(args: argparse.Namespace) -> tuple[dict[str, Any], dict[int, tuple[Any, Path]]]:
    if args.workers < 1 or args.max_workers is not None and args.max_workers < 1:
        raise ValueError("repair workers and maximum workers must be at least 1")
    if args.worker_start_delay < 0:
        raise ValueError("repair worker start delay must be zero or greater")
    report, report_digest = _load_audit_report(args.report)
    destinations = [Path(value).expanduser().resolve() for value in report["destinations"]]
    if not destinations:
        raise ValueError("audit report contains no destination roots")
    if args.archive and len(destinations) > 1:
        raise ValueError("--archive cannot be shared by a report containing multiple destination roots")
    missing_destination = args.destination or (destinations[0] if len(destinations) == 1 else None)

    def progress(message: str) -> None:
        print(f"Repair: {message}", file=sys.stderr, flush=True)

    actions: list[dict[str, Any]] = []
    unsupported: list[dict[str, str]] = []
    prepared: dict[int, tuple[Any, Path]] = {}
    missing_urls = any(
        isinstance(item, dict) and item.get("status") == "missing"
        for item in report["items"]
    )
    current_roots = list(dict.fromkeys([
        *destinations,
        *([missing_destination] if missing_destination else []),
    ]))
    current_library = scan_library(current_roots, progress=progress) if missing_urls else []

    for item in report["items"]:
        if not isinstance(item, dict) or not item.get("canonical_url"):
            continue
        url = str(item["canonical_url"])
        status = item.get("status")
        completeness = item.get("completeness")
        integrity = item.get("image_integrity")
        if status == "missing":
            if resolve_url_folders(url, current_library):
                unsupported.append({
                    "url": url,
                    "reason": "audit report is stale: a matching folder now exists; run audit again",
                })
                continue
            if missing_destination is None:
                unsupported.append({
                    "url": url,
                    "reason": "select --destination for missing galleries when the audit used multiple roots",
                })
                continue
            try:
                backend = choose_backend(url)
                scope = gallery_dl_scope(url) if backend == "gallery-dl" else None
                if args.scratch and backend in {"hdporncomics", "native-nhentai"}:
                    raise ValueError(f"scratch mode is not supported for the {backend} backend")
                if scope is not None and scope.broad_collection:
                    raise ValueError("broad gallery-dl collections require a separate reviewed download")
            except ValueError as exc:
                unsupported.append({"url": url, "reason": str(exc)})
                continue
            actions.append({
                "kind": "download_gallery",
                "url": url,
                "backend": backend,
                "destination": str(missing_destination),
                "reason": "URL has no matched gallery folder",
            })
            continue
        if status != "matched":
            unsupported.append({"url": url, "reason": f"folder identity is {status or 'unknown'}"})
            continue
        has_damage = completeness == "incomplete" or integrity == "issues"
        if not has_damage:
            if completeness != "complete":
                unsupported.append({
                    "url": url,
                    "reason": "completion is unknown; no exact repair target can be established",
                })
            continue
        folders = [Path(value).expanduser().resolve() for value in item.get("folders", [])]
        if len(folders) != 1:
            unsupported.append({"url": url, "reason": "repair requires exactly one matched folder"})
            continue
        destination = _containing_destination(folders[0], destinations)
        if destination is None:
            unsupported.append({"url": url, "reason": "matched folder is outside the report destination roots"})
            continue
        try:
            page_plan, archive = _fresh_page_plan(item, destination, args, progress)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            unsupported.append({"url": url, "reason": str(exc)})
            continue
        if not page_plan.damaged_pages:
            continue
        action_index = len(actions)
        actions.append({
            "kind": "repair_pages",
            "url": url,
            "destination": str(destination),
            "folder": str(page_plan.folder),
            "expected_pages": page_plan.expected_count,
            "damaged_pages": list(page_plan.damaged_pages),
            "archive": str(archive),
            "archive_keys_to_reconcile": [page_plan.page_keys[page] for page in page_plan.damaged_pages],
            "archive_rows_present": list(page_plan.archive_rows_found),
            "corrupt_files_to_quarantine": [str(path) for path in page_plan.corrupt_files],
        })
        prepared[action_index] = (page_plan, archive)

    token_payload = {
        "schema": REPAIR_PLAN_SCHEMA,
        "report_sha256": report_digest,
        "actions": actions,
        "unsupported": unsupported,
    }
    token = hashlib.sha256(json.dumps(token_payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    plan = {
        "schema": REPAIR_PLAN_SCHEMA,
        "kind": "mangadl-repair-plan",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mangadl_version": __version__,
        "mode": "apply" if args.apply else "preview",
        "audit_report": str(args.report),
        "audit_report_sha256": report_digest,
        "actions": actions,
        "unsupported": unsupported,
        "action_count": len(actions),
        "unsupported_count": len(unsupported),
        "confirmation_token": token,
        "workers": args.workers,
        "max_workers": args.max_workers,
    }
    return plan, prepared


def _format_batch_repair_plan(plan: dict[str, Any]) -> str:
    lines = [
        styled("\nRepair plan", "bright"),
        f"  Planned actions: {plan['action_count']}",
        f"  Report-only/unsupported issues: {plan['unsupported_count']}",
    ]
    if "workers" in plan:
        lines.append(f"  Downloader workers: {plan['workers']} (normal dashboard; one queue per destination)")
    for index, action in enumerate(plan["actions"], 1):
        lines.append("")
        if action["kind"] == "repair_pages":
            lines.append(styled(f"  {index}. Repair {len(action['damaged_pages'])} page(s)", "yellow"))
            lines.append(field("URL", action["url"], color="cyan"))
            lines.append(field("Folder", Path(action["folder"]).name))
            lines.append(field("Pages", _format_audit_page_ranges(action["damaged_pages"]), color="yellow"))
        else:
            lines.append(styled(f"  {index}. Download missing gallery", "yellow"))
            lines.append(field("URL", action["url"], color="cyan"))
        lines.append(field("Destination", action["destination"]))
    for row in plan["unsupported"]:
        lines.append("\n" + styled(f"  REPORT ONLY: {row['url']}", "red"))
        lines.append(field("Reason", row["reason"], color="yellow"))
    if plan["actions"]:
        lines.append("\n" + styled(f"  Confirmation token: {plan['confirmation_token']}", "green"))
        if plan["mode"] == "preview":
            lines.append("  Re-run with -f/--apply and -C/--confirm-plan TOKEN to apply this exact plan.")
    return "\n".join(lines)


def _repair_run_arguments(action: dict[str, Any], args: argparse.Namespace, archive: Path) -> list[str]:
    run_args = [
        "run", "-u", action["url"], "-d", action["destination"], "-a", str(archive),
        "-b", "auto", "-w", str(args.workers),
        "--worker-start-delay", str(args.worker_start_delay),
    ]
    if args.max_workers is not None:
        run_args.extend(["--max-workers", str(args.max_workers)])
    if args.no_ui or args.json:
        run_args.append("--no-ui")
    if args.gallery_config:
        run_args.extend(["-g", str(args.gallery_config)])
    if args.cookies:
        run_args.extend(["--cookies", str(args.cookies)])
    if args.cookies_browser:
        run_args.extend(["-B", args.cookies_browser])
    if args.user_agent:
        run_args.extend(["--gallery-user-agent", args.user_agent])
    if args.rate:
        run_args.extend(["--max-rate", args.rate])
    if args.scratch:
        run_args.extend(["-S", str(args.scratch)])
    return run_args


def _run_nested(argv: list[str]) -> int:
    try:
        return main(argv)
    except SystemExit as exc:
        raise RuntimeError(f"download manager exited: {exc.code}") from exc


def _backfill_repaired_source(url: str, destination: Path) -> dict[str, int]:
    return backfill_source_indexes([url], scan_library([destination]))


def _run_repair_queue(actions, args, archive, page_plans, token) -> int:
    run_args = _repair_run_arguments(actions[0], args, archive)
    for action in actions[1:]:
        run_args.extend(["--url", action["url"]])
    old_token = os.environ.get("MANGADL_REPAIR_TOKEN")
    if token:
        os.environ["MANGADL_REPAIR_TOKEN"] = token
    try:
        # JSON repair output remains one document; manager status/progress goes
        # to stderr rather than adding a second JSON value to stdout.
        with redirect_stdout(sys.stderr) if args.json else nullcontext():
            if not page_plans:
                return _run_nested(run_args)
            run_namespace = build_parser(run_args).parse_args(run_args)
            run_namespace.repair_file_ranges = {
                plan.url: ",".join(str(page) for page in plan.damaged_pages) for plan in page_plans
            }
            return _run(run_namespace)
    finally:
        if old_token is None:
            os.environ.pop("MANGADL_REPAIR_TOKEN", None)
        else:
            os.environ["MANGADL_REPAIR_TOKEN"] = old_token


def _batch_repair(args: argparse.Namespace) -> int:
    plan, prepared = _build_batch_repair_plan(args)
    if args.plan_output:
        _write_json_atomic(args.plan_output, plan)
    if not args.json:
        print(_format_batch_repair_plan(plan))
    if not args.apply:
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    if args.confirm_plan != plan["confirmation_token"]:
        raise ValueError("--apply requires --confirm-plan with the token from the current exact repair preview")

    from contextlib import ExitStack
    from .library_guard import library_write_guard

    with ExitStack() as owners:
        destinations = sorted({Path(action["destination"]).resolve() for action in plan["actions"]})
        for destination in destinations:
            owners.enter_context(library_write_guard(destination))
        return _apply_batch_repair_owned(args, plan, prepared)


def _apply_batch_repair_owned(args, plan, prepared) -> int:

    results: list[dict[str, Any]] = []
    groups: dict[tuple[Path, Path], list[tuple[int, dict[str, Any]]]] = {}
    for index, action in enumerate(plan["actions"]):
        destination = Path(action["destination"])
        archive = prepared[index][1] if action["kind"] == "repair_pages" else _archive_for_destination(
            args, destination, {destination}
        )
        groups.setdefault((destination, archive), []).append((index, action))

    for (destination, archive), group in groups.items():
        actions = [action for _index, action in group]
        page_plans = [prepared[index][0] for index, action in group if action["kind"] == "repair_pages"]
        try:
            _assert_no_active_mangadl_run(destination)
            verified_details = None
            controls = ScratchControls(destination, args.scratch, archive,
                                       destination / ".mangadl" / "state.sqlite3",
                                       destination / ".mangadl" / "logs") if args.scratch else None
            pending_scratch = controls.validate_pending() if controls else False
            queue_returned = False

            def run_download(plans, token) -> None:
                nonlocal queue_returned
                if pending_scratch and controls:
                    # Canonical keys were deliberately cleared under this
                    # repair lock. Mirror those exact targets to the working
                    # archive, and checkpoint only this owned baseline change.
                    clear_page_repair_archive(plans, controls.archive)
                    archive_cleanup_checkpoint(partial_root_for(destination, args.scratch),
                                               controls.archive, archive, verify=False)
                returncode = _run_repair_queue(actions, args, archive, plans, token)
                queue_returned = True
                if returncode != 0:
                    raise RuntimeError(f"download manager returned exit status {returncode}")

            def verify_repair(page_plan) -> tuple[bool, set[int]]:
                nonlocal verified_details
                if verified_details is None:
                    inputs, _rejected = collect_inputs([], [item.url for item in page_plans])
                    counts = {item.url.rstrip("/").rsplit("/", 1)[-1]: item.expected_count for item in page_plans}
                    verified_details = audit_destinations(
                        inputs, [destination], None,
                        metadata_resolver=lambda gallery_id: SimpleNamespace(page_count=counts[gallery_id]),
                    ).details
                verified = verified_details[page_plan.url]
                return verified["completeness"] == "complete", set(verified["missing_pages"])

            if page_plans:
                page_results = apply_page_repairs(
                    page_plans, archive, destination / ".mangadl" / "repair-quarantine", run_download, verify_repair,
                )
                if controls and queue_returned and controls.manifest.is_file():
                    if json.loads(controls.manifest.read_text(encoding="utf-8")).get("pending"):
                        archive_cleanup_checkpoint(partial_root_for(destination, args.scratch),
                                                   controls.archive, archive, verify=False)
            else:
                run_download([], "")
                page_results = []
            pages_by_url = {row["url"]: row for row in page_results}
            for action in actions:
                index_result = _backfill_repaired_source(action["url"], destination)
                if action["kind"] == "repair_pages":
                    results.append({"kind": action["kind"], **pages_by_url[action["url"]], "index_backfill": index_result})
                    continue
                inputs, _rejected = collect_inputs([], [action["url"]])
                verified = audit_destinations(
                    inputs,
                    [destination],
                    None,
                    metadata_resolver=resolve_nhentai_metadata,
                    page_resolver=resolve_expected_pages,
                ).details[action["url"]]
                results.append({
                    "url": action["url"],
                    "kind": action["kind"],
                    "downloaded": True,
                    "verified": verified["completeness"] == "complete",
                    "verification": verified["completeness"],
                    "index_backfill": index_result,
                })
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            results.extend({
                "url": action["url"],
                "kind": action["kind"],
                "verified": False,
                "error": f"{type(exc).__name__}: {exc}",
            } for action in actions)

    payload = {**plan, "results": results}
    succeeded = sum(bool(row.get("verified")) for row in results)
    payload["verified_actions"] = succeeded
    payload["failed_or_unverified_actions"] = len(results) - succeeded
    if args.plan_output:
        _write_json_atomic(args.plan_output, payload)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(styled(f"\nRepair results: {succeeded} verified, {len(results) - succeeded} failed or unverified.",
                     "green" if succeeded == len(results) else "red"))
        for row in results:
            state = "VERIFIED" if row.get("verified") else "NOT VERIFIED"
            detail = row.get("error") or row.get("run_error") or row.get("verification") or ""
            print(styled(f"  {state}: {row['url']}", "green" if row.get("verified") else "red"))
            if detail:
                print(field("Detail", detail))
            if row.get("remaining_pages"):
                print(field("Remaining pages", _format_audit_page_ranges(row["remaining_pages"]), color="red"))
    if plan["unsupported_count"]:
        return 1
    return 0 if succeeded == len(results) else 1


def _interactive_auth_site(targets: TargetStore, query: str | None) -> str:
    if not sys.stdin.isatty():
        raise ValueError("interactive site selection requires a terminal; use --site NAME")
    selected_query = (query or input("Filter installed gallery-dl sites: ")).strip().lower()
    choices = [site for site in gallery_sites(targets) if selected_query in site.name]
    if not choices:
        raise ValueError(f"no installed gallery-dl sites match {selected_query!r}")
    if len(choices) > 50:
        raise ValueError(f"{len(choices)} sites match; use --site-filter to narrow the list to 50 or fewer")
    for index, site in enumerate(choices, 1):
        marker = "saved" if site.target_url else "URL needed"
        example = site.examples[0] if site.examples else "no example"
        print(f"{index:3}. {site.name:<24} [{marker}] {example}", file=sys.stderr)
    raw = input("Select site number: ").strip()
    try:
        return choices[int(raw) - 1].name
    except (ValueError, IndexError) as exc:
        raise ValueError(f"invalid site selection: {raw!r}") from exc


def _prompt_auth_target(site: str, targets: TargetStore) -> str:
    if not sys.stdin.isatty():
        raise ValueError(
            f"no saved target URL for gallery-dl site {site!r}; rerun with --url ACTUAL_GALLERY_URL"
        )
    print(
        f"No validated target URL is saved for gallery-dl site {site!r}.\n"
        "Open the site and paste an actual gallery/series URL that gallery-dl supports; "
        "a homepage or search page may not work.",
        file=sys.stderr,
    )
    while True:
        url = input("Target URL: ").strip()
        try:
            targets.save(site, url)
        except ValueError as exc:
            print(f"Invalid target: {exc}", file=sys.stderr)
            continue
        return url


def _resolve_auth_target(args: argparse.Namespace, targets: TargetStore) -> tuple[str, str]:
    if args.select_site and args.site:
        raise ValueError("--select-site cannot be combined with --site")
    if args.select_site:
        site = _interactive_auth_site(targets, args.site_filter)
    elif args.site:
        site = targets.resolve_site(args.site)
    else:
        site = DEFAULT_AUTH_SITE
    if args.url:
        actual_site = site_for_url(args.url)
        if args.site or args.select_site:
            if actual_site != site:
                raise ValueError(f"URL belongs to gallery-dl site {actual_site!r}, not selected site {site!r}")
        else:
            site = actual_site
        targets.save(site, args.url)
        return site, args.url
    url = targets.url_for(site)
    return site, url or _prompt_auth_target(site, targets)


def _auth(args: argparse.Namespace) -> int:
    store = ProfileStore(args.auth_dir)
    targets = TargetStore(store.root)
    if args.auth_command == "sites":
        query = args.filter.lower()
        sites = [
            site
            for site in gallery_sites(targets)
            if query in site.name and (not args.known_only or site.target_url)
        ]
        payload = [
            {
                "site": site.name,
                "extractors": site.extractor_count,
                "target_url": site.target_url,
                "examples": list(site.examples),
            }
            for site in sites
        ]
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for site in sites:
                target = site.target_url or "URL needed"
                print(f"{site.name:<28} extractors={site.extractor_count:<3} target={target}")
            print(f"{len(sites)} installed gallery-dl site(s)")
        return 0
    if args.auth_command == "refresh":
        site, url = _resolve_auth_target(args, targets)
        profile, probe = refresh_profile(
            url,
            store=store,
            browser=args.browser,
            debug_port=args.debug_port,
            timeout=args.timeout,
            no_launch=args.no_launch_browser,
            cookie_file=args.cookie_file,
            user_agent=args.user_agent,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
        payload = {
            "site": site,
            "target_url": url,
            "domain": domain_for(url),
            "browser": args.browser,
            "profile": "present" if profile else "absent",
            "validation": probe.status,
            "message": probe.message,
        }
        if profile:
            summary = cookie_summary(profile.cookie_path)
            payload.update(
                {
                    "cookie_file": str(profile.cookie_path),
                    "cookies": summary.count,
                    "cookie_names": list(summary.names),
                    "user_agent": "present",
                    "updated_at": profile.updated_at,
                }
            )
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif profile:
            print(
                f"[{payload['domain']}] credentials captured: {payload['cookies']} cookie(s), "
                f"browser={args.browser}; validation succeeded\nprofile: {payload['cookie_file']}"
            )
        else:
            print(f"[{payload['domain']}] authentication refresh failed: {probe.message}", file=sys.stderr)
        return 0 if profile else 1

    value = args.url or args.domain
    domain = domain_for(value)
    if args.auth_command == "clear":
        removed = store.clear(domain)
        payload = {"domain": domain, "removed": removed}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"[{domain}] managed authentication {'removed' if removed else 'was not present'}")
        return 0

    profile = store.load(domain)
    payload: dict[str, Any] = {"domain": domain, "profile": "present" if profile else "absent"}
    if profile:
        summary = cookie_summary(profile.cookie_path)
        payload.update(
            {
                "browser": profile.browser,
                "source": profile.source,
                "cookie_file": str(profile.cookie_path),
                "cookies": summary.count,
                "cookie_names": list(summary.names),
                "earliest_expiry": summary.earliest_expiry,
                "expired": summary.expired,
                "user_agent": "present",
                "updated_at": profile.updated_at,
            }
        )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif not profile:
        print(f"[{domain}] managed authentication profile: absent")
    else:
        print(
            f"domain: {domain}\nprofile: present\nbrowser: {profile.browser}\n"
            f"cookies: {payload['cookies']}\nexpired: {payload['expired']}\nuser-agent: present\n"
            f"cookie file: {profile.cookie_path}"
        )
    return 0 if profile else 1


def _favorites(args: argparse.Namespace) -> int:
    progress = None if args.quiet else lambda message: print(message, file=sys.stderr, flush=True)
    result = crawl_favorites(
        args.url,
        auth_dir=args.auth_dir,
        cookie_file=args.cookies,
        cookies_browser=args.cookies_browser,
        user_agent=args.user_agent,
        max_pages=args.max_pages,
        page_delay=args.page_delay,
        timeout=args.timeout,
        progress=progress,
    )
    if args.apply:
        write_url_file(args.output, result)
    payload = favorites_result_payload(result, args.output, args.apply)
    print(
        json.dumps(payload, indent=2, sort_keys=True)
        if args.json
        else format_favorites_result(result, args.output, args.apply)
    )
    return 0


def _compress(args: argparse.Namespace) -> int:
    from .compress import run_cli as run_compress_cli

    return run_compress_cli(args)


def _format_lock_table(locks) -> str:
    from termdash.table import render_table
    from termdash.utils import fmt_hms, format_bytes_decimal

    rows: list[list[str]] = []
    for rec in locks:
        status_str = "ENGAGED" if rec.engaged else ("STALE" if rec.stale else ("CLEANED" if rec.auto_cleaned else "IDLE"))
        proc = rec.process
        pid_str = str(proc.pid) if proc and proc.pid else (str(rec.holder.get("pid")) if rec.holder and rec.holder.get("pid") else "-")
        proc_state = "-"
        if proc is not None:
            parts = [proc.state]
            if proc.cpu_seconds is not None:
                parts.append(f"cpu={proc.cpu_seconds:.1f}s")
            if proc.memory_rss_bytes:
                parts.append(f"mem={format_bytes_decimal(proc.memory_rss_bytes)}")
            proc_state = " ".join(parts)
        elapsed_detail = rec.detail
        if proc is not None and proc.elapsed_seconds is not None:
            elapsed_detail = f"{fmt_hms(proc.elapsed_seconds)} ({rec.detail})" if rec.detail else fmt_hms(proc.elapsed_seconds)
        rows.append([
            rec.name,
            rec.mode.upper(),
            status_str,
            pid_str,
            proc_state,
            rec.operation or "-",
            elapsed_detail,
        ])
    return render_table(
        headers=["Lock", "Mode", "Status", "PID", "Process", "Operation", "Detail"],
        rows=rows,
        alignments=["left", "left", "left", "right", "left", "left", "left"],
    )


def _lock(args: argparse.Namespace) -> int:
    from .library_guard import inspect_library_locks, unlock_library_locks
    from cross_platform.locks import LockRecord, ProcessStatus

    dest = args.destination.expanduser()
    if not dest.exists() or not dest.is_dir():
        raise ValueError(f"Lock target directory does not exist: {dest}")

    if getattr(args, "unlock", False):
        result = unlock_library_locks(dest)
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            rep = result["report"]
            print(styled("MangaDL Folder Lock Unlock", "cyan"))
            print(field("Target", result["target"]))
            if result["library_root"] != result["target"]:
                print(field("Library root", result["library_root"]))
            if result["unlocked"]:
                print(styled(f"Unlocked {len(result['unlocked'])} stale lock artifact(s):", "green"))
                for item in result["unlocked"]:
                    print(f"  - {item['name']}: {item['action']} ({item['path']})")
            else:
                print("No stale locks needed unlocking.")
            if result["refused_active"]:
                print(styled(f"Refused to unlock {len(result['refused_active'])} active lock(s) held by running process(es):", "red"))
                for item in result["refused_active"]:
                    pid = (item.get("process") or {}).get("pid") or (item.get("holder") or {}).get("pid") or "unknown"
                    print(f"  - {item['name']} ({item['mode'].upper()}): held by PID {pid} ({item.get('operation') or 'active'})")
            if rep.get("locks"):
                reconstructed = [
                    LockRecord(
                        **{
                            **lk,
                            "process": ProcessStatus(**lk["process"]) if lk.get("process") else None,
                        }
                    )
                    for lk in rep["locks"]
                ]
                print(_format_lock_table(reconstructed))
        return 1 if result["refused_active"] else 0

    report = inspect_library_locks(dest, auto_clean=True)
    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

    if report.write_locked:
        headline = styled("ENGAGED (WRITE LOCK)", "yellow")
    elif report.read_locked:
        headline = styled("ENGAGED (READ LOCK)", "cyan")
    elif report.stale_count > 0:
        headline = styled(f"UNLOCKED ({report.stale_count} STALE LOCK(S) DETECTED)", "red")
    else:
        headline = styled("UNLOCKED (IDLE)", "green")

    print(styled("MangaDL Folder Lock Status", "cyan"))
    print(field("Target", report.target))
    if report.library_root != report.target:
        print(field("Library root", report.library_root))
    print(field("State", headline))
    if report.auto_cleaned_count > 0:
        print(field("Auto-cleaned", f"{report.auto_cleaned_count} stale lock metadata record(s)"))
    if report.locks:
        print(_format_lock_table(report.locks))
    else:
        print("No lock files or active mangadl/compresser processes found for this folder.")
    if report.stale_count > 0:
        print(styled(f"Hint: run `mangadl lock -u -d \"{report.target}\"` to clear stale locks.", "yellow"))
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    shape = normalize_command_shape(raw_argv)
    parser = build_parser(raw_argv)
    args = parser.parse_args(list(shape.argv))
    if args.command == "compress" and not getattr(args, "operation", None):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction) and "compress" in action.choices:
                action.choices["compress"].print_help()
                return 0
    if args.command == "run":
        args.run_mode = shape.run_mode
        args.advanced_config = shape.advanced_config
    try:
        return {
            "run": _run,
            "inspect": _inspect,
            "status": _show_state,
            "retry": _retry,
            "kavita": lambda parsed: (
                _kavita_batch(parsed)
                if parsed.kavita_command.startswith("assign-")
                else _kavita_reconcile(parsed)
            ),
            "archive": _archive,
            "patch-hdporncomics": _patch_hdporncomics,
            "audit": _audit_destinations,
            "audit-destinations": _audit_destinations,
            "repair-loose": _repair_loose,
            "repair-pages": _repair_pages,
            "repair": _batch_repair,
            "partials": _partials,
            "auth": _auth,
            "favorites": _favorites,
            "compress": _compress,
            "lock": _lock,
        }[args.command](args)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 2
