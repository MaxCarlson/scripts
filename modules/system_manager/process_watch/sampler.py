"""Framework-independent process sampling, topology aggregation, and churn tracking."""

from __future__ import annotations

import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

import psutil
from resource_metrics import CachedGpuMonitor

from .history import ProcessHistoryStore
from .models import (
    HostSummary,
    LifecycleEvent,
    MonitoringSnapshot,
    ProcessIdentity,
    ProcessSample,
    redact_sensitive_text,
)


@dataclass
class _PrevCounters:
    monotonic: float
    cpu_time: Optional[float]
    read_bytes: Optional[int]
    write_bytes: Optional[int]


def _extract_private_bytes(mem_info: Any) -> Optional[int]:
    if mem_info is None:
        return None
    for attr in ("private", "uss", "data"):
        val = getattr(mem_info, attr, None)
        if val is not None:
            return int(val)
    return None


def _extract_handles(proc: Any) -> Optional[int]:
    with suppress(psutil.Error, AttributeError, OSError, NotImplementedError):
        if hasattr(proc, "num_handles"):
            return int(proc.num_handles())
        if hasattr(proc, "num_fds"):
            return int(proc.num_fds())
    return None


class ProcessSampler:
    """Collects process snapshots with monotonic CPU/I/O deltas, topology, and bounded history."""

    def __init__(
        self,
        *,
        enable_gpu: bool = False,
        gpu_ttl_seconds: float = 4.0,
        exited_grace_seconds: float = 5.0,
        collect_details_for_all: bool = False,
        psutil_module: Any = psutil,
        gpu_monitor: Optional[CachedGpuMonitor] = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        history_store: Optional[ProcessHistoryStore] = None,
    ) -> None:
        self.enable_gpu = enable_gpu
        self.exited_grace_seconds = max(0.0, float(exited_grace_seconds))
        self.collect_details_for_all = collect_details_for_all
        self._psutil = psutil_module
        self._clock = monotonic_clock
        self._wall_clock = wall_clock
        self._gpu_monitor = gpu_monitor or CachedGpuMonitor(ttl_seconds=gpu_ttl_seconds, clock=monotonic_clock)
        self.history_store = history_store or ProcessHistoryStore()

        self._prev: Dict[ProcessIdentity, _PrevCounters] = {}
        self._known_live: Dict[ProcessIdentity, ProcessSample] = {}
        self._exited_cache: Dict[ProcessIdentity, Tuple[float, ProcessSample]] = {}
        self._first_seen: Dict[ProcessIdentity, float] = {}
        self._prev_disk_io: Optional[Tuple[float, int, int]] = None
        self._events: Deque[LifecycleEvent] = deque(maxlen=200)
        self._has_primed = False

    def sample(
        self,
        *,
        focus_identities: Optional[Set[ProcessIdentity]] = None,
        pinned_identities: Optional[Set[ProcessIdentity]] = None,
    ) -> MonitoringSnapshot:
        """Execute one sampling cycle and return a complete MonitoringSnapshot."""
        start_mono = self._clock()
        now_epoch = self._wall_clock()
        focus = set(focus_identities or ()) | set(pinned_identities or ())

        gpu_data: Optional[Dict[str, Any]] = None
        if self.enable_gpu:
            gpu_data = self._gpu_monitor.snapshot()

        gpu_proc_map: Dict[int, Dict[str, Any]] = (gpu_data or {}).get("process_memory", {})
        logical_cpus = max(1, int(self._psutil.cpu_count(logical=True) or 1))

        attrs = [
            "pid",
            "ppid",
            "name",
            "exe",
            "cmdline",
            "username",
            "status",
            "create_time",
            "cpu_times",
            "memory_info",
            "num_threads",
        ]
        if self.collect_details_for_all:
            attrs.append("cwd")

        live_samples: List[ProcessSample] = []
        live_by_ident: Dict[ProcessIdentity, ProcessSample] = {}
        new_prev: Dict[ProcessIdentity, _PrevCounters] = {}

        for proc in self._psutil.process_iter(attrs, ad_value=None):
            sample_mono = self._clock()
            try:
                info = getattr(proc, "info", None)
                if info is None:
                    info = proc.as_dict(attrs=attrs)
                pid = int(info.get("pid") or getattr(proc, "pid", 0))
                if pid <= 0:
                    continue
                create_time = info.get("create_time")
                if create_time is None:
                    with suppress(self._psutil.Error, OSError):
                        create_time = proc.create_time()
                create_time_f = float(create_time or 0.0)
                ident = ProcessIdentity(pid=pid, create_time=create_time_f)

                name = str(info.get("name") or f"pid-{pid}")
                ppid = int(info.get("ppid") or 0)
                exe = str(info.get("exe") or "")
                cmdline_list = info.get("cmdline")
                cmdline_raw = " ".join(str(part) for part in cmdline_list) if cmdline_list else ""
                cmdline_redacted = redact_sensitive_text(cmdline_raw)
                username = str(info.get("username") or "")
                status = str(info.get("status") or "")
                cwd = str(info.get("cwd") or "") if self.collect_details_for_all else ""

                cpu_times = info.get("cpu_times")
                cpu_time_sec: Optional[float] = None
                if cpu_times is not None:
                    cpu_time_sec = float(getattr(cpu_times, "user", 0.0)) + float(getattr(cpu_times, "system", 0.0))

                mem_info = info.get("memory_info")
                rss_bytes = int(mem_info.rss) if mem_info is not None and hasattr(mem_info, "rss") else None
                vms_bytes = int(mem_info.vms) if mem_info is not None and hasattr(mem_info, "vms") else None
                private_bytes = _extract_private_bytes(mem_info)

                num_threads = info.get("num_threads")
                num_threads_i = int(num_threads) if num_threads is not None else None
                num_handles_i = _extract_handles(proc) if (self.collect_details_for_all or ident in focus) else None

                io_read_bytes: Optional[int] = None
                io_write_bytes: Optional[int] = None
                access_denied = mem_info is None and cpu_times is None
                with suppress(self._psutil.Error, AttributeError, OSError, NotImplementedError):
                    io_c = proc.io_counters()
                    if io_c is not None:
                        io_read_bytes = int(getattr(io_c, "read_bytes", 0))
                        io_write_bytes = int(getattr(io_c, "write_bytes", 0))

                prev = self._prev.get(ident)
                cpu_pct: Optional[float] = None
                cpu_norm: Optional[float] = None
                io_read_rate: Optional[float] = None
                io_write_rate: Optional[float] = None
                io_total_rate: Optional[float] = None

                if prev is not None:
                    elapsed = sample_mono - prev.monotonic
                    if elapsed > 0:
                        if cpu_time_sec is not None and prev.cpu_time is not None:
                            delta_cpu = cpu_time_sec - prev.cpu_time
                            if delta_cpu >= 0:
                                cpu_pct = (delta_cpu / elapsed) * 100.0
                                cpu_norm = cpu_pct / logical_cpus
                        if io_read_bytes is not None and prev.read_bytes is not None:
                            delta_r = io_read_bytes - prev.read_bytes
                            if delta_r >= 0:
                                io_read_rate = delta_r / elapsed
                        if io_write_bytes is not None and prev.write_bytes is not None:
                            delta_w = io_write_bytes - prev.write_bytes
                            if delta_w >= 0:
                                io_write_rate = delta_w / elapsed
                        if io_read_rate is not None or io_write_rate is not None:
                            io_total_rate = (io_read_rate or 0.0) + (io_write_rate or 0.0)

                new_prev[ident] = _PrevCounters(
                    monotonic=sample_mono,
                    cpu_time=cpu_time_sec,
                    read_bytes=io_read_bytes,
                    write_bytes=io_write_bytes,
                )

                gpu_entry = gpu_proc_map.get(pid)
                gpu_mem = gpu_entry.get("memory_bytes") if gpu_entry else None
                gpu_id = gpu_entry.get("gpu_id") if gpu_entry else None
                gpu_prov = gpu_entry.get("provenance") if gpu_entry else None

                uptime = max(0.0, now_epoch - create_time_f) if create_time_f > 0 else None
                first_seen = self._first_seen.setdefault(ident, sample_mono)
                is_new = self._has_primed and ident not in self._known_live

                sample = ProcessSample(
                    identity=ident,
                    pid=pid,
                    ppid=ppid,
                    name=name,
                    exe=exe,
                    cmdline_redacted=cmdline_redacted,
                    cmdline_raw=cmdline_raw,
                    cwd=cwd,
                    username=username,
                    status=status,
                    create_time=create_time_f,
                    uptime_seconds=uptime,
                    cpu_percent=cpu_pct,
                    cpu_percent_normalized=cpu_norm,
                    cpu_time_seconds=cpu_time_sec,
                    rss_bytes=rss_bytes,
                    private_bytes=private_bytes,
                    vms_bytes=vms_bytes,
                    io_read_bytes=io_read_bytes,
                    io_write_bytes=io_write_bytes,
                    io_read_rate=io_read_rate,
                    io_write_rate=io_write_rate,
                    io_total_rate=io_total_rate,
                    num_threads=num_threads_i,
                    num_handles=num_handles_i,
                    gpu_memory_bytes=gpu_mem,
                    gpu_id=gpu_id,
                    gpu_util_percent=None,  # Never fabricate per-process GPU util from device util
                    gpu_provenance=gpu_prov,
                    is_new=is_new,
                    is_exited=False,
                    access_denied=access_denied,
                    first_seen_monotonic=first_seen,
                    last_seen_monotonic=sample_mono,
                )
                live_samples.append(sample)
                live_by_ident[ident] = sample
            except (self._psutil.NoSuchProcess, self._psutil.ZombieProcess, self._psutil.AccessDenied, OSError):
                continue

        # Detect lifecycle churn (started / exited)
        if self._has_primed:
            for ident, sample in live_by_ident.items():
                if ident not in self._known_live:
                    self._events.append(LifecycleEvent(now_epoch, ident, sample.name, "started"))

        for ident, prev_sample in self._known_live.items():
            if ident not in live_by_ident:
                self._events.append(LifecycleEvent(now_epoch, ident, prev_sample.name, "exited"))
                exited_copy = ProcessSample(
                    identity=prev_sample.identity,
                    pid=prev_sample.pid,
                    ppid=prev_sample.ppid,
                    name=prev_sample.name,
                    exe=prev_sample.exe,
                    cmdline_redacted=prev_sample.cmdline_redacted,
                    cmdline_raw="",
                    cwd=prev_sample.cwd,
                    username=prev_sample.username,
                    status="exited",
                    create_time=prev_sample.create_time,
                    uptime_seconds=prev_sample.uptime_seconds,
                    cpu_percent=None,
                    cpu_percent_normalized=None,
                    cpu_time_seconds=prev_sample.cpu_time_seconds,
                    rss_bytes=prev_sample.rss_bytes,
                    private_bytes=prev_sample.private_bytes,
                    vms_bytes=prev_sample.vms_bytes,
                    io_read_bytes=prev_sample.io_read_bytes,
                    io_write_bytes=prev_sample.io_write_bytes,
                    io_read_rate=None,
                    io_write_rate=None,
                    io_total_rate=None,
                    num_threads=prev_sample.num_threads,
                    num_handles=prev_sample.num_handles,
                    gpu_memory_bytes=None,
                    gpu_id=prev_sample.gpu_id,
                    gpu_util_percent=None,
                    gpu_provenance=prev_sample.gpu_provenance,
                    is_new=False,
                    is_exited=True,
                    access_denied=prev_sample.access_denied,
                    first_seen_monotonic=prev_sample.first_seen_monotonic,
                    last_seen_monotonic=prev_sample.last_seen_monotonic,
                    peak_cpu_percent=prev_sample.peak_cpu_percent,
                    peak_cpu_at=prev_sample.peak_cpu_at,
                    peak_rss_bytes=prev_sample.peak_rss_bytes,
                    peak_rss_at=prev_sample.peak_rss_at,
                    peak_io_rate=prev_sample.peak_io_rate,
                    peak_io_at=prev_sample.peak_io_at,
                )
                self._exited_cache[ident] = (start_mono, exited_copy)

        # Prune expired exited entries unless pinned/focused
        expired = [
            ident
            for ident, (exited_at, _) in self._exited_cache.items()
            if ident in live_by_ident or ((start_mono - exited_at) > self.exited_grace_seconds and ident not in focus)
        ]
        for ident in expired:
            del self._exited_cache[ident]

        # Build single-pass topology & non-double-counted subtree aggregates for live processes
        children_map = _build_topology_and_aggregates(live_samples)

        # Record bounded history & update peaks
        self.history_store.record_cycle(
            now_epoch,
            live_samples,
            focus_identities=focus,
            live_identities=set(live_by_ident.keys()),
        )

        # Host summary
        host = self._collect_host_summary(
            start_mono=start_mono,
            logical_cpus=logical_cpus,
            total_processes=len(live_samples),
            gpu_data=gpu_data,
        )

        self._prev = new_prev
        self._known_live = live_by_ident
        self._has_primed = True

        # Combine live + retained exited samples
        all_samples = list(live_samples)
        by_identity = dict(live_by_ident)
        for ident, (_, exited_sample) in self._exited_cache.items():
            if ident not in by_identity:
                all_samples.append(exited_sample)
                by_identity[ident] = exited_sample

        return MonitoringSnapshot(
            sampled_at_epoch=now_epoch,
            sampled_at_monotonic=start_mono,
            host=host,
            processes=all_samples,
            by_identity=by_identity,
            children_map=children_map,
            events=list(self._events),
        )

    def _collect_host_summary(
        self,
        *,
        start_mono: float,
        logical_cpus: int,
        total_processes: int,
        gpu_data: Optional[Dict[str, Any]],
    ) -> HostSummary:
        cpu_pct = 0.0
        with suppress(Exception):
            cpu_pct = float(self._psutil.cpu_percent(interval=None))

        mem_used = 0
        mem_total = 0
        mem_pct = 0.0
        with suppress(Exception):
            vm = self._psutil.virtual_memory()
            mem_used = int(vm.used)
            mem_total = int(vm.total)
            mem_pct = float(vm.percent)

        disk_r: Optional[float] = None
        disk_w: Optional[float] = None
        with suppress(Exception):
            dio = self._psutil.disk_io_counters()
            if dio is not None:
                now_d = self._clock()
                r_b = int(dio.read_bytes)
                w_b = int(dio.write_bytes)
                if self._prev_disk_io is not None:
                    prev_t, prev_r, prev_w = self._prev_disk_io
                    dt = now_d - prev_t
                    if dt > 0 and r_b >= prev_r and w_b >= prev_w:
                        disk_r = (r_b - prev_r) / dt
                        disk_w = (w_b - prev_w) / dt
                self._prev_disk_io = (now_d, r_b, w_b)

        duration_ms = max(0.0, (self._clock() - start_mono) * 1000.0)
        return HostSummary(
            cpu_percent=cpu_pct,
            cpu_count=logical_cpus,
            mem_used_bytes=mem_used,
            mem_total_bytes=mem_total,
            mem_percent=mem_pct,
            disk_read_rate=disk_r,
            disk_write_rate=disk_w,
            gpu_backend=(gpu_data or {}).get("backend", "unavailable"),
            gpu_age_seconds=(gpu_data or {}).get("age_seconds"),
            gpu_devices=(gpu_data or {}).get("devices", []),
            gpu_limitations=(gpu_data or {}).get("limitations"),
            sample_duration_ms=duration_ms,
            total_processes=total_processes,
            matched_processes=total_processes,
        )

    def inspect_process_details(self, identity: ProcessIdentity) -> Dict[str, Any]:
        """Fetch extra on-demand details (cwd, handles, ancestry) for a single process."""
        details: Dict[str, Any] = {}
        proc_cls = getattr(self._psutil, "Process", None)
        if proc_cls is None:
            return details
        try:
            proc = proc_cls(identity.pid)
            if abs(float(proc.create_time()) - identity.create_time) > 1.0:
                return {"exited": True}
            with suppress(self._psutil.Error, OSError):
                details["cwd"] = proc.cwd()
            handles = _extract_handles(proc)
            if handles is not None:
                details["num_handles"] = handles
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, OSError):
            details["access_denied"] = True
        return details


