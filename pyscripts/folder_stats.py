#!/usr/bin/env python3
# folder_stats.py
# Totals space by file extension under a target directory (cross-platform, pwsh7 friendly).

import argparse
import sys
import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Iterable, Tuple, Set

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

# ---------------------------- CLI --------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan a directory and report file-type statistics."
    )
    parser.add_argument("directory", metavar="DIR", help="Target directory to scan")
    parser.add_argument("-d", "--depth", metavar="N", type=int, default=-1,
                        help="Max recursion depth (-1 = infinite)")
    parser.add_argument("-t", "--tree", action="store_true",
                        help="Print stats per-subdirectory (indented) instead of aggregate")
    parser.add_argument("-a", "--auto-units", action="store_true",
                        help="Auto-select best size unit (KB/MB/GB/TB). Default shows MB")
    parser.add_argument("--dates", choices=["atime", "mtime", "ctime"], default=None,
                        help="Include oldest/newest access/modify/create dates per category")
    parser.add_argument("-x", "--exclude", action="append", default=[],
                        help="Glob(s) to exclude (match against file or folder name). Repeatable.")
    parser.add_argument("-s", "--sort", choices=["size", "count", "ext"], default="size",
                        help="Sort extension rows by total size, file count, or extension (default: size)")
    parser.add_argument("-r", "--reverse", action="store_true", help="Reverse sort order")
    parser.add_argument("--follow-symlinks", action="store_true",
                        help="Follow symlinks (default: do not follow). Symlinks counted as [symlink].")
    # Hotspots mode
    parser.add_argument("-E", "--ext", action="append", default=[],
                        help="Focus on these extensions for hotspot analysis. "
                             "Comma-separated or repeat (-E jpg -E png).")
    parser.add_argument("-H", "--hotspots", type=int, default=0,
                        help="Show top N folders by size within focused extensions (or all if none).")
    parser.add_argument("--hotspots-sort", choices=["size", "count"], default="size",
                        help="Rank hotspots by size or by file count (default: size)")
    return parser.parse_args()


# ---------------------------- Helpers ----------------------------------------

def humanize_size(bytes_size: int) -> str:
    size = float(bytes_size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.2f}{unit}"
        size /= 1024.0
    return f"{size:.2f}TB"

def to_mb(bytes_size: int) -> float:
    return bytes_size / (1024 * 1024)

def _should_exclude(name: str, patterns: Iterable[str]) -> bool:
    if not patterns:
        return False
    import fnmatch
    for pat in patterns:
        if fnmatch.fnmatch(name, pat):
            return True
    return False

