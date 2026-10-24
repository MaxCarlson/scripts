"""Runtime statistics and verified resource telemetry for runmux-managed processes."""

from __future__ import annotations

import json
import select
import shutil
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from resource_metrics import gpu_devices, gpu_process_memory, process_tree
from resource_metrics.process import process_io
from resource_metrics.system import memory_stats, net_io_counters, rate

from runmux.client import refresh_active_statuses
from runmux.constants import TERMINAL_STATUSES
from runmux.models import RunRecord, parse_iso_datetime, utc_now_iso
from runmux.store import RunStore


@dataclass(frozen=True)
class HostTelemetry:
    """Sampled host-level resource telemetry."""

    cpu_percent: float | None
    cpu_count: int
    memory_used_bytes: int | None
    memory_available_bytes: int | None
    memory_total_bytes: int | None
    memory_percent: float | None
    net_read_bytes_per_second: float | None
    net_write_bytes_per_second: float | None
    gpu_devices: list[dict[str, Any]]
    sampled_at: str
    sampled_epoch: float | None = None


@dataclass(frozen=True)
class ProcessStats:
    """Sampled resource usage for one managed run.

    Provides verified metrics with clear attribution scope:
    - cpu_percent: raw multi-core sum (100% per core)
    - cpu_percent_normalized: normalized by logical CPU count (0-100%)
    - rss_bytes: aggregate resident memory across process tree
    - read_bytes_per_second / write_bytes_per_second: disk I/O rate
    - net_read_bytes_per_second / net_write_bytes_per_second: per-process network
      (None unless per-socket OS attribution exists)
    - host_net_read_bytes_per_second / host_net_write_bytes_per_second: host-level
      network delta explicitly scoped to the machine
    - unavailable: explicit reason when metrics cannot be gathered
    """

    record: RunRecord
    process_count: int
    thread_count: int
    cpu_percent: float | None
    rss_bytes: int | None
    read_bytes_per_second: float | None
    write_bytes_per_second: float | None
    net_read_bytes_per_second: float | None = None
    net_write_bytes_per_second: float | None = None
    host_net_read_bytes_per_second: float | None = None
    host_net_write_bytes_per_second: float | None = None
    cpu_percent_normalized: float | None = None
    cpu_count: int = 1
    cpu_time_seconds: float | None = None
    total_read_bytes: int | None = None
    total_write_bytes: int | None = None
    gpu_memory_bytes: int | None = None
    gpu_util_percent: float | None = None
    unavailable: str | None = None
    sampled_at: str | None = None
    sample_interval_seconds: float | None = None
    sampled_epoch: float | None = None


PID_CREATION_TOLERANCE_SECONDS = 5.0


def verify_run_process(psutil_module: Any, record: RunRecord) -> tuple[Any | None, str | None]:
    """Verify run status and PID identity to prevent false attribution and PID reuse."""

    if record.status in TERMINAL_STATUSES:
        return None, f"run is {record.status}"
    if record.pid is None:
        return None, "no pid assigned"

    if not hasattr(psutil_module, "Process"):
        return None, None

    no_such_error = getattr(psutil_module, "NoSuchProcess", psutil_module.Error)
    access_error = getattr(psutil_module, "AccessDenied", psutil_module.Error)
    zombie_error = getattr(psutil_module, "ZombieProcess", psutil_module.Error)

    try:
        root = psutil_module.Process(record.pid)
        if hasattr(root, "is_running") and not root.is_running():
            return None, "process exited"
    except no_such_error:
        return None, "process exited"
    except access_error:
        return None, "permission denied"
    except zombie_error:
        return None, "zombie process"
    except (psutil_module.Error, OSError, ValueError):
        return None, "process unavailable"

    # PID reuse protection: compare process create_time with run record timestamps
    ref_iso = record.started_at or record.created_at
    if hasattr(root, "create_time") and ref_iso:
        try:
            ref_dt = parse_iso_datetime(ref_iso)
            if ref_dt is not None:
                ref_epoch = ref_dt.timestamp()
                proc_create = float(root.create_time())
                # If process was created noticeably after run started, PID has been recycled
                if proc_create > ref_epoch + PID_CREATION_TOLERANCE_SECONDS:
                    return None, "pid reused by another process"
                # If process was created noticeably before run started, PID belongs to older process
                if proc_create < ref_epoch - PID_CREATION_TOLERANCE_SECONDS:
                    return None, "pid reused by another process"
                if record.ended_at:
                    ended_dt = parse_iso_datetime(record.ended_at)
                    if ended_dt and proc_create > ended_dt.timestamp():
                        return None, "pid reused by another process"
        except (ValueError, OSError, OverflowError):
            pass

    return root, None


