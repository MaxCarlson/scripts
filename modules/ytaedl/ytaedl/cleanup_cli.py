"""
ytaedl cleanup — maintenance subcommand.

Usage
-----
  ytaedl cleanup partial [options]   Delete stale _partial/ directories
  ytaedl cleanup index   [options]   Rebuild the domain URL index

Run ``ytaedl cleanup <operation> --help`` for per-operation options.

Examples
--------
  # Preview stale partial dirs without deleting:
  ytaedl cleanup partial -P B:\\stars\\ --dry-run

  # Delete stale partial dirs and remove stale archive entries:
  ytaedl cleanup partial -P B:\\stars\\ -a ./logs/archive

  # Rebuild the domain index from URL files:
  ytaedl cleanup index -s ./files/downloads/stars -d ./files/downloads/ae-stars

  # Show what the domain index would contain (dry-run):
  ytaedl cleanup index -s ./files/downloads/stars --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__ as YTAEDL_VERSION
from . import _partial_utils
from .domain_index import DomainIndex


# ---------------------------------------------------------------------------
# Top-level help
# ---------------------------------------------------------------------------

_OPERATIONS = {
    "partial": "Delete stale _partial/ directories and remove archive entries",
    "index": "Rebuild (or inspect) the domain URL index from URL files",
}

_TOP_EPILOG = textwrap.dedent("""\
    Operations:
      partial    Delete stale _partial/ directories and remove archive entries
      index      Rebuild the domain URL index from URL files

    Examples:
      ytaedl cleanup partial -P B:\\stars\\ --dry-run
      ytaedl cleanup partial -P B:\\stars\\
      ytaedl cleanup index --stars-dir ./files/downloads/stars

    Run 'ytaedl cleanup <operation> --help' for full option list.
""")


def _print_top_help(prog: str = "ytaedl cleanup") -> None:
    lines = [
        f"ytaedl {YTAEDL_VERSION}",
        "",
        f"usage: {prog} <operation> [options]",
        "",
        "Maintenance operations — no downloads are started.",
        "",
        _TOP_EPILOG.rstrip(),
    ]
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# ytaedl cleanup partial
# ---------------------------------------------------------------------------

def _make_partial_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ytaedl cleanup partial",
        description=(
            f"ytaedl {YTAEDL_VERSION} - scan proxy staging directories for stale _partial/ download "
            "working dirs, print a deletion summary (in red), require the "
            "user to type DELETE to confirm, then delete them.  Optionally "
            "removes the corresponding archive entries so those URLs are "
            "retried on the next run."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              ytaedl cleanup partial -P B:\\stars\\ --dry-run
              ytaedl cleanup partial -P B:\\stars\\
              ytaedl cleanup partial -P B:\\stars\\ -a ./logs/archive
        """),
    )
    p.add_argument(
        "-P", "--proxy-root",
        required=True,
        help="Proxy staging root directory (e.g. B:\\stars\\). Scans all "
             "channel subdirectories inside it for _partial/ dirs.",
    )
    p.add_argument(
        "-a", "--archive-dir",
        default=None,
        help="Archive directory. When provided, archive entries for deleted "
             "URLs are removed so those URLs will be retried on the next run.",
    )
    p.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Print the deletion summary but do not delete anything.",
    )
    return p


def _run_partial_cleanup(args: argparse.Namespace) -> int:
    proxy_root = Path(args.proxy_root).expanduser().resolve()
    archive_dir = Path(args.archive_dir).expanduser().resolve() if args.archive_dir else None

    result = _partial_utils.cleanup_partial_dirs(
        proxy_root,
        archive_dir=archive_dir,
        dry_run=args.dry_run,
        require_confirm=True,
    )
    return 0


# ---------------------------------------------------------------------------
# ytaedl cleanup index
# ---------------------------------------------------------------------------

