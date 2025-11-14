#!/usr/bin/env python3
"""
URL file audit utilities for ytaedl.

Provides scanning helpers that can be reused programmatically as well as
an interactive/JSON/table CLI.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import re
import shutil
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

GBYTES = 1024 ** 3
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
TERMDASH_DEFAULT = "~/Repos/scripts/termdash"
DEFAULT_STARS_DIR = "files/downloads/stars"
DEFAULT_AE_DIR = "files/downloads/ae-stars"
DEFAULT_MEDIA_DIR = "stars"

INTERACTIVE_COLUMN_LAYOUT: List[Tuple[str, int, str]] = [
    ("Name", 18, "<"),
    ("Unique", 8, ">"),
    ("AE", 7, ">"),
    ("Stars", 7, ">"),
    ("MP4s", 6, ">"),
    ("Remain", 8, ">"),
    ("Ratio", 6, ">"),
    ("GB", 6, ">"),
]

SORT_CHOICES = ("remaining", "ratio", "name", "unique", "mp4", "ae", "stars")


@dataclass
class UrlEntry:
    name: str
    total_unique_urls: int
    ae_line_count: int
    ae_unique_urls: int
    stars_line_count: int
    stars_unique_urls: int
    mp4_count: int
    mp4_bytes: int
    mp4_files: List[str]
    remaining: int
    ratio: float
    ae_path: Optional[Path]
    stars_path: Optional[Path]
    media_path: Path


@dataclass
class ScanResult:
    entries: List[UrlEntry]
    totals: Dict[str, int]
    path_index: Dict[str, UrlEntry]


class Palette:
    RESET = "\033[0m"

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"{code}{text}{self.RESET}"

    def header(self, text: str) -> str:
        return self._wrap("\033[95m\033[1m", text)

    def name(self, text: str) -> str:
        return self._wrap("\033[96m\033[1m", text)

    def number(self, text: str) -> str:
        return self._wrap("\033[97m", text)

    def warn(self, text: str) -> str:
        return self._wrap("\033[91m\033[1m", text)

    def good(self, text: str) -> str:
        return self._wrap("\033[92m\033[1m", text)

    def muted(self, text: str) -> str:
        return self._wrap("\033[90m", text)


def normalize_path(raw: str) -> Path:
    trimmed = raw[1:] if raw.startswith("@") else raw
    return Path(trimmed).expanduser().resolve()


def gather_file_map(directory: Path, label: str) -> Dict[str, Path]:
    if not directory.exists():
        print(f"[WARN] {label} directory '{directory}' does not exist.", file=sys.stderr)
        return {}
    return {path.stem: path for path in directory.glob("*.txt") if path.is_file()}


def read_url_lines(path: Optional[Path]) -> List[str]:
    if path is None or not path.exists():
        return []
    urls: List[str] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            stripped = raw.strip()
            if stripped:
                urls.append(stripped)
    return urls


def mp4_inventory(folder: Path) -> Tuple[int, int, List[str]]:
    if not folder.exists() or not folder.is_dir():
        return 0, 0, []
    count = 0
    total_bytes = 0
    files: List[str] = []
    for child in folder.iterdir():
        if child.is_file() and child.suffix.lower() == ".mp4":
            count += 1
            try:
                total_bytes += child.stat().st_size
            except OSError:
                pass
            files.append(child.name)
    files.sort(key=str.lower)
    return count, total_bytes, files


def compute_ratio(remaining: int, downloaded: int) -> float:
    if downloaded == 0:
        return math.inf if remaining else 0.0
    return remaining / downloaded


def collect_entries(ae_dir: Path, stars_dir: Path, media_dir: Path) -> Tuple[List[UrlEntry], Dict[str, int]]:
    ae_map = gather_file_map(ae_dir, "AE URL")
    stars_map = gather_file_map(stars_dir, "Star URL")
    names = sorted(set(ae_map) | set(stars_map), key=lambda n: n.lower())
    totals = {
        "total_unique_urls": 0,
        "ae_url_lines": 0,
        "ae_unique_urls": 0,
        "stars_url_lines": 0,
        "stars_unique_urls": 0,
        "downloaded_mp4s": 0,
        "downloaded_bytes": 0,
        "remaining": 0,
    }
    entries: List[UrlEntry] = []
    for name in names:
        ae_path = ae_map.get(name)
        stars_path = stars_map.get(name)
        media_path = media_dir / name
        ae_lines = read_url_lines(ae_path)
        stars_lines = read_url_lines(stars_path)
        ae_unique = set(ae_lines)
        stars_unique = set(stars_lines)
        combined_unique = ae_unique | stars_unique
        mp4_count, mp4_bytes, mp4_files = mp4_inventory(media_path)
        total_unique = len(combined_unique)
        remaining = max(total_unique - mp4_count, 0)
        entry = UrlEntry(
            name=name,
            total_unique_urls=total_unique,
            ae_line_count=len(ae_lines),
            ae_unique_urls=len(ae_unique),
            stars_line_count=len(stars_lines),
            stars_unique_urls=len(stars_unique),
            mp4_count=mp4_count,
            mp4_bytes=mp4_bytes,
            mp4_files=mp4_files,
            remaining=remaining,
            ratio=compute_ratio(remaining, mp4_count),
            ae_path=ae_path,
            stars_path=stars_path,
            media_path=media_path,
        )
        entries.append(entry)
        totals["total_unique_urls"] += total_unique
        totals["ae_url_lines"] += len(ae_lines)
        totals["ae_unique_urls"] += len(ae_unique)
        totals["stars_url_lines"] += len(stars_lines)
        totals["stars_unique_urls"] += len(stars_unique)
        totals["downloaded_mp4s"] += mp4_count
        totals["downloaded_bytes"] += mp4_bytes
        totals["remaining"] += remaining
    return entries, totals


def scan_url_stats(stars_dir: Path, ae_dir: Path, media_dir: Path) -> ScanResult:
    entries, totals = collect_entries(ae_dir, stars_dir, media_dir)
    path_index: Dict[str, UrlEntry] = {}
    for entry in entries:
        for path in (entry.ae_path, entry.stars_path):
            if path:
                path_index[str(path.resolve())] = entry
    return ScanResult(entries=entries, totals=totals, path_index=path_index)


def sort_entries(entries: List[UrlEntry], key: str, ascending: bool) -> List[UrlEntry]:
    def key_func(entry: UrlEntry):
        if key == "ratio":
            return math.inf if math.isinf(entry.ratio) else entry.ratio
        if key == "remaining":
            return entry.remaining
        if key == "unique":
            return entry.total_unique_urls
        if key == "mp4":
            return entry.mp4_count
        if key == "ae":
            return entry.ae_line_count
        if key == "stars":
            return entry.stars_line_count
        return entry.name.lower()

    return sorted(entries, key=key_func, reverse=not ascending)


def compute_rankings(entries: List[UrlEntry], ascending: bool, key: str) -> Tuple[List[Path], Dict[str, int]]:
    ordered_entries = sort_entries(entries, key, ascending)
    ordered_paths: List[Path] = []
    ranks: Dict[str, int] = {}
    for entry in ordered_entries:
        for path in [entry.stars_path, entry.ae_path]:
            if not path:
                continue
            resolved = str(path.resolve())
            if resolved in ranks:
                continue
            ranks[resolved] = len(ordered_paths)
            ordered_paths.append(path.resolve())
    return ordered_paths, ranks


def format_int(value: int) -> str:
    return f"{value:,}"


def format_ratio(value: float) -> str:
    return "∞" if math.isinf(value) else f"{value:.2f}"


def build_summary_line(totals: Dict[str, int]) -> str:
    gb_total = totals["downloaded_bytes"] / GBYTES if totals["downloaded_bytes"] else 0.0
    return (
        f"Downloaded MP4s: {format_int(totals['downloaded_mp4s'])} "
        f"({gb_total:.2f} GB) | "
        f"Total unique URLs: {format_int(totals['total_unique_urls'])} | "
        f"Remaining: {format_int(totals['remaining'])}"
    )


def build_table(entries: List[UrlEntry], palette: Palette) -> str:
    headers = [
        palette.header("Name"),
        palette.header("Unique URLs"),
        palette.header("AE URLs"),
        palette.header("Stars Unique"),
        palette.header("MP4s"),
        palette.header("Remaining"),
        palette.header("Remain/Done"),
    ]
    rows: List[List[str]] = [headers]
    for entry in entries:
        remaining_str = format_int(entry.remaining)
        if entry.remaining:
            remaining_str = palette.warn(remaining_str)
        else:
            remaining_str = palette.good(remaining_str)
        ratio_text = format_ratio(entry.ratio)
        if math.isinf(entry.ratio):
            ratio_str = palette.warn(ratio_text)
        elif entry.ratio == 0:
            ratio_str = palette.good(ratio_text)
        else:
            ratio_str = palette.number(ratio_text)

        rows.append([
            palette.name(entry.name),
            palette.number(format_int(entry.total_unique_urls)),
            palette.number(format_int(entry.ae_line_count)),
            palette.number(format_int(entry.stars_unique_urls)),
            palette.number(format_int(entry.mp4_count)),
            remaining_str,
            ratio_str,
        ])
    widths = [max(len(strip_ansi(row[i])) for row in rows) for i in range(len(headers))]
    lines = [
        "  ".join(pad_cell(row[idx], widths[idx]) for idx in range(len(headers)))
        for row in rows
    ]
    return "\n".join(lines)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def pad_cell(text: str, width: int) -> str:
    padding = width - len(strip_ansi(text))
    return text + (" " * padding if padding > 0 else "")


def build_json(entries: List[UrlEntry], totals: Dict[str, int], settings: argparse.Namespace) -> str:
    payload = {
        "settings": {
            "stars_dir": str(settings.stars_dir),
            "ae_dir": str(settings.ae_dir),
            "media_dir": str(settings.media_dir),
            "sort_key": settings.sort_key,
            "ascending": settings.ascending,
        },
        "entries": [
            {
                "name": entry.name,
                "total_unique_urls": entry.total_unique_urls,
                "ae_url_lines": entry.ae_line_count,
                "ae_unique_urls": entry.ae_unique_urls,
                "stars_url_lines": entry.stars_line_count,
                "stars_unique_urls": entry.stars_unique_urls,
                "downloaded_mp4s": entry.mp4_count,
                "downloaded_bytes": entry.mp4_bytes,
                "downloaded_gb": entry.mp4_bytes / GBYTES,
                "mp4_files": entry.mp4_files,
                "remaining": entry.remaining,
                "remaining_ratio": None if math.isinf(entry.ratio) else entry.ratio,
                "ae_file": str(entry.ae_path) if entry.ae_path else None,
                "stars_file": str(entry.stars_path) if entry.stars_path else None,
                "media_folder": str(entry.media_path),
            }
            for entry in entries
        ],
        "totals": {
            "total_unique_urls": totals["total_unique_urls"],
            "ae_url_lines": totals["ae_url_lines"],
            "ae_unique_urls": totals["ae_unique_urls"],
            "stars_url_lines": totals["stars_url_lines"],
            "stars_unique_urls": totals["stars_unique_urls"],
            "downloaded_mp4s": totals["downloaded_mp4s"],
            "downloaded_bytes": totals["downloaded_bytes"],
            "downloaded_gb": totals["downloaded_bytes"] / GBYTES,
            "remaining": totals["remaining"],
        },
    }
    return json.dumps(payload, indent=2)


def _truncate_column(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _format_interactive_columns(values: List[str]) -> str:
    segments: List[str] = []
    for (_, width, align), value in zip(INTERACTIVE_COLUMN_LAYOUT, values):
        truncated = _truncate_column(str(value), width)
        fmt = f"{{:{align}{width}}}"
        segments.append(fmt.format(truncated))
    return " ".join(segments)


def _iter_termdash_candidates(hint: Optional[Path]) -> List[Path]:
    candidates: List[Path] = []
    if hint:
        candidates.append(hint)
    script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir)
    return candidates


def _maybe_add_termdash_path(path: Path) -> bool:
    if not path:
        return False
    candidate = path
    if not candidate.exists():
        return False
    if candidate.is_file():
        candidate = candidate.parent
    package_parent: Optional[Path] = None
    if candidate.name == "termdash" and (candidate / "__init__.py").exists():
        package_parent = candidate.parent
    else:
        nested = candidate / "termdash"
        if (nested / "__init__.py").exists():
            package_parent = candidate
    if not package_parent:
        return False
    candidate_str = str(package_parent)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)
    return True


def load_interactive_components(termdash_hint: Optional[Path]):
    module_name = "termdash.interactive_list"
    last_error: Optional[ImportError] = None
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        last_error = exc
        for candidate in _iter_termdash_candidates(termdash_hint):
            if _maybe_add_termdash_path(candidate):
                try:
                    module = importlib.import_module(module_name)
                    break
                except ImportError as inner_exc:
                    last_error = inner_exc
                    continue
        else:
            raise ImportError(
                "Interactive mode requires the 'termdash' module. "
                "Provide --termdash-path or install the package, or use --non-interactive."
            ) from last_error
    return module.InteractiveList, module.DetailEntry, module.DetailViewData


def _interactive_filter(entry: UrlEntry, pattern: str) -> bool:
    needle = pattern.strip().lower()
    if not needle:
        return True
    haystack = entry.name.lower()
    return fnmatch(haystack, needle) or needle in haystack


def run_interactive_ui(entries: List[UrlEntry], totals: Dict[str, int], args: argparse.Namespace,
                       termdash_hint: Optional[Path]) -> bool:
    try:
        InteractiveList, DetailEntry, DetailViewData = load_interactive_components(termdash_hint)
    except ImportError as exc:
        print(f"[WARN] {exc}", file=sys.stderr)
        return False

    columns_line = _format_interactive_columns([name for name, _, _ in INTERACTIVE_COLUMN_LAYOUT])

    def formatter(item: UrlEntry, sort_field: str, width: int, show_date: bool,
                  show_time: bool, scroll_offset: int) -> str:
        values = [
            item.name,
            format_int(item.total_unique_urls),
            format_int(item.ae_line_count),
            format_int(item.stars_unique_urls),
            format_int(item.mp4_count),
            format_int(item.remaining),
            format_ratio(item.ratio),
            f"{item.mp4_bytes / GBYTES:.2f}",
        ]
        line = _format_interactive_columns(values)
        if width > 0:
            max_scroll = max(0, len(line) - width)
            offset = min(scroll_offset, max_scroll)
            if offset:
                line = line[offset:]
            return line[:width].ljust(width)
        if scroll_offset:
            line = line[scroll_offset:]
        return line

    def detail_formatter(item: UrlEntry):
        completion_pct = (item.mp4_count / item.total_unique_urls * 100) if item.total_unique_urls else 0.0
        backlog_pct = (item.remaining / item.total_unique_urls * 100) if item.total_unique_urls else 0.0
        backlog_share = (item.remaining / totals["remaining"] * 100) if totals["remaining"] else 0.0
        overview_lines = [
            f"Unique URLs: {format_int(item.total_unique_urls)}",
            f"AE lines/unique: {format_int(item.ae_line_count)} / {format_int(item.ae_unique_urls)}",
            f"Stars lines/unique: {format_int(item.stars_line_count)} / {format_int(item.stars_unique_urls)}",
            f"MP4 files: {format_int(item.mp4_count)} ({completion_pct:.1f}% complete)",
            f"Remaining: {format_int(item.remaining)} ({backlog_pct:.1f}% of this list, {backlog_share:.1f}% of backlog)",
            f"Remain/download ratio: {format_ratio(item.ratio)}",
            f"Downloaded size: {item.mp4_bytes / GBYTES:.2f} GB",
        ]
        if item.ae_line_count != item.ae_unique_urls:
            overview_lines.append(
                f"AE duplicates: {format_int(item.ae_line_count - item.ae_unique_urls)}"
            )
        if item.stars_line_count != item.stars_unique_urls:
            overview_lines.append(
                f"Stars duplicates: {format_int(item.stars_line_count - item.stars_unique_urls)}"
            )
        source_lines = [
            f"AE URL file: {item.ae_path or '—'}",
            f"Stars URL file: {item.stars_path or '—'}",
            f"Media folder: {item.media_path}",
        ]
        mp4_body = item.mp4_files or ["(no MP4 files found)"]
        return DetailViewData(
            title=f"{item.name} stats",
            entries=[
                DetailEntry(summary="Overview", body=overview_lines, expanded=True),
                DetailEntry(summary="Paths", body=source_lines, expanded=True),
                DetailEntry(summary="MP4 files", body=mp4_body, expanded=bool(item.mp4_files)),
            ],
            footer="Enter: toggle | g/G: start/end | Esc/q: back | f/x: filter list",
        )

    sorters: Dict[str, Callable[[UrlEntry], object]] = {
        "name": lambda e: e.name.lower(),
        "total_unique_urls": lambda e: e.total_unique_urls,
        "ae_line_count": lambda e: e.ae_line_count,
        "stars_unique_urls": lambda e: e.stars_unique_urls,
        "mp4_count": lambda e: e.mp4_count,
        "remaining": lambda e: e.remaining,
        "ratio": lambda e: math.inf if math.isinf(e.ratio) else e.ratio,
        "mp4_bytes": lambda e: e.mp4_bytes,
    }
    initial_sort = args.sort_key if args.sort_key in sorters else "remaining"
    sort_keys_mapping = {
        ord("n"): "name",
        ord("u"): "total_unique_urls",
        ord("a"): "ae_line_count",
        ord("s"): "stars_unique_urls",
        ord("m"): "mp4_count",
        ord("r"): "remaining",
        ord("p"): "ratio",
        ord("g"): "mp4_bytes",
    }
    footer_lines = [
        "↑↓/PgUp/PgDn: move | Enter: details | f/x: filter/exclude | Ctrl+Q/q: quit",
        "Sort keys n/u/a/s/m/r/p/g (repeat to flip order)",
    ]
    list_view = InteractiveList(
        items=list(entries),
        sorters=sorters,
        formatter=formatter,
        filter_func=_interactive_filter,
        initial_sort=initial_sort,
        initial_order="asc" if args.ascending else "desc",
        header="Star Download Audit",
        sort_keys_mapping=sort_keys_mapping,
        footer_lines=footer_lines,
        detail_formatter=detail_formatter,
        size_extractor=lambda entry: entry.mp4_bytes,
        enable_color_gradient=True,
        columns_line=columns_line,
    )
    try:
        list_view.run()
        return True
    except SystemExit as exc:
        if exc.code == 2:
            print(
                "Interactive UI unavailable (TTY/terminfo issue). Falling back to static output.",
                file=sys.stderr,
            )
            return False
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytaedl urls",
        description="Summarize URL files vs downloaded MP4s.",
    )
    parser.add_argument("-s", "--stars-dir", default=DEFAULT_STARS_DIR,
                        help="Directory containing primary star URL files")
    parser.add_argument("-a", "--ae-dir", default=DEFAULT_AE_DIR,
                        help="Directory containing AE star URL files")
    parser.add_argument("-m", "--media-dir", default=DEFAULT_MEDIA_DIR,
                        help="Directory containing per-star folders with MP4 files")
    parser.add_argument("-k", "--sort-key", choices=SORT_CHOICES,
                        default="remaining", help="Sort by remaining, ratio, name, unique, mp4, ae, or stars")
    parser.add_argument("-A", "--ascending", action="store_true",
                        help="Sort ascending instead of descending")
    parser.add_argument("-j", "--json", action="store_true",
                        help="Emit JSON instead of pretty table")
    parser.add_argument("-J", "--json-file", help="Optional path to write JSON output")
    parser.add_argument("-n", "--no-color", action="store_true",
                        help="Disable colored pretty output")
    parser.add_argument("-N", "--non-interactive", action="store_true",
                        help="Skip the interactive TUI and print the static table")
    parser.add_argument("-T", "--termdash-path", default=TERMDASH_DEFAULT,
                        help="Path to the termdash module")
    return parser


def cli_main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    stars_dir = normalize_path(args.stars_dir)
    ae_dir = normalize_path(args.ae_dir)
    media_dir = normalize_path(args.media_dir)

    scan = scan_url_stats(stars_dir, ae_dir, media_dir)
    if not scan.entries:
        print("No URL files were found in the provided directories.", file=sys.stderr)
        return 1

    sorted_entries = sort_entries(scan.entries, args.sort_key, args.ascending)

    json_blob: Optional[str] = None
    if args.json or args.json_file:
        json_blob = build_json(sorted_entries, scan.totals, args)
        if args.json_file:
            json_path = normalize_path(args.json_file)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json_blob, encoding="utf-8")
        if args.json:
            print(json_blob)
            if args.non_interactive:
                return 0

    palette = Palette(enabled=not args.no_color and sys.stdout.isatty())
    termdash_hint = normalize_path(args.termdash_path) if args.termdash_path else None
    interactive_used = False
    wants_interactive = not args.non_interactive and not args.json
    if wants_interactive:
        if sys.stdin.isatty() and sys.stdout.isatty():
            interactive_used = run_interactive_ui(sorted_entries, scan.totals, args, termdash_hint)
        else:
            print(
                "Interactive UI requires a TTY. Falling back to static table output.",
                file=sys.stderr,
            )
    if interactive_used:
        print()
        print(build_summary_line(scan.totals))
        return 0

    table = build_table(sorted_entries, palette)
    print(table)
    print()
    summary = build_summary_line(scan.totals)
    print(palette.muted(summary) if palette.enabled else summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