def verify_supervisor_process(psutil_module: Any, record: RunRecord) -> tuple[Any | None, str | None]:
    """Verify supervisor status and PID identity to prevent false attribution and PID reuse."""

    if record.supervisor_pid is None:
        return None, "no supervisor pid assigned"

    if not hasattr(psutil_module, "Process"):
        return None, None

    no_such_error = getattr(psutil_module, "NoSuchProcess", psutil_module.Error)
    access_error = getattr(psutil_module, "AccessDenied", psutil_module.Error)
    zombie_error = getattr(psutil_module, "ZombieProcess", psutil_module.Error)

    try:
        proc = psutil_module.Process(record.supervisor_pid)
        if hasattr(proc, "is_running") and not proc.is_running():
            return None, "process exited"
    except no_such_error:
        return None, "process exited"
    except access_error:
        return None, "permission denied"
    except zombie_error:
        return None, "zombie process"
    except (psutil_module.Error, OSError, ValueError):
        return None, "process unavailable"

    identity_verified = False

    # PID reuse protection: compare process create_time with run record timestamps
    ref_iso = record.created_at or record.started_at
    if hasattr(proc, "create_time") and ref_iso:
        try:
            ref_dt = parse_iso_datetime(ref_iso)
            if ref_dt is not None:
                ref_epoch = ref_dt.timestamp()
                proc_create = float(proc.create_time())
                # If process was created noticeably after run started, PID has been recycled
                if proc_create > ref_epoch + PID_CREATION_TOLERANCE_SECONDS:
                    return None, "pid reused by another process"
                # If process was created noticeably before run started, PID belongs to older process
                if proc_create < ref_epoch - PID_CREATION_TOLERANCE_SECONDS:
                    return None, "pid reused by another process"
                if record.ended_at:
                    ended_dt = parse_iso_datetime(record.ended_at)
                    if ended_dt and proc_create > ended_dt.timestamp():
                        return None, "pid reused by another process"
                identity_verified = True
        except (ValueError, OSError, OverflowError):
            pass

    # Command line check: verify process command line matches supervisor for this run
    if hasattr(proc, "cmdline"):
        try:
            cmd = proc.cmdline()
            if cmd:
                cmd_str = " ".join(cmd)
                if "runmux.supervisor" not in cmd_str or record.id not in cmd_str:
                    return None, "pid reused by another process"
                identity_verified = True
        except (access_error, no_such_error):
            return None, "permission denied"
        except (psutil_module.Error, OSError, ValueError):
            pass

    if not identity_verified:
        return None, "supervisor identity unconfirmed"

    return proc, None


