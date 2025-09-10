#!/usr/bin/env python3
"""
TermDash CLI Demos (revised)

- `multistats` is the canonical demo. Use `-r 1` to mimic "single process" stats.
- `threads` runs multiple independent `multistats` rows concurrently.
- Bars below rows are full-width and independent of column alignment.
- `stats` is kept as an alias of `multistats -r 1` to ease transition.

Single-letter flags exist for all options.
"""
from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from . import Stat, Line, TermDash
from .components import DEFAULT_COLOR, RESET
from .progress import ProgressBar
from .seemake import SeemakePrinter


# ---------------------------------------------------------------------------
# Helpers

def _sleep(sec: float) -> None:
    if sec > 0:
        time.sleep(sec)


def _print_snapshot(title: str, rows: List[Tuple[str, List[Stat]]]) -> None:
    print("\n=== TermDash Demo Snapshot:", title, "===")
    for name, stats in rows:
        line = " | ".join(s.render() for s in stats)
        print(f"{name:>12}: {line}")


def _add_header(td: TermDash, name: str, text: str) -> None:
    td.add_line(name, Line(name, stats=[Stat("title", text, format_string="{}", color="1;36")], style="header"))


def _add_fullwidth_bar_line(td: TermDash, line_name: str,
                            current_fn: Callable[[], float],
                            total_fn: Callable[[], float],
                            width_hint: int) -> Line:
    """A bar that spans the terminal width on its *own* line."""
    pb = ProgressBar(f"{line_name}:bar", total=1, width=max(10, width_hint),
                     show_percent=True, full_width=True, margin=0)
    pb.bind(current_fn=current_fn, total_fn=total_fn)
    line = Line(f"{line_name}:bar", stats=[pb.cell()])
    td.add_line(f"{line_name}:bar", line)
    return line


# ---------------------------------------------------------------------------
# MULTISTATS

@dataclass
class StatItem:
    name: str
    total: int
    done: int = 0
    status: str = "queued"
    rate: float = 0.0
    errs: int = 0

class StatItemStat(Stat):
    def __init__(self, name, item, extra_stats=0, with_progress=False):
        super().__init__(name, value=item)
        self.item = item
        self.extra_stats = extra_stats
        self.with_progress = with_progress
        if self.with_progress:
            self.progress_bar = ProgressBar(f"{name}_bar", total=item.total, width=30, min_width_fraction=0.66)

    def render(self, logger=None) -> str:
        item = self.item
        if self.with_progress:
            self.progress_bar.set(item.done)
        
        parts = []
        if self.with_progress:
            parts.append(self.progress_bar.__str__())
        
        parts.append(f"{item.status:12}")
        parts.append(f"Done: {item.done:4}")
        parts.append(f"Total: {item.total:<4}")
        if self.extra_stats >= 1:
            parts.append(f"Rate: {item.rate:6.1f} u/s")
        if self.extra_stats >= 2:
            parts.append(f"Errs: {item.errs}")
        
        text = "  ".join(parts)
        color_code = self.color_provider(self.value) or DEFAULT_COLOR
        return f"\033[{color_code}m{text}{RESET}"

def _profile(kind: str) -> Tuple[int, int]:
    return {
        "ytdlp": (1, 6),
        "copy": (5, 25),
        "compute": (1, 3),
    }.get(kind, (1, 5))

