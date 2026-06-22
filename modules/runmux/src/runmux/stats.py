"""Runtime statistics for runmux-managed processes."""

from __future__ import annotations

import json
import select
import shutil
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from runmux.client import refresh_active_statuses
from runmux.constants import TERMINAL_STATUSES
from runmux.models import RunRecord
from runmux.store import RunStore


@dataclass(frozen=True)
class ProcessStats:
    """Sampled resource usage for one managed run."""

    record: RunRecord
    process_count: int
    thread_count: int
    cpu_percent: float
    rss_bytes: int
    read_bytes_per_second: float
    write_bytes_per_second: float
    net_read_bytes_per_second: float = 0.0
    net_write_bytes_per_second: float = 0.0
    gpu_memory_bytes: int | None = None
    gpu_util_percent: float | None = None
    unavailable: str | None = None


def show_stats(
    store: RunStore,
    *,
    once: bool,
    refresh_seconds: float,
    output_json: bool,
) -> int:
    """Show live or one-shot process stats for active managed runs."""

    if once or output_json:
        stats = sample_active_stats(store, interval_seconds=refresh_seconds)
        if output_json:
            print(json.dumps([stats_to_json(item) for item in stats], indent=2))
        else:
            print(
                format_stats_table(
                    stats,
                    width=shutil.get_terminal_size(fallback=(140, 30)).columns,
                    color=sys.stdout.isatty(),
                )
            )
        return 0

    print("\x1b[?25l", end="")
    try:
        while True:
            stats = sample_active_stats(store, interval_seconds=refresh_seconds)
            screen = "\x1b[H\x1b[2J" + format_stats_table(
                stats,
                width=shutil.get_terminal_size(fallback=(140, 30)).columns,
                title=(
                    f"runmux stats - {time.strftime('%Y-%m-%d %H:%M:%S')} - " "q quit, Ctrl-Q quit now, Ctrl-C exit"
                ),
                color=sys.stdout.isatty(),
            )
            sys.stdout.write(screen)
            sys.stdout.flush()
            key = read_stats_key_nonblocking()
            if key == "\x11":
                return 0
            if key in {"q", "Q"} and confirm_quit():
                return 0
    except KeyboardInterrupt:
        return 0
    finally:
        print("\x1b[?25h", end="")
        sys.stdout.flush()


def sample_active_stats(store: RunStore, *, interval_seconds: float) -> list[ProcessStats]:
    """Sample active process stats over an interval."""

    try:
        import psutil
    except ImportError as error:
        raise RuntimeError("runmux stats requires psutil. Reinstall runmux to refresh dependencies.") from error

    records = refresh_active_statuses(store.list_runs(include_all=False), store)
    active_records = [record for record in records if record.status not in TERMINAL_STATUSES]
    before = {record.id: snapshot_record_io(psutil, record) for record in active_records}
    before_net = snapshot_system_net(psutil)
    prime_cpu_percent(psutil, active_records)
    time.sleep(max(0.1, interval_seconds))
    records = refresh_active_statuses(store.list_runs(include_all=False), store)
    after_net = snapshot_system_net(psutil)
    gpu_usage = query_gpu_usage_by_pid()
    stats: list[ProcessStats] = []
    for record in records:
        if record.status in TERMINAL_STATUSES:
            continue
        stats.append(
            build_process_stats(
                psutil,
                record,
                before.get(record.id),
                interval_seconds,
                system_net_delta=net_delta(before_net, after_net, interval_seconds),
                gpu_usage=gpu_usage,
            )
        )
    return stats


def prime_cpu_percent(psutil_module: Any, records: list[RunRecord]) -> None:
    """Prime psutil CPU counters before a sampled interval."""

    for record in records:
        for process in get_process_tree(psutil_module, record.pid):
            with suppress(psutil_module.Error):
                process.cpu_percent(interval=None)