class TelemetrySampler:
    """Non-blocking, thread-safe monotonic resource telemetry sampler for Runmux.

    Note on Child-PID Caching:
    On Windows, full process-tree discovery via toolhelp snapshots requires ~18ms per
    active run. To minimize sampling CPU overhead, discovered child PIDs and their
    creation timestamps are cached for child_cache_ttl (default: 30.0s).
    During cache hits, cached child processes are inspected directly and verified
    against PID recycling via create_time().
    Tradeoff: Short-lived child processes that spawn and terminate entirely within
    the 30-second window between full discovery scans may not be captured in tree
    aggregations.
    """

    def __init__(self, *, clock: Any = time.monotonic, child_cache_ttl: float = 30.0) -> None:
        self._clock = clock
        self._child_cache_ttl = child_cache_ttl
        self._lock = threading.Lock()
        # run_id -> (timestamp, cpu_time, read_bytes, write_bytes, pid)
        self._snapshots: dict[str, tuple[float, float, int | None, int | None, int | None]] = {}
        # run_id -> (cache_timestamp, [(process, create_time), ...])
        self._child_cache: dict[str, tuple[float, list[tuple[Any, float]]]] = {}
        self._cached_gpu: tuple[float, dict[int, tuple[int, float | None]]] | None = None
        self._cached_gpu_devices: tuple[float, list[dict[str, Any]]] | None = None
        self._cached_host_net: tuple[float, tuple[int, int]] | None = None

    def clear(self) -> None:
        """Clear all cached sample baselines."""
        with self._lock:
            self._snapshots.clear()
            self._child_cache.clear()
            self._cached_gpu = None
            self._cached_gpu_devices = None
            self._cached_host_net = None

    def _get_gpu_usage(self) -> dict[int, tuple[int, float | None]]:
        now = self._clock()
        if self._cached_gpu and (now - self._cached_gpu[0]) < 1.5:
            return self._cached_gpu[1]
        usage = query_gpu_usage_by_pid()
        self._cached_gpu = (now, usage)
        return usage

    def _get_gpu_devices(self) -> list[dict[str, Any]]:
        now = self._clock()
        if self._cached_gpu_devices and (now - self._cached_gpu_devices[0]) < 1.5:
            return self._cached_gpu_devices[1]
        devices = gpu_devices(timeout=1.0)
        self._cached_gpu_devices = (now, devices)
        return devices

    def sample_run(
        self,
        record: RunRecord,
        *,
        psutil_module: Any = None,
        gpu_usage: dict[int, tuple[int, float | None]] | None = None,
    ) -> ProcessStats:
        """Sample single run metrics instantaneously using monotonic state deltas."""

        if psutil_module is None:
            try:
                import psutil as psutil_module
            except ImportError:
                return ProcessStats(
                    record=record,
                    process_count=0,
                    thread_count=0,
                    cpu_percent=None,
                    rss_bytes=None,
                    read_bytes_per_second=None,
                    write_bytes_per_second=None,
                    unavailable="psutil unavailable",
                    sampled_at=utc_now_iso(),
                )

        root, unavailable_reason = verify_run_process(psutil_module, record)
        now = self._clock()
        sampled_at = utc_now_iso()

        if unavailable_reason is not None:
            with self._lock:
                self._snapshots.pop(record.id, None)
                self._child_cache.pop(record.id, None)
            return ProcessStats(
                record=record,
                process_count=0,
                thread_count=0,
                cpu_percent=None,
                rss_bytes=None,
                read_bytes_per_second=None,
                write_bytes_per_second=None,
                unavailable=unavailable_reason,
                sampled_at=sampled_at,
            )

        processes: list[Any] = [root]
        with self._lock:
            cached_child_entry = self._child_cache.get(record.id)
            if cached_child_entry is not None and (now - cached_child_entry[0]) < self._child_cache_ttl:
                # Cache hit: inspect known children directly, verifying against PID recycling
                valid_children: list[tuple[Any, float]] = []
                for child, expected_create_time in cached_child_entry[1]:
                    try:
                        if hasattr(child, "is_running") and not child.is_running():
                            continue
                        if hasattr(child, "create_time") and child.create_time() != expected_create_time:
                            continue # Recycled PID!
                        valid_children.append((child, expected_create_time))
                        processes.append(child)
                    except (psutil_module.Error, OSError, ValueError):
                        pass
                self._child_cache[record.id] = (cached_child_entry[0], valid_children)
            else:
                # Cache miss or expired: perform full discovery
                discovered = get_process_tree(psutil_module, record.pid)
                if not discovered:
                    self._snapshots.pop(record.id, None)
                    self._child_cache.pop(record.id, None)
                    return ProcessStats(
                        record=record,
                        process_count=0,
                        thread_count=0,
                        cpu_percent=None,
                        rss_bytes=None,
                        read_bytes_per_second=None,
                        write_bytes_per_second=None,
                        unavailable="process unavailable",
                        sampled_at=sampled_at,
                    )
                processes = discovered
                new_cached_children = []
                for p in processes:
                    if int(p.pid) != int(root.pid):
                        try:
                            new_cached_children.append((p, float(p.create_time())))
                        except (psutil_module.Error, OSError, AttributeError):
                            pass
                self._child_cache[record.id] = (now, new_cached_children)

        process_count = len(processes)
        thread_count = 0
        rss_bytes = 0
        cpu_time = 0.0
        read_bytes: int | None = None
        write_bytes: int | None = None
        io_supported = False
        pids: set[int] = set()

        for process in processes:
            pids.add(int(process.pid))
            with suppress(psutil_module.Error, OSError):
                thread_count += int(process.num_threads())
            with suppress(psutil_module.Error, OSError):
                times = process.cpu_times()
                cpu_time += float(times.user) + float(times.system)
            with suppress(psutil_module.Error, OSError):
                rss_bytes += int(process.memory_info().rss)
            counters = process_io(process, psutil_module=psutil_module)
            if counters is not None:
                r_val = getattr(counters, "read_bytes", None)
                w_val = getattr(counters, "write_bytes", None)
                if r_val is not None:
                    read_bytes = (read_bytes or 0) + int(r_val)
                    io_supported = True
                if w_val is not None:
                    write_bytes = (write_bytes or 0) + int(w_val)
                    io_supported = True

        try:
            cores = psutil_module.cpu_count(logical=True)
        except (psutil_module.Error, OSError, AttributeError):
            cores = None
        cores = max(1, int(cores or 1))

        cpu_percent: float | None = None
        read_rate: float | None = None
        write_rate: float | None = None
        elapsed: float | None = None

        with self._lock:
            prev = self._snapshots.get(record.id)
            if prev is not None and prev[4] == record.pid:
                prev_time, prev_cpu, prev_read, prev_write, _ = prev
                delta_t = now - prev_time
                if delta_t > 0:
                    elapsed = delta_t
                    cpu_percent = max(0.0, (cpu_time - prev_cpu) / delta_t * 100.0)
                    if prev_read is not None and read_bytes is not None:
                        read_rate = rate(prev_read, read_bytes, delta_t)
                    if prev_write is not None and write_bytes is not None:
                        write_rate = rate(prev_write, write_bytes, delta_t)
            self._snapshots[record.id] = (
                now,
                cpu_time,
                read_bytes if io_supported else None,
                write_bytes if io_supported else None,
                record.pid,
            )

        cpu_percent_normalized = (cpu_percent / cores) if cpu_percent is not None else None

        active_gpu_usage = gpu_usage if gpu_usage is not None else self._get_gpu_usage()
        gpu_memory = 0
        for pid in pids:
            if pid in active_gpu_usage:
                mem, _ = active_gpu_usage[pid]
                gpu_memory += mem

        return ProcessStats(
            record=record,
            process_count=process_count,
            thread_count=thread_count,
            cpu_percent=cpu_percent,
            cpu_percent_normalized=cpu_percent_normalized,
            cpu_count=cores,
            cpu_time_seconds=cpu_time,
            rss_bytes=rss_bytes,
            read_bytes_per_second=read_rate,
            write_bytes_per_second=write_rate,
            total_read_bytes=read_bytes if io_supported else None,
            total_write_bytes=write_bytes if io_supported else None,
            net_read_bytes_per_second=None,
            net_write_bytes_per_second=None,
            gpu_memory_bytes=gpu_memory or None,
            gpu_util_percent=None,
            sampled_at=sampled_at,
            sample_interval_seconds=elapsed,
            sampled_epoch=time.time(),
        )

    def sample_active_runs(
        self,
        records: list[RunRecord],
        *,
        psutil_module: Any = None,
    ) -> tuple[list[ProcessStats], HostTelemetry]:
        """Sample all active runs non-blockingly and collect host telemetry."""

        if psutil_module is None:
            try:
                import psutil as psutil_module
            except ImportError:
                psutil_module = None

        active_records = [r for r in records if r.status not in TERMINAL_STATUSES]
        active_ids = {r.id for r in active_records}

        with self._lock:
            for saved_id in list(self._snapshots):
                if saved_id not in active_ids:
                    self._snapshots.pop(saved_id, None)
            for cached_id in list(self._child_cache):
                if cached_id not in active_ids:
                    self._child_cache.pop(cached_id, None)

        gpu_usage = self._get_gpu_usage()
        stats = [self.sample_run(record, psutil_module=psutil_module, gpu_usage=gpu_usage) for record in records]

        # Host telemetry
        host_cpu = None
        cores = 1
        mem_used = None
        mem_avail = None
        mem_total = None
        mem_pct = None
        host_net_read = None
        host_net_write = None

        if psutil_module:
            with suppress(psutil_module.Error, OSError):
                host_cpu = float(psutil_module.cpu_percent(interval=None))
            with suppress(psutil_module.Error, OSError, AttributeError):
                cores = int(psutil_module.cpu_count(logical=True) or 1)

        mem = memory_stats()
        if mem:
            mem_used = mem.get("used")
            mem_avail = mem.get("available")
            mem_total = mem.get("total")
            mem_pct = mem.get("percent")

        now = self._clock()
        curr_net = snapshot_system_net(psutil_module)
        if curr_net and self._cached_host_net:
            prev_net_time, prev_net_counters = self._cached_host_net
            net_elapsed = now - prev_net_time
            if net_elapsed > 0:
                host_net_read = rate(prev_net_counters[0], curr_net[0], net_elapsed)
                host_net_write = rate(prev_net_counters[1], curr_net[1], net_elapsed)
        if curr_net:
            self._cached_host_net = (now, curr_net)

        devices = self._get_gpu_devices()

        host_telemetry = HostTelemetry(
            cpu_percent=host_cpu,
            cpu_count=cores,
            memory_used_bytes=mem_used,
            memory_available_bytes=mem_avail,
            memory_total_bytes=mem_total,
            memory_percent=mem_pct,
            net_read_bytes_per_second=host_net_read,
            net_write_bytes_per_second=host_net_write,
            gpu_devices=devices,
            sampled_at=utc_now_iso(),
            sampled_epoch=time.time(),
        )

        return stats, host_telemetry


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
                title=(f"runmux stats - {time.strftime('%Y-%m-%d %H:%M:%S')} - q quit, Ctrl-Q quit now, Ctrl-C exit"),
                color=sys.stdout.isatty(),
            ).replace("\n", "\r\n")
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
    """Sample active process stats over an interval for CLI commands."""

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
    host_net = net_delta(before_net, after_net, interval_seconds)
    for record in records:
        if record.status in TERMINAL_STATUSES:
            continue
        stats.append(
            build_process_stats(
                psutil,
                record,
                before.get(record.id),
                interval_seconds,
                system_net_delta=host_net,
                gpu_usage=gpu_usage,
            )
        )
    return stats