def demo_multistats(args: argparse.Namespace) -> int:
    stat_rows = max(1, args.stat_rows)
    stat_cols = max(1, args.stat_cols)
    duration = max(0.1, args.duration)
    update = max(0.01, args.update)
    kind = args.proc

    # Create a grid of stats
    stats_grid = []
    for r in range(stat_rows):
        row_items = []
        for c in range(stat_cols):
            item = StatItem(name=f"stat_{r}_{c}", total=random.randint(60, 120))
            row_items.append(item)
        stats_grid.append(row_items)

    td = None
    snap: List[Tuple[str, List[Stat]]] = []

    if args.plain:
        t0 = time.time()
        while time.time() - t0 < duration and any(item.done < item.total for row in stats_grid for item in row):
            for r_idx, row in enumerate(stats_grid):
                line_parts = []
                for c_idx, item in enumerate(row):
                    if item.done < item.total:
                        step = random.randint(*_profile(kind))
                        item.done = min(item.total, item.done + step)
                        item.rate = 0.6 * item.rate + 0.4 * (step / max(update, 1e-6))
                        item.status = "downloading" if kind == "ytdlp" else "running"
                    else:
                        item.status = "done"
                    line_parts.append(f"{item.name:>12} | {item.status:12} | {item.done:4}/{item.total:<4} | {item.rate:6.1f} u/s | errs={item.errs}")
                print(" | ".join(line_parts))
            _sleep(update)
        return 0

    td = TermDash(status_line=True, refresh_rate=0.05)
    with td:
        if args.header:
            _add_header(td, "hdr", f"Multi-Stats Demo ({kind})")
            if args.header_bar:
                bar_line = _add_fullwidth_bar_line(
                    td, "hdr",
                    current_fn=lambda: float(sum(item.done for row in stats_grid for item in row)),
                    total_fn=lambda: float(sum(item.total for row in stats_grid for item in row)),
                    width_hint=args.width,
                )
                snap.append((bar_line.name, list(bar_line._stats.values())))

        # Create lines for each row of stats
        for r_idx, row_items in enumerate(stats_grid):
            line_name = f"line_{r_idx}"
            cells = []
            for c_idx, item in enumerate(row_items):
                cells.append(StatItemStat(f"stat_{r_idx}_{c_idx}", item, args.extra_stats, args.progress_bar))
            
            line = Line(line_name, stats=cells)
            td.add_line(line_name, line)
            snap.append((line_name, cells))

            if args.bars:
                def make_current_fn(items):
                    return lambda: float(sum(item.done for item in items))
                def make_total_fn(items):
                    return lambda: float(sum(item.total for item in items))

                bar_line = _add_fullwidth_bar_line(
                    td,
                    line_name,
                    current_fn=make_current_fn(row_items),
                    total_fn=make_total_fn(row_items),
                    width_hint=args.width,
                )
                snap.append((bar_line.name, list(bar_line._stats.values())))

        # Drive updates
        t0 = time.time()
        while time.time() - t0 < duration and any(item.done < item.total for row in stats_grid for item in row):
            for r_idx, row_items in enumerate(stats_grid):
                for c_idx, item in enumerate(row_items):
                    if item.done >= item.total:
                        if item.status != "done":
                            item.status = "done"
                    else:
                        step = random.randint(*_profile(kind))
                        item.done = min(item.total, item.done + step)
                        item.rate = 0.6 * item.rate + 0.4 * (step / max(update, 1e-6))
                        item.status = "downloading" if kind == "ytdlp" else "running"

                    if args.extra_stats >= 2 and random.random() < 0.03:
                        item.errs += 1
            _sleep(update)

    if not args.clear:
        _print_snapshot("multistats", snap)
    return 0


# ---------------------------------------------------------------------------
# MULTISTATS

@dataclass
class StatItem:
    name: str
    total: int
    done: int = 0
    status: str = "queued"
    rate: float = 0.0
    errs: int = 0

class StatItemStat(Stat):
    def __init__(self, name, item, extra_stats=0, with_progress=False):
        super().__init__(name, value=item)
        self.item = item
        self.extra_stats = extra_stats
        self.with_progress = with_progress
        if self.with_progress:
            self.progress_bar = ProgressBar(f"{name}_bar", total=item.total, width=30, min_width_fraction=0.66)

    def render(self, logger=None) -> str:
        item = self.item
        if self.with_progress:
            self.progress_bar.set(item.done)
        
        parts = []
        if self.with_progress:
            parts.append(self.progress_bar.__str__())
        
        parts.append(f"{item.status:12}")
        parts.append(f"Done: {item.done:4}")
        parts.append(f"Total: {item.total:<4}")
        if self.extra_stats >= 1:
            parts.append(f"Rate: {item.rate:6.1f} u/s")
        if self.extra_stats >= 2:
            parts.append(f"Errs: {item.errs}")
        
        text = "  ".join(parts)
        color_code = self.color_provider(self.value) or DEFAULT_COLOR
        return f"\033[{color_code}m{text}{RESET}"

def _profile(kind: str) -> Tuple[int, int]:
    return {
        "ytdlp": (1, 6),
        "copy": (5, 25),
        "compute": (1, 3),
    }.get(kind, (1, 5))

