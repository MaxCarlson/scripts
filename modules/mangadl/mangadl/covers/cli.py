from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from .kavita import parse_path_maps
from .service import process_url_folder


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-U",
        "--urls-folder",
        type=Path,
        required=True,
        help="Folder scanned recursively for every url*.txt file.",
    )
    parser.add_argument(
        "-d",
        "--destination",
        type=Path,
        action="append",
        required=True,
        help="Manga library root to match; repeatable.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-n", "--dry-run", action="store_true", help="Match and scrape without writing (default).")
    mode.add_argument("-f", "--apply", action="store_true", help="Download covers and write managed metadata.")
    parser.add_argument("-F", "--force", action="store_true", help="Refresh and preserve any existing managed cover.")
    parser.add_argument("-C", "--cookies", type=Path, help="Netscape/Mozilla cookies file.")
    parser.add_argument("-t", "--timeout", type=float, default=45.0, help="HTTP timeout in seconds (default: 45).")
    parser.add_argument("-k", "--kavita-url", help="Kavita base URL, such as http://192.168.50.100:5000.")
    parser.add_argument(
        "-E",
        "--kavita-api-key-env",
        default="KAVITA_API_KEY",
        help="Environment variable containing the Kavita Auth Key (default: KAVITA_API_KEY).",
    )
    parser.add_argument("-K", "--apply-kavita", action="store_true", help="Upload and lock matched covers in Kavita.")
    parser.add_argument(
        "-M",
        "--kavita-path-map",
        action="append",
        default=[],
        metavar="LOCAL=KAVITA",
        help="Translate local library paths to Kavita-visible paths; repeatable.",
    )
    parser.add_argument("-j", "--json", action="store_true", help="Emit the complete JSON report.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress per-URL progress on stderr.")


def run_cli(args: argparse.Namespace) -> int:
    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than zero")
    if args.force and not args.apply:
        raise ValueError("--force requires --apply")
    api_key = os.environ.get(args.kavita_api_key_env, "") if args.apply_kavita else None
    progress = None if args.quiet else lambda message: print(f"Covers: {message}", file=sys.stderr, flush=True)
    results, rejected, files = process_url_folder(
        args.urls_folder,
        args.destination,
        apply=bool(args.apply),
        force=bool(args.force),
        cookies=args.cookies.expanduser().resolve() if args.cookies else None,
        timeout=float(args.timeout),
        kavita_url=args.kavita_url,
        kavita_api_key=api_key,
        apply_kavita=bool(args.apply_kavita),
        kavita_path_maps=parse_path_maps(args.kavita_path_map),
        progress=progress,
    )
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    payload = {
        "mode": "apply" if args.apply else "dry-run",
        "urls_folder": str(args.urls_folder.expanduser().resolve()),
        "url_files": [str(path) for path in files],
        "destinations": [str(path.expanduser().resolve()) for path in args.destination],
        "counts": dict(sorted(counts.items())),
        "rejected": rejected,
        "results": [asdict(result) for result in results],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        summary = ", ".join(f"{name}={count}" for name, count in sorted(counts.items())) or "no URLs"
        print(f"Covers {payload['mode']}: {len(results)} URL(s), {summary}")
        for result in results:
            target = f" -> {result.folder}" if result.folder else ""
            detail = f" ({result.message})" if result.message else ""
            print(f"  {result.status.upper():16} {result.url}{target}{detail}")
    has_error = counts.get("failed", 0) or counts.get("ambiguous", 0) or counts.get("unsupported", 0)
    return 1 if has_error else 0