def prime_cpu_percent(psutil_module: Any, records: list[RunRecord]) -> None:
    """Prime psutil CPU counters before a sampled interval."""

    for record in records:
        for process in get_process_tree(psutil_module, record.pid):
            with suppress(psutil_module.Error, OSError):
                process.cpu_percent(interval=None)


def snapshot_record_io(psutil_module: Any, record: RunRecord) -> tuple[int, int] | None:
    """Capture aggregate read/write byte counters for a run process tree."""

    processes = get_process_tree(psutil_module, record.pid)
    if not processes:
        return None
    read_bytes = 0
    write_bytes = 0
    io_found = False
    for process in processes:
        counters = process_io(process, psutil_module=psutil_module)
        if counters is None:
            continue
        r = getattr(counters, "read_bytes", None)
        w = getattr(counters, "write_bytes", None)
        if r is not None:
            read_bytes += int(r)
            io_found = True
        if w is not None:
            write_bytes += int(w)
            io_found = True
    return (read_bytes, write_bytes) if io_found else None


def build_process_stats(
    psutil_module: Any,
    record: RunRecord,
    previous_io: tuple[int, int] | None,
    interval_seconds: float,
    system_net_delta: tuple[float, float] | None = None,
    gpu_usage: dict[int, tuple[int, float | None]] | None = None,
) -> ProcessStats:
    """Build sampled stats for one run with verified attribution and PID validation."""

    root, unavailable_reason = verify_run_process(psutil_module, record)
    if unavailable_reason is not None:
        return ProcessStats(
            record=record,
            process_count=0,
            thread_count=0,
            cpu_percent=None,
            rss_bytes=None,
            read_bytes_per_second=None,
            write_bytes_per_second=None,
            unavailable=unavailable_reason,
            sampled_at=utc_now_iso(),
            sampled_epoch=time.time(),
        )

    processes = get_process_tree(psutil_module, record.pid)
    if not processes:
        return ProcessStats(
            record=record,
            process_count=0,
            thread_count=0,
            cpu_percent=None,
            rss_bytes=None,
            read_bytes_per_second=None,
            write_bytes_per_second=None,
            unavailable="process unavailable",
            sampled_at=utc_now_iso(),
            sampled_epoch=time.time(),
        )

    process_count = len(processes)
    thread_count = 0
    cpu_percent = 0.0
    rss_bytes = 0
    read_bytes = 0
    write_bytes = 0
    io_supported = False
    pids: set[int] = set()

    for process in processes:
        pids.add(int(process.pid))
        with suppress(psutil_module.Error, OSError):
            thread_count += int(process.num_threads())
        with suppress(psutil_module.Error, OSError):
            cpu_percent += float(process.cpu_percent(interval=None))
        with suppress(psutil_module.Error, OSError):
            rss_bytes += int(process.memory_info().rss)
        counters = process_io(process, psutil_module=psutil_module)
        if counters is not None:
            r = getattr(counters, "read_bytes", None)
            w = getattr(counters, "write_bytes", None)
            if r is not None:
                read_bytes += int(r)
                io_supported = True
            if w is not None:
                write_bytes += int(w)
                io_supported = True

    elapsed = max(0.001, interval_seconds)
    if previous_io is None:
        read_rate = 0.0
        write_rate = 0.0
    else:
        read_rate = rate(previous_io[0], read_bytes, elapsed) or 0.0
        write_rate = rate(previous_io[1], write_bytes, elapsed) or 0.0

    try:
        cores = psutil_module.cpu_count(logical=True)
    except (psutil_module.Error, OSError, AttributeError):
        cores = None
    cores = max(1, int(cores or 1))
    cpu_percent_normalized = cpu_percent / cores

    gpu_memory = 0
    for pid in pids:
        if gpu_usage and pid in gpu_usage:
            memory, _ = gpu_usage[pid]
            gpu_memory += memory

    # Notice: system_net_delta is host-scoped. It is placed in host_net_*, NOT
    # in net_read_bytes_per_second / net_write_bytes_per_second!
    host_net_read, host_net_write = system_net_delta if system_net_delta else (None, None)

    return ProcessStats(
        record=record,
        process_count=process_count,
        thread_count=thread_count,
        cpu_percent=cpu_percent,
        cpu_percent_normalized=cpu_percent_normalized,
        cpu_count=cores,
        rss_bytes=rss_bytes,
        read_bytes_per_second=read_rate,
        write_bytes_per_second=write_rate,
        total_read_bytes=read_bytes if io_supported else None,
        total_write_bytes=write_bytes if io_supported else None,
        net_read_bytes_per_second=None,
        net_write_bytes_per_second=None,
        host_net_read_bytes_per_second=host_net_read,
        host_net_write_bytes_per_second=host_net_write,
        gpu_memory_bytes=gpu_memory or None,
        gpu_util_percent=None,
        sampled_at=utc_now_iso(),
        sample_interval_seconds=elapsed,
    )