def demo_multistats(args: argparse.Namespace) -> int:
    stat_rows = max(1, args.stat_rows)
    stat_cols = max(1, args.stat_cols)
    duration = max(0.1, args.duration)
    update = max(0.01, args.update)
    kind = args.proc

    # Create a grid of stats
    stats_grid = []
    for r in range(stat_rows):
        row_items = []
        for c in range(stat_cols):
            item = StatItem(name=f"stat_{r}_{c}", total=random.randint(60, 120))
            row_items.append(item)
        stats_grid.append(row_items)

    td = None
    snap: List[Tuple[str, List[Stat]]] = []

    if args.plain:
        t0 = time.time()
        while time.time() - t0 < duration and any(item.done < item.total for row in stats_grid for item in row):
            for r_idx, row in enumerate(stats_grid):
                line_parts = []
                for c_idx, item in enumerate(row):
                    if item.done < item.total:
                        step = random.randint(*_profile(kind))
                        item.done = min(item.total, item.done + step)
                        item.rate = 0.6 * item.rate + 0.4 * (step / max(update, 1e-6))
                        item.status = "downloading" if kind == "ytdlp" else "running"
                    else:
                        item.status = "done"
                    line_parts.append(f"{item.name:>12} | {item.status:12} | {item.done:4}/{item.total:<4} | {item.rate:6.1f} u/s | errs={item.errs}")
                print(" | ".join(line_parts))
            _sleep(update)
        return 0

    td = TermDash(status_line=True, refresh_rate=0.05)
    with td:
        if args.header:
            _add_header(td, "hdr", f"Multi-Stats Demo ({kind})")
            if args.header_bar:
                _add_fullwidth_bar_line(
                    td, "hdr",
                    current_fn=lambda: float(sum(item.done for row in stats_grid for item in row)),
                    total_fn=lambda: float(sum(item.total for row in stats_grid for item in row)),
                    width_hint=args.width,
                )

        # Create lines for each row of stats
        for r_idx, row_items in enumerate(stats_grid):
            line_name = f"line_{r_idx}"
            cells = []
            for c_idx, item in enumerate(row_items):
                cells.append(StatItemStat(f"stat_{r_idx}_{c_idx}", item, args.extra_stats, args.progress_bar))
            
            td.add_line(line_name, Line(line_name, stats=cells))
            snap.append((line_name, cells))

            if args.bars:
                _add_fullwidth_bar_line(
                    td,
                    line_name,
                    current_fn=lambda row_items=row_items: float(sum(item.done for item in row_items)),
                    total_fn=lambda row_items=row_items: float(sum(item.total for item in row_items)),
                    width_hint=args.width,
                )

        # Drive updates
        t0 = time.time()
        while time.time() - t0 < duration and any(item.done < item.total for row in stats_grid for item in row):
            for r_idx, row_items in enumerate(stats_grid):
                for c_idx, item in enumerate(row_items):
                    if item.done >= item.total:
                        if item.status != "done":
                            item.status = "done"
                    else:
                        step = random.randint(*_profile(kind))
                        item.done = min(item.total, item.done + step)
                        item.rate = 0.6 * item.rate + 0.4 * (step / max(update, 1e-6))
                        item.status = "downloading" if kind == "ytdlp" else "running"

                    if args.extra_stats >= 2 and random.random() < 0.03:
                        item.errs += 1
            _sleep(update)

    if not args.clear:
        _print_snapshot("multistats", snap)
    return 0


# ---------------------------------------------------------------------------
# THREADS  => multiple multistats asynchronously

def demo_threads(args: argparse.Namespace) -> int:
    threads = max(1, args.threads)
    duration = max(0.1, args.duration)
    update = max(0.01, args.update)
    kind = args.proc

    items = [StatItem(name=f"thr-{i+1:02d}", total=random.randint(60, 120)) for i in range(threads)]

    td = TermDash(status_line=True, refresh_rate=0.05)
    with td:
        if args.header:
            _add_header(td, "hdr", "Multi-Threaded Demo")
            if args.header_bar:
                _add_fullwidth_bar_line(
                    td, "hdr",
                    current_fn=lambda: float(sum(item.done for item in items)),
                    total_fn=lambda: float(sum(item.total for item in items)),
                    width_hint=args.width,
                )

        # one row per thread
        for i in range(threads):
            item = items[i]
            line_name = f"thr-{i+1:02d}"
            cells = [StatItemStat(f"stat_{i}", item, args.extra_stats, args.bars)]
            td.add_line(line_name, Line(line_name, stats=cells))

        stop = time.time() + duration

        def worker(idx: int) -> None:
            item = items[idx]
            while time.time() < stop and item.done < item.total:
                lo, hi = _profile(kind)
                step = random.randint(lo, hi)
                item.done = min(item.total, item.done + step)
                item.rate = 0.6 * item.rate + 0.4 * (step / max(update, 1e-6))
                _sleep(update)

        ts = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(threads)]
        for t in ts: t.start()
        for t in ts: t.join()

    return 0


# ---------------------------------------------------------------------------
# SEEMAKE