def snapshot_record_io(psutil_module: Any, record: RunRecord) -> tuple[int, int] | None:
    """Capture aggregate read/write byte counters for a run process tree."""

    processes = get_process_tree(psutil_module, record.pid)
    if not processes:
        return None
    read_bytes = 0
    write_bytes = 0
    for process in processes:
        try:
            counters = process.io_counters()
        except (psutil_module.Error, AttributeError):
            continue
        read_bytes += int(getattr(counters, "read_bytes", 0))
        write_bytes += int(getattr(counters, "write_bytes", 0))
    return read_bytes, write_bytes


def build_process_stats(
    psutil_module: Any,
    record: RunRecord,
    previous_io: tuple[int, int] | None,
    interval_seconds: float,
    system_net_delta: tuple[float, float] | None = None,
    gpu_usage: dict[int, tuple[int, float | None]] | None = None,
) -> ProcessStats:
    """Build sampled stats for one run."""

    processes = get_process_tree(psutil_module, record.pid)
    if not processes:
        return ProcessStats(
            record=record,
            process_count=0,
            thread_count=0,
            cpu_percent=0.0,
            rss_bytes=0,
            read_bytes_per_second=0.0,
            write_bytes_per_second=0.0,
            net_read_bytes_per_second=0.0,
            net_write_bytes_per_second=0.0,
            unavailable="process unavailable",
        )

    process_count = len(processes)
    thread_count = 0
    cpu_percent = 0.0
    rss_bytes = 0
    read_bytes = 0
    write_bytes = 0
    pids: set[int] = set()
    for process in processes:
        pids.add(int(process.pid))
        with suppress(psutil_module.Error):
            thread_count += int(process.num_threads())
        with suppress(psutil_module.Error):
            cpu_percent += float(process.cpu_percent(interval=None))
        with suppress(psutil_module.Error):
            rss_bytes += int(process.memory_info().rss)
        try:
            counters = process.io_counters()
            read_bytes += int(getattr(counters, "read_bytes", 0))
            write_bytes += int(getattr(counters, "write_bytes", 0))
        except (psutil_module.Error, AttributeError):
            pass

    elapsed = max(0.1, interval_seconds)
    if previous_io is None:
        read_rate = 0.0
        write_rate = 0.0
    else:
        read_rate = max(0.0, (read_bytes - previous_io[0]) / elapsed)
        write_rate = max(0.0, (write_bytes - previous_io[1]) / elapsed)

    gpu_memory = 0
    gpu_util_values: list[float] = []
    for pid in pids:
        if gpu_usage and pid in gpu_usage:
            memory, util = gpu_usage[pid]
            gpu_memory += memory
            if util is not None:
                gpu_util_values.append(util)
    gpu_util = sum(gpu_util_values) if gpu_util_values else None
    net_read_rate, net_write_rate = system_net_delta or (0.0, 0.0)

    return ProcessStats(
        record=record,
        process_count=process_count,
        thread_count=thread_count,
        cpu_percent=cpu_percent,
        rss_bytes=rss_bytes,
        read_bytes_per_second=read_rate,
        write_bytes_per_second=write_rate,
        net_read_bytes_per_second=net_read_rate,
        net_write_bytes_per_second=net_write_rate,
        gpu_memory_bytes=gpu_memory or None,
        gpu_util_percent=gpu_util,
    )


def get_process_tree(psutil_module: Any, pid: int | None) -> list[Any]:
    """Return the root process and live child processes."""

    if pid is None:
        return []
    try:
        root = psutil_module.Process(pid)
        children = root.children(recursive=True)
    except psutil_module.Error:
        return []
    processes = [root]
    processes.extend(child for child in children if child.is_running())
    return processes