def _normalize_exts(exts: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    for e in exts:
        if not e:
            continue
        for part in str(e).split(","):
            p = part.strip().lower()
            if not p:
                continue
            if not p.startswith("."):
                p = "." + p
            out.add(p)
    return out


# ---------------------------- Core stats (by extension) -----------------------

def _empty_row() -> Dict[str, Any]:
    return {
        "count": 0,
        "total": 0,
        "atime_min": None, "atime_max": None,
        "mtime_min": None, "mtime_max": None,
        "ctime_min": None, "ctime_max": None,
    }

def _merge_into(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    dst["count"] += src["count"]
    dst["total"] += src["total"]
    for key in ("atime", "mtime", "ctime"):
        mn, mx = f"{key}_min", f"{key}_max"
        if src[mn] is not None:
            dst[mn] = src[mn] if dst[mn] is None else min(dst[mn], src[mn])
            dst[mx] = src[mx] if dst[mx] is None else max(dst[mx], src[mx])

def _file_stat(path_like: Path, follow_symlinks: bool):
    """Use Path.stat so tests can monkeypatch it. Avoid following symlinks unless asked."""
    try:
        return path_like.stat() if follow_symlinks else path_like.stat(follow_symlinks=False)
    except Exception:
        return None

def gather_stats(
    path: Path,
    maxdepth: int,
    current_depth: int = 0,
    *,
    exclude: Iterable[str] = (),
    follow_symlinks: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Walk 'path' up to 'maxdepth' and accumulate stats by file extension (lowercased).
    Symlinks are categorized as [symlink] unless follow_symlinks=True.
    """
    stats: Dict[str, Dict[str, Any]] = {}

    try:
        with os.scandir(path) as it:
            entries = list(it)
    except (FileNotFoundError, PermissionError):
        return stats

    for entry in entries:
        name = entry.name
        if _should_exclude(name, exclude):
            # Apply to both files and directories
            continue
        entry_path = Path(entry.path)

        try:
            if entry.is_symlink():
                if not follow_symlinks:
                    row = stats.setdefault("[symlink]", _empty_row())
                    row["count"] += 1
                    continue

            if entry.is_file(follow_symlinks=follow_symlinks):
                info = _file_stat(entry_path, follow_symlinks)
                if info is None:
                    continue
                ext = entry_path.suffix.lower() or "[no extension]"
                row = stats.setdefault(ext, _empty_row())
                row["count"] += 1
                row["total"] += int(info.st_size)
                for key, stamp in (("atime", info.st_atime),
                                   ("mtime", info.st_mtime),
                                   ("ctime", info.st_ctime)):
                    mn = f"{key}_min"; mx = f"{key}_max"
                    if row[mn] is None or stamp < row[mn]:
                        row[mn] = stamp
                    if row[mx] is None or stamp > row[mx]:
                        row[mx] = stamp
                continue

            if entry.is_dir(follow_symlinks=follow_symlinks) and (maxdepth < 0 or current_depth < maxdepth):
                child = gather_stats(
                    entry_path, maxdepth, current_depth + 1,
                    exclude=exclude, follow_symlinks=follow_symlinks
                )
                for ext, data in child.items():
                    _merge_into(stats.setdefault(ext, _empty_row()), data)

        except (PermissionError, FileNotFoundError):
            continue

    # Only compute hardlinks once at root depth
    if current_depth == 0:
        hard = 0
        visited: Set[Tuple[int, int]] = set()
        for p in path.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    st = _file_stat(p, follow_symlinks)
                    if st and getattr(st, "st_nlink", 1) > 1:
                        key = (getattr(st, "st_ino", 0), getattr(st, "st_dev", 0))
                        if key not in visited:
                            visited.add(key)
                            hard += 1
            except Exception:
                pass
        if hard:
            row = stats.setdefault("[hardlink]", _empty_row())
            row["count"] = hard
    return stats


def find_max_depth(root: Path) -> int:
    maxd = 0
    for p in root.rglob("*"):
        try:
            if p.is_dir():
                depth = len(p.relative_to(root).parts)
                if depth > maxd:
                    maxd = depth
        except Exception:
            continue
    return maxd


# ---------------------------- Directory “hotspots” ----------------------------

def gather_dir_totals(
    path: Path,
    maxdepth: int,
    current_depth: int = 0,
    *,
    focus_exts: Optional[Set[str]] = None,
    exclude: Iterable[str] = (),
    follow_symlinks: bool = False,
) -> Tuple[Dict[Path, Dict[str, int]], int, int]:
    """
    Recursively aggregate totals per directory.
    Returns (dir_map, total_count, total_bytes) where dir_map[path] = {'count','total'}.
    If 'focus_exts' is provided, only files with those extensions are included.
    """
    dir_map: Dict[Path, Dict[str, int]] = {}
    files_count = 0
    bytes_total = 0

    try:
        with os.scandir(path) as it:
            entries = list(it)
    except (FileNotFoundError, PermissionError):
        return dir_map, 0, 0

    for entry in entries:
        name = entry.name
        if _should_exclude(name, exclude):
            continue
        p = Path(entry.path)

        try:
            if entry.is_file(follow_symlinks=follow_symlinks):
                ext = p.suffix.lower()
                if focus_exts and ext not in focus_exts:
                    continue
                st = _file_stat(p, follow_symlinks)
                if st is None:
                    continue
                files_count += 1
                bytes_total += int(st.st_size)
            elif entry.is_dir(follow_symlinks=follow_symlinks) and (maxdepth < 0 or current_depth < maxdepth):
                sub_map, c, b = gather_dir_totals(
                    p, maxdepth, current_depth + 1,
                    focus_exts=focus_exts, exclude=exclude, follow_symlinks=follow_symlinks
                )
                # merge child map
                for k, v in sub_map.items():
                    acc = dir_map.setdefault(k, {"count": 0, "total": 0})
                    acc["count"] += v["count"]
                    acc["total"] += v["total"]
                files_count += c
                bytes_total += b
        except (PermissionError, FileNotFoundError):
            continue

    # add current directory aggregate
    dir_map[path] = {"count": files_count, "total": bytes_total}
    return dir_map, files_count, bytes_total


# ---------------------------- Presentation -----------------------------------

def _format_size(bytes_size: int, auto_units: bool) -> str:
    return humanize_size(bytes_size) if auto_units else f"{to_mb(bytes_size):.2f}MB"

def _auto_compact(width: int, want_dates: Optional[str]) -> Tuple[bool, bool]:
    """
    Decide whether to hide [% of total] and [date] columns.
    IMPORTANT: If dates are requested, we ALWAYS show them (tests expect this),
    while % may still be hidden on very narrow terminals.
    """
    show_dates = bool(want_dates)  # always show when requested
    show_pct = width >= 70
    return show_pct, show_dates

def _auto_compact_hotspots(width: int) -> Tuple[bool, bool]:
    """Decide whether to show % and a simple bar for hotspots table."""
    show_pct = width >= 70
    show_bar = width >= 85
    return show_pct, show_bar

def print_stats(
    stats: Dict[str, Dict[str, Any]],
    indent: int = 0,
    dir_name: Optional[str] = None,
    args: argparse.Namespace = None,
    header_note: Optional[str] = None,
):
    pad = "    " * indent
    if header_note:
        console.print(f"{pad}[bold yellow]{header_note}[/]")
    if dir_name:
        console.print(f"{pad}[bold underline]{dir_name}[/]")

    total_bytes = sum(d["total"] for d in stats.values())
    # Sorting
    if args.sort == "size":
        sortkey = lambda kv: kv[1]["total"]
    elif args.sort == "count":
        sortkey = lambda kv: kv[1]["count"]
    else:
        sortkey = lambda kv: kv[0]
    rows_sorted = sorted(
        stats.items(), key=sortkey,
        reverse=(not args.reverse if args.sort in ("size", "count") else args.reverse)
    )

    width = shutil.get_terminal_size((100, 24)).columns
    show_pct, show_dates = _auto_compact(width, getattr(args, "dates", None))

    table = Table(box=box.SIMPLE, expand=True, show_header=True, header_style="bold cyan")
    table.add_column("Extension", style="white", no_wrap=True, overflow="ellipsis", min_width=8, max_width=24)
    table.add_column("Count", justify="right", no_wrap=True, min_width=5)
    table.add_column("Size", justify="right", no_wrap=True, min_width=9)
    if show_pct:
        table.add_column("% of total", justify="right", no_wrap=True, min_width=7)
    if show_dates:
        table.add_column("Oldest", justify="right", no_wrap=True, min_width=16)
        table.add_column("Newest", justify="right", no_wrap=True, min_width=16)

    for ext, d in rows_sorted:
        count = d["count"]
        size_bytes = d["total"]
        size = _format_size(size_bytes, getattr(args, "auto_units", False))
        row = [ext, str(count), size]
        if show_pct:
            pct = f"{(size_bytes / total_bytes * 100.0):.1f}%" if total_bytes > 0 else "0.0%"
            row.append(pct)
        if show_dates:
            dates_key = getattr(args, "dates", None)
            mn = d.get(f"{dates_key}_min") if dates_key else None
            mx = d.get(f"{dates_key}_max") if dates_key else None
            row += [
                datetime.fromtimestamp(mn).isoformat(timespec="seconds") if isinstance(mn, (int, float)) else "-",
                datetime.fromtimestamp(mx).isoformat(timespec="seconds") if isinstance(mx, (int, float)) else "-",
            ]
        table.add_row(*row)

    footer = Table(box=None, show_header=False, show_lines=False)
    footer.add_column(justify="left")
    footer.add_column(justify="right")
    footer.add_row(
        "[dim]Totals[/]",
        f"[bold]{_format_size(total_bytes, getattr(args, 'auto_units', False))}[/] "
        f"across {sum(d['count'] for d in stats.values())} files, {len(stats)} extensions"
    )

    console.print(table)
    console.print(footer)
    console.print()


def print_hotspots(
    root: Path,
    dir_map: Dict[Path, Dict[str, int]],
    *,
    top_n: int,
    base_total: int,
    base_count: int,
    auto_units: bool,
    sort: str = "size",
):
    width = shutil.get_terminal_size((100, 24)).columns
    show_pct, show_bar = _auto_compact_hotspots(width)

    table = Table(box=box.SIMPLE, expand=True, show_header=True, header_style="bold magenta")
    table.add_column("#", justify="right", no_wrap=True, min_width=2)
    table.add_column("Folder", style="white", overflow="ellipsis", min_width=16)
    table.add_column("Files", justify="right", no_wrap=True, min_width=5)
    table.add_column("Size", justify="right", no_wrap=True, min_width=9)
    if show_pct:
        table.add_column("% of matched", justify="right", no_wrap=True, min_width=9)
    if show_bar:
        table.add_column("Bar", justify="left", no_wrap=True)

    items = [(p, v["count"], v["total"]) for p, v in dir_map.items()]
    items.sort(key=(lambda t: t[2] if sort == "size" else t[1]), reverse=True)

    max_total = max((t[2] for t in items), default=0) or 1

    for idx, (p, cnt, tot) in enumerate(items[:top_n], 1):
        pct = (tot / base_total * 100.0) if base_total > 0 else 0.0
        row = [
            str(idx),
            str(p.relative_to(root)) if p != root else ".",
            str(cnt),
            _format_size(tot, auto_units),
        ]
        if show_pct:
            row.append(f"{pct:.1f}%")
        if show_bar:
            bar_len = max(1, int(20 * (tot / max_total)))
            row.append("█" * bar_len)
        table.add_row(*row)

    console.print(table)
    console.print(f"[dim]Hotspots computed across[/] {base_count} files, {_format_size(base_total, auto_units)} total\n")


def traverse(path: Path, args: argparse.Namespace, current_depth: int = 0):
    stats = gather_stats(
        path, getattr(args, "depth", -1), current_depth,
        exclude=getattr(args, "exclude", []),
        follow_symlinks=getattr(args, "follow_symlinks", False),
    )
    note = None
    if not getattr(args, "auto_units", False):
        for d in stats.values():
            if to_mb(d["total"]) > 9999:
                note = "Large sizes detected: switching to auto-units"
                args.auto_units = True
                break

    console.print(f"[bold]Extensions in:[/] {path.resolve()}\n")
    print_stats(stats, indent=current_depth, dir_name=None, args=args, header_note=note)

    if getattr(args, "hotspots", 0):
        focus = _normalize_exts(getattr(args, "ext", []))
        focus_label = ", ".join(sorted(focus)) if focus else "ALL extensions"
        console.print(f"[bold magenta]Top {args.hotspots} folders[/] — focus: {focus_label}\n")
        dir_map, c, b = gather_dir_totals(
            path, getattr(args, "depth", -1), current_depth,
            focus_exts=(focus if focus else None),
            exclude=getattr(args, "exclude", []),
            follow_symlinks=getattr(args, "follow_symlinks", False),
        )
        print_hotspots(
            path, dir_map,
            top_n=args.hotspots,
            base_total=b,
            base_count=c,
            auto_units=getattr(args, "auto_units", False),
            sort=getattr(args, "hotspots_sort", "size"),
        )

    if getattr(args, "tree", False) and (getattr(args, "depth", -1) < 0 or current_depth < getattr(args, "depth", -1)):
        try:
            subs = sorted(p for p in path.iterdir() if p.is_dir())
        except Exception:
            subs = []
        for sub in subs:
            traverse(sub, args, current_depth + 1)


def main():
    args = parse_args()
    root = Path(args.directory)
    if not root.is_dir():
        console.print(f"[red]Error[/] '{root}' is not a directory.")
        sys.exit(1)

    maxd = find_max_depth(root)
    console.print(f"[green]Max depth:[/] {maxd}\n")

    if args.tree:
        traverse(root, args, 0)
    else:
        stats = gather_stats(
            root, args.depth, 0,
            exclude=args.exclude, follow_symlinks=args.follow_symlinks
        )
        print_stats(stats, args=args)

        if args.hotspots and args.hotspots > 0:
            focus = _normalize_exts(args.ext)
            focus_label = ", ".join(sorted(focus)) if focus else "ALL extensions"
            console.print(f"[bold magenta]Top {args.hotspots} folders[/] — focus: {focus_label}\n")
            dir_map, c, b = gather_dir_totals(
                root, args.depth, 0,
                focus_exts=(focus if focus else None),
                exclude=args.exclude,
                follow_symlinks=args.follow_symlinks,
            )
            print_hotspots(
                root, dir_map,
                top_n=args.hotspots,
                base_total=b,
                base_count=c,
                auto_units=args.auto_units,
                sort=args.hotspots_sort,
            )

if __name__ == "__main__":
    main()