def demo_seemake(args: argparse.Namespace) -> int:
    steps = max(1, args.steps)

    if args.plain:
        # Plain mode: simple colored-like text (no ANSI here to keep logs clean)
        for i in range(1, steps + 1):
            pct = int(round(100 * i / steps))
            print(f"[{pct:3d}%] step {i}/{steps}")
            _sleep(args.interval)
        return 0

    # Leaner TermDash config to reduce flicker and avoid the "lock" feel.
    td = TermDash(status_line=False, refresh_rate=0.05, reserve_extra_rows=0)
    with td:
        sm = SeemakePrinter(
            total=steps, td=td, with_bar=args.header_bar,
            bar_width=args.width, label="Build", out=sys.stdout
        )
        # Typical sequence: scan -> build -> (optional link) -> success
        kinds = ["scan", "build", "build", "link", "success"]
        for i in range(1, steps + 1):
            k = kinds[(i - 1) % len(kinds)]
            msg = {
                "scan": "Scanning dependencies of target demo",
                "build": f"Building CXX object src/file_{i}.o",
                "link": "Linking CXX executable demo",
                "success": "Built target demo",
            }[k]
            sm.step(msg, kind=k)
            _sleep(args.interval)

    return 0


# ---------------------------------------------------------------------------
# ARGPARSE

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="termdash", description="TermDash CLI demos")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser):
        sp.add_argument("-c", "--clear", action="store_true", help="Clear screen at exit (default: print snapshot).")
        sp.add_argument("-P", "--plain", action="store_true", help="Run without live dashboard; print plain text.")
        sp.add_argument("-S", "--seed", type=int, default=1234, help="Random seed for repeatability.")

    # multistats (canonical)
    sp = sub.add_parser("multistats", help="Single process with multiple stats in a grid.")
    add_common(sp)
    sp.add_argument("-r", "--stat-rows", type=int, default=3, help="Number of rows of stats.")
    sp.add_argument("-C", "--stat-cols", type=int, default=2, help="Number of columns of stats.")
    sp.add_argument("-g", "--proc", choices=["ytdlp", "copy", "compute"], default="ytdlp", help="Profile of row updates.")
    sp.add_argument("-d", "--duration", type=float, default=5.0)
    sp.add_argument("-u", "--update", type=float, default=0.15)
    sp.add_argument("-w", "--width", type=int, default=26, help="Width hint for bars (full-width ignores this mostly).")
    sp.add_argument("-b", "--bars", action="store_true", help="Show a full-width bar on its own line below each row.")
    sp.add_argument("-e", "--extra-stats", type=int, default=0, help="Extra stats per cell (0..2).")
    sp.add_argument("-p", "--progress-bar", action="store_true", help="Show a progress bar in each cell.")
    sp.add_argument("-H", "--header", action="store_true", help="Header with title.")
    sp.add_argument("-B", "--header-bar", action="store_true", help="Header progress bar (combined progress).")
    sp.set_defaults(func=demo_multistats)

    # threads (many multistats concurrently)
    sp = sub.add_parser("threads", help="Multiple rows updated by threads; same flags as multistats.")
    add_common(sp)
    sp.add_argument("-n", "--threads", type=int, default=6)
    sp.add_argument("-g", "--proc", choices=["ytdlp", "copy", "compute"], default="ytdlp")
    sp.add_argument("-d", "--duration", type=float, default=5.0)
    sp.add_argument("-u", "--update", type=float, default=0.10)
    sp.add_argument("-w", "--width", type=int, default=26)
    sp.add_argument("-b", "--bars", action="store_true")
    sp.add_argument("-e", "--extra-stats", type=int, default=0)
    sp.add_argument("-H", "--header", action="store_true")
    sp.add_argument("-B", "--header-bar", action="store_true")
    sp.set_defaults(func=demo_threads)

    # seamake
    sp = sub.add_parser("seemake", help="CMake-like scrolling output (optionally with a bottom bar).")
    add_common(sp)
    sp.add_argument("-s", "--steps", type=int, default=25)
    sp.add_argument("-i", "--interval", type=float, default=0.08)
    sp.add_argument("-B", "--header-bar", action="store_true", help="Show a bottom progress bar row.")
    sp.add_argument("-w", "--width", type=int, default=24)
    sp.set_defaults(func=demo_seemake)

    # stats (alias of multistats -r 1)
    sp = sub.add_parser("stats", help="Alias of: multistats -r 1")
    add_common(sp)
    sp.add_argument("-b", "--bars", action="store_true")
    sp.add_argument("-e", "--extra-stats", type=int, default=0)
    sp.add_argument("-H", "--header", action="store_true")
    sp.add_argument("-B", "--header-bar", action="store_true")
    sp.add_argument("-w", "--width", type=int, default=28)
    sp.set_defaults(func=lambda a: demo_multistats(argparse.Namespace(
        cmd="multistats",
        clear=a.clear, plain=a.plain, seed=a.seed,
        stat_rows=1, stat_cols=1, proc="ytdlp",
        duration=4.0, update=0.1, width=a.width,
        bars=a.bars, extra_stats=a.extra_stats, header=a.header, header_bar=a.header_bar,
    )))

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    random.seed(args.seed)
    return int(bool(args.func(args)))


if __name__ == "__main__":
    raise SystemExit(main())