def _build_topology_and_aggregates(samples: List[ProcessSample]) -> Dict[int, List[int]]:
    """Build parent->children map once and compute O(N) non-double-counted subtree aggregates."""
    by_pid: Dict[int, ProcessSample] = {s.pid: s for s in samples}
    children_map: Dict[int, List[int]] = {}
    for s in samples:
        if s.ppid and s.ppid != s.pid and s.ppid in by_pid:
            children_map.setdefault(s.ppid, []).append(s.pid)
        s.child_count = 0

    for ppid, kids in children_map.items():
        by_pid[ppid].child_count = len(kids)

    # Compute depth in O(N) using memoization + cycle guard
    depth_memo: Dict[int, int] = {}
    for s in samples:
        if s.pid in depth_memo:
            s.depth = depth_memo[s.pid]
            continue
        path: List[int] = []
        seen: Set[int] = set()
        cur_pid: Optional[int] = s.pid
        base_depth = 0
        while cur_pid is not None and cur_pid in by_pid and cur_pid not in seen:
            if cur_pid in depth_memo:
                base_depth = depth_memo[cur_pid]
                break
            seen.add(cur_pid)
            path.append(cur_pid)
            ppid = by_pid[cur_pid].ppid
            cur_pid = ppid if (ppid and ppid != cur_pid and ppid in by_pid) else None
        for offset, pid in enumerate(reversed(path)):
            d = base_depth + offset + (1 if cur_pid is not None and cur_pid in depth_memo else 0)
            depth_memo[pid] = d
            by_pid[pid].depth = d

    # Bottom-up iterative post-order DP: O(N) across both shallow and deep trees.
    # state: 0=unvisited, 1=visiting (cycle guard), 2=done
    state: Dict[int, int] = {}
    for s in samples:
        if state.get(s.pid, 0) != 0:
            continue
        stack: List[Tuple[int, bool]] = [(s.pid, False)]
        while stack:
            pid, expanded = stack.pop()
            if not expanded:
                if state.get(pid, 0) != 0:
                    continue
                state[pid] = 1
                stack.append((pid, True))
                for child_pid in children_map.get(pid, ()):
                    if state.get(child_pid, 0) == 0:
                        stack.append((child_pid, False))
            else:
                node = by_pid[pid]
                desc = 0
                cpu_sum = node.cpu_percent if node.cpu_percent is not None else 0.0
                has_cpu = node.cpu_percent is not None
                rss_sum = node.rss_bytes if node.rss_bytes is not None else 0
                has_rss = node.rss_bytes is not None
                r_sum = node.io_read_rate if node.io_read_rate is not None else 0.0
                has_r = node.io_read_rate is not None
                w_sum = node.io_write_rate if node.io_write_rate is not None else 0.0
                has_w = node.io_write_rate is not None

                for child_pid in children_map.get(pid, ()):
                    if state.get(child_pid) == 2:
                        cnode = by_pid[child_pid]
                        desc += 1 + cnode.descendant_count
                        if cnode.subtree_cpu_percent is not None:
                            cpu_sum += cnode.subtree_cpu_percent
                            has_cpu = True
                        if cnode.subtree_rss_bytes is not None:
                            rss_sum += cnode.subtree_rss_bytes
                            has_rss = True
                        if cnode.subtree_io_read_rate is not None:
                            r_sum += cnode.subtree_io_read_rate
                            has_r = True
                        if cnode.subtree_io_write_rate is not None:
                            w_sum += cnode.subtree_io_write_rate
                            has_w = True

                node.descendant_count = desc
                node.subtree_cpu_percent = cpu_sum if has_cpu else None
                node.subtree_rss_bytes = rss_sum if has_rss else None
                node.subtree_io_read_rate = r_sum if has_r else None
                node.subtree_io_write_rate = w_sum if has_w else None
                state[pid] = 2

    return children_map


def get_ancestry_chain(sample: ProcessSample, by_pid: Dict[int, ProcessSample]) -> List[ProcessSample]:
    """Return ancestry chain from root ancestor down to the given process."""
    chain: List[ProcessSample] = [sample]
    seen = {sample.pid}
    cur = sample
    while cur.ppid and cur.ppid in by_pid and cur.ppid not in seen:
        seen.add(cur.ppid)
        parent = by_pid[cur.ppid]
        chain.append(parent)
        cur = parent
    chain.reverse()
    return chain


def sample_once(
    sampler: ProcessSampler,
    *,
    interval_seconds: float = 1.0,
) -> MonitoringSnapshot:
    """Perform a prime sample, wait interval_seconds, and return a delta-populated snapshot."""
    sampler.sample()
    if interval_seconds > 0:
        time.sleep(interval_seconds)
    return sampler.sample()