def get_process_tree(psutil_module: Any, pid: int | None) -> list[Any]:
    """Return the root process and live child processes."""

    if pid is None or pid <= 0:
        return []
    processes = process_tree(pid, psutil_module=psutil_module)
    if not processes:
        return []
    live = [processes[0]]
    for process in processes[1:]:
        with suppress(psutil_module.Error, OSError):
            if not hasattr(process, "is_running") or process.is_running():
                live.append(process)
    return live


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
    separator = f"{'-' * 4} {'-' * 8} {'-' * 7} {'-' * 10} {'-' * 31} {'-' * 14} {'-' * 7} {'-' * 20}"
    rows.append(header)
    rows.append(colorize(separator, "2", enabled=color))
    command_width = max(12, width - 88)
    for item in stats:
        detail = item.unavailable or truncate(item.record.command_line, command_width)
        status = colorize(f"{item.record.status:<8}", status_color(item.record.status), enabled=color)
        if item.unavailable:
            cpu = colorize("     --", "90", enabled=color)
            rss = colorize("        --", "90", enabled=color)
            disk = colorize(f"{'--':<31}", "90", enabled=color)
        else:
            cpu_val = item.cpu_percent if item.cpu_percent is not None else 0.0
            cpu = colorize(f"{cpu_val:>6.1f}%", metric_color(cpu_val, 30, 75), enabled=color)
            rss_val = item.rss_bytes if item.rss_bytes is not None else 0
            rss = colorize(f"{format_bytes(rss_val):>10}", "36", enabled=color)
            read_rate = item.read_bytes_per_second if item.read_bytes_per_second is not None else 0.0
            write_rate = item.write_bytes_per_second if item.write_bytes_per_second is not None else 0.0
            disk_plain = f"R {format_bytes(read_rate):>10}/s W {format_bytes(write_rate):>10}/s"
            disk = colorize(f"{disk_plain:<31}", "36", enabled=color)
        gpu_plain = format_gpu_cell(item, color=False)
        gpu = colorize(f"{gpu_plain:<14}", "32" if gpu_plain != "--" else "90", enabled=color)
        procs_threads = colorize(f"{item.process_count}/{item.thread_count:<7}", "90", enabled=color)
        command = colorize(detail, "97", enabled=color)
        rows.append(f"{item.record.numeric_id:<4} {status} {cpu} {rss} {disk} {gpu} {procs_threads} {command}")
    if not stats:
        rows.append(colorize("No active runmux-managed processes.", "33", enabled=color))
    return "\n".join(rows) + "\n"