def format_stats_table(
    stats: list[ProcessStats],
    *,
    width: int,
    title: str | None = None,
    color: bool = False,
) -> str:
    """Format stats as a readable fixed-width table."""

    rows: list[str] = []
    if title:
        rows.append(colorize(title, "1;36", enabled=color))
    rows.append(format_stats_summary(stats, color=color))
    rows.append("")
    header = format_stats_header(color=color)
    separator = f"{'-' * 4} {'-' * 8} {'-' * 7} {'-' * 10} " f"{'-' * 23} {'-' * 14} {'-' * 7} {'-' * 20}"
    rows.append(header)
    rows.append(colorize(separator, "2", enabled=color))
    command_width = max(20, width - 84)
    for item in stats:
        detail = item.unavailable or truncate(item.record.command_line, command_width)
        status = colorize(
            f"{item.record.status:<8}",
            status_color(item.record.status),
            enabled=color,
        )
        cpu = colorize(
            f"{item.cpu_percent:>6.1f}%",
            metric_color(item.cpu_percent, 30, 75),
            enabled=color,
        )
        rss = colorize(f"{format_bytes(item.rss_bytes):>10}", "36", enabled=color)
        disk = (
            f"{colorize('R', '34', enabled=color)} {format_bytes(item.read_bytes_per_second):>8}/s "
            f"{colorize('W', '35', enabled=color)} {format_bytes(item.write_bytes_per_second):>8}/s"
        )
        gpu = format_gpu_cell(item, color=color)
        procs_threads = colorize(f"{item.process_count:>2}/{item.thread_count:<3}", "90", enabled=color)
        command = colorize(detail, "97", enabled=color)
        rows.append(
            f"{item.record.numeric_id:<4} {status} {cpu} {rss} {disk} " f"{gpu:>14} {procs_threads:>7} {command}"
        )
    if not stats:
        rows.append(colorize("No active runmux-managed processes.", "33", enabled=color))
    return "\n".join(rows) + "\n"


def format_stats_summary(stats: list[ProcessStats], *, color: bool) -> str:
    """Format a compact summary line for global counters."""

    total_cpu = sum(item.cpu_percent for item in stats)
    total_rss = sum(item.rss_bytes for item in stats)
    total_disk_read = sum(item.read_bytes_per_second for item in stats)
    total_disk_write = sum(item.write_bytes_per_second for item in stats)
    net_read = stats[0].net_read_bytes_per_second if stats else 0.0
    net_write = stats[0].net_write_bytes_per_second if stats else 0.0
    parts = [
        colorize(f"runs {len(stats)}", "1;37", enabled=color),
        colorize(f"cpu {total_cpu:.1f}%", metric_color(total_cpu, 50, 90), enabled=color),
        colorize(f"rss {format_bytes(total_rss)}", "36", enabled=color),
        colorize(f"disk R {format_bytes(total_disk_read)}/s", "34", enabled=color),
        colorize(f"W {format_bytes(total_disk_write)}/s", "35", enabled=color),
        colorize(f"net(system) R {format_bytes(net_read)}/s", "32", enabled=color),
        colorize(f"W {format_bytes(net_write)}/s", "32", enabled=color),
    ]
    return "  ".join(parts)


def format_stats_header(*, color: bool) -> str:
    """Format the stats table header."""

    header = f"{'ID':<4} {'STATE':<8} {'CPU':>7} {'RAM':>10} {'DISK I/O':<23} " f"{'GPU':>14} {'P/T':>7} COMMAND"
    return colorize(header, "1;37", enabled=color)


def format_gpu_cell(item: ProcessStats, *, color: bool) -> str:
    """Format GPU usage for one process row."""

    if item.gpu_memory_bytes is None and item.gpu_util_percent is None:
        return colorize("--", "90", enabled=color)
    memory = format_optional_bytes(item.gpu_memory_bytes)
    util = format_optional_percent(item.gpu_util_percent)
    return colorize(f"{memory}/{util}", "32", enabled=color)