def _make_index_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ytaedl cleanup index",
        description=(
            f"ytaedl {YTAEDL_VERSION} - rebuild the domain URL index from the URL files in --stars-dir "
            "and --aebn-dir, then print a summary.  Does not start any "
            "download workers.  Use --dry-run to inspect what the index would "
            "contain without writing it to disk."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              ytaedl cleanup index -s ./files/downloads/stars
              ytaedl cleanup index -s ./files/downloads/stars -d ./files/downloads/ae-stars
              ytaedl cleanup index -H ./logs/domain_index.json --dry-run
        """),
    )
    p.add_argument(
        "-s", "--stars-dir",
        default=os.environ.get("STARS_DIR", "./files/downloads/stars"),
        help="Directory of yt-dlp URL files ($STARS_DIR).",
    )
    p.add_argument(
        "-d", "--aebn-dir",
        default=os.environ.get("AESTARS_DIR", "./files/downloads/ae-stars"),
        help="Directory of AEBN URL files ($AESTARS_DIR).",
    )
    p.add_argument(
        "-H", "--domain-index-path",
        default=None,
        help="Path to the domain index JSON file.  When omitted and --log-dir "
             "is set, defaults to <log-dir>/domain_index.json.",
    )
    p.add_argument(
        "-g", "--log-dir",
        default="./logs",
        help="Log directory used to resolve the default domain index path.",
    )
    p.add_argument(
        "-a", "--archive-dir",
        default=None,
        help="Archive directory used to seed the index with already-finished URLs.",
    )
    p.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Build the index in memory and print the summary, but do not "
             "write or overwrite the index file.",
    )
    return p


def _run_index_rebuild(args: argparse.Namespace) -> int:
    stars_dir = Path(args.stars_dir).expanduser().resolve()
    aebn_dir = Path(args.aebn_dir).expanduser().resolve()
    log_dir = Path(args.log_dir).expanduser().resolve()

    if args.domain_index_path:
        index_path = Path(args.domain_index_path).expanduser().resolve()
    elif archive_dir:
        index_path = archive_dir / "domain_index.json"
    else:
        index_path = log_dir / "domain_index.json"

    archive_dir = Path(args.archive_dir).expanduser().resolve() if args.archive_dir else None

    # Collect URL files
    url_files: List[Path] = []
    for root in (stars_dir, aebn_dir):
        if root.exists():
            url_files.extend(sorted(root.rglob("*.txt")))

    if not url_files:
        print(
            f"[WARN] No URL files found in {stars_dir} or {aebn_dir}.",
            file=sys.stderr,
        )
        return 1

    # Load finished URLs from archive (optional)
    finished_urls: dict[str, str] = {}
    if archive_dir and archive_dir.exists():
        try:
            # Reuse the same archive-reading logic as the manager
            from .manager import _load_archive_finished_urls
            finished_urls = _load_archive_finished_urls(archive_dir)
            if finished_urls:
                print(f"[INDEX] Seeding from archive: {len(finished_urls)} finished URL(s)")
        except Exception as exc:
            print(f"[WARN] Could not read archive: {exc}", file=sys.stderr)

    print(f"[INDEX] Building from {len(url_files)} URL file(s)…")

    def _progress(msg: str) -> None:
        print(f"  {msg}")

    domain_index = DomainIndex.build(
        url_files,
        finished_urls=finished_urls if finished_urls else None,
        progress_cb=_progress,
    )

    print(f"[INDEX] {domain_index.summary_line()}")

    if args.dry_run:
        print("[INDEX] --dry-run: index not written to disk.")
        return 0

    index_path.parent.mkdir(parents=True, exist_ok=True)
    domain_index.save(index_path)
    print(f"[INDEX] Saved to {index_path}")
    return 0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for ``ytaedl cleanup``."""
    argv_list = list(argv) if argv is not None else sys.argv[1:]

    if not argv_list or argv_list[0] in ("-h", "--help"):
        _print_top_help()
        return 0

    operation = argv_list[0]
    rest = argv_list[1:]

    if operation == "partial":
        parser = _make_partial_parser()
        args = parser.parse_args(rest)
        return _run_partial_cleanup(args)

    if operation == "index":
        parser = _make_index_parser()
        args = parser.parse_args(rest)
        return _run_index_rebuild(args)

    print(f"ytaedl cleanup: unknown operation '{operation}'", file=sys.stderr)
    print("Run 'ytaedl cleanup --help' for available operations.", file=sys.stderr)
    return 2