def format_stats_summary(stats: list[ProcessStats], *, color: bool) -> str:
    """Format a compact summary line for global counters."""

    total_cpu = sum(item.cpu_percent or 0.0 for item in stats)
    total_rss = sum(item.rss_bytes or 0 for item in stats)
    total_disk_read = sum(item.read_bytes_per_second or 0.0 for item in stats)
    total_disk_write = sum(item.write_bytes_per_second or 0.0 for item in stats)
    first = stats[0] if stats else None
    net_read = (
        first.host_net_read_bytes_per_second if first and first.host_net_read_bytes_per_second is not None else 0.0
    )
    net_write = (
        first.host_net_write_bytes_per_second if first and first.host_net_write_bytes_per_second is not None else 0.0
    )
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

    header = f"{'ID':<4} {'STATE':<8} {'CPU':>7} {'RAM':>10} {'DISK I/O':<31} {'GPU':<14} {'P/T':<7} COMMAND"
    return colorize(header, "1;37", enabled=color)


def format_gpu_cell(item: ProcessStats, *, color: bool) -> str:
    """Format GPU usage for one process row."""

    if item.gpu_memory_bytes is None and item.gpu_util_percent is None:
        return colorize("--", "90", enabled=color)
    memory = format_optional_bytes(item.gpu_memory_bytes)
    util = format_optional_percent(item.gpu_util_percent)
    return colorize(f"{memory}/{util}", "32", enabled=color)