def stats_to_json(item: ProcessStats) -> dict[str, Any]:
    """Convert process stats to JSON output."""

    return {
        "id": item.record.id,
        "numeric_id": item.record.numeric_id,
        "status": item.record.status,
        "pid": item.record.pid,
        "command_line": item.record.command_line,
        "process_count": item.process_count,
        "thread_count": item.thread_count,
        "cpu_percent": item.cpu_percent,
        "rss_bytes": item.rss_bytes,
        "read_bytes_per_second": item.read_bytes_per_second,
        "write_bytes_per_second": item.write_bytes_per_second,
        "net_read_bytes_per_second": item.net_read_bytes_per_second,
        "net_write_bytes_per_second": item.net_write_bytes_per_second,
        "gpu_memory_bytes": item.gpu_memory_bytes,
        "gpu_util_percent": item.gpu_util_percent,
        "unavailable": item.unavailable,
    }


def snapshot_system_net(psutil_module: Any) -> tuple[int, int] | None:
    """Capture system network counters.

    Most common desktop OS APIs do not expose per-process network throughput.
    This gives a live system delta so runmux still surfaces network activity
    while keeping JSON fields explicit.
    """

    with suppress(psutil_module.Error, AttributeError):
        counters = psutil_module.net_io_counters()
        return int(counters.bytes_recv), int(counters.bytes_sent)
    return None


def net_delta(
    before: tuple[int, int] | None,
    after: tuple[int, int] | None,
    interval_seconds: float,
) -> tuple[float, float] | None:
    """Return system network rates."""

    if before is None or after is None:
        return None
    elapsed = max(0.1, interval_seconds)
    return max(0.0, (after[0] - before[0]) / elapsed), max(0.0, (after[1] - before[1]) / elapsed)


def query_gpu_usage_by_pid() -> dict[int, tuple[int, float | None]]:
    """Return best-effort NVIDIA GPU usage keyed by process PID."""

    command = [
        "nvidia-smi",
        "--query-compute-apps=pid,used_memory",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    usage: dict[int, tuple[int, float | None]] = {}
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        with suppress(ValueError):
            pid = int(parts[0])
            memory_bytes = int(float(parts[1]) * 1024 * 1024)
            usage[pid] = (memory_bytes, None)
    return usage


def read_stats_key_nonblocking() -> str | None:
    """Read one key for the stats UI if one is waiting."""

    if not sys.stdin.isatty():
        return None
    if sys.platform == "win32":
        import msvcrt

        if not msvcrt.kbhit():
            return None
        return msvcrt.getwch()
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready:
        return None
    return sys.stdin.read(1)


def confirm_quit() -> bool:
    """Prompt for q quit confirmation."""

    sys.stdout.write("\x1b[s\x1b[999;1H\x1b[2KQuit runmux stats? y/N \x1b[u")
    sys.stdout.flush()
    if sys.platform == "win32":
        import msvcrt

        key = msvcrt.getwch()
    else:
        key = sys.stdin.read(1)
    return key in {"y", "Y"}


def format_bytes(value: float) -> str:
    """Format a byte value with binary units."""

    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = float(max(0.0, value))
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{amount:.0f} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} PiB"


def format_optional_bytes(value: int | None) -> str:
    """Format optional bytes."""

    if value is None:
        return "--"
    return format_bytes(value)


def format_optional_percent(value: float | None) -> str:
    """Format optional percent."""

    if value is None:
        return "--"
    return f"{value:.0f}%"


def colorize(value: str, color_code: str, *, enabled: bool) -> str:
    """Apply ANSI color when enabled."""

    if not enabled:
        return value
    return f"\x1b[{color_code}m{value}\x1b[0m"


def status_color(status: str) -> str:
    """Return a color code for a run status."""

    if status == "running":
        return "32"
    if status == "paused":
        return "33"
    if status in {"failed", "lost"}:
        return "31"
    if status in {"finished", "killed"}:
        return "90"
    return "37"


def metric_color(value: float, warn: float, critical: float) -> str:
    """Return a color code for a numeric metric."""

    if value >= critical:
        return "31"
    if value >= warn:
        return "33"
    return "32"


def truncate(value: str, width: int) -> str:
    """Truncate text for a table cell."""

    if len(value) <= width:
        return value
    if width <= 1:
        return "…"
    return value[: width - 1] + "…"