def stats_to_json(item: ProcessStats) -> dict[str, Any]:
    """Convert process stats to JSON output with clear scope attribution."""

    return {
        "id": item.record.id,
        "numeric_id": item.record.numeric_id,
        "status": item.record.status,
        "pid": item.record.pid,
        "command_line": item.record.command_line,
        "process_count": item.process_count,
        "thread_count": item.thread_count,
        "cpu_percent": item.cpu_percent,
        "cpu_percent_normalized": item.cpu_percent_normalized,
        "cpu_count": item.cpu_count,
        "cpu_time_seconds": item.cpu_time_seconds,
        "rss_bytes": item.rss_bytes,
        "read_bytes_per_second": item.read_bytes_per_second,
        "write_bytes_per_second": item.write_bytes_per_second,
        "total_read_bytes": item.total_read_bytes,
        "total_write_bytes": item.total_write_bytes,
        "net_read_bytes_per_second": item.net_read_bytes_per_second,
        "net_write_bytes_per_second": item.net_write_bytes_per_second,
        "host_net_read_bytes_per_second": item.host_net_read_bytes_per_second,
        "host_net_write_bytes_per_second": item.host_net_write_bytes_per_second,
        "gpu_memory_bytes": item.gpu_memory_bytes,
        "gpu_util_percent": item.gpu_util_percent,
        "unavailable": item.unavailable,
        "sampled_at": item.sampled_at,
        "sample_interval_seconds": item.sample_interval_seconds,
    }


def snapshot_system_net(psutil_module: Any) -> tuple[int, int] | None:
    """Capture system network counters."""

    counters = net_io_counters()
    if counters is not None:
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
    elapsed = max(0.001, interval_seconds)
    return (
        rate(before[0], after[0], elapsed) or 0.0,
        rate(before[1], after[1], elapsed) or 0.0,
    )


def query_gpu_usage_by_pid() -> dict[int, tuple[int, float | None]]:
    """Return best-effort NVIDIA GPU memory keyed by process PID."""

    usage: dict[int, tuple[int, float | None]] = {}
    for item in gpu_process_memory(timeout=1.0):
        memory = item.get("memory_bytes")
        if memory is not None:
            usage[int(item["pid"])] = (int(memory), None)
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
