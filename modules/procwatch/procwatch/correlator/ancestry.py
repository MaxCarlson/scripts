"""Process table cache, Toolhelp32 seeding, PID-reuse-safe ancestry, and venv shim collapsing."""

from __future__ import annotations

from collections import OrderedDict
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import threading
import time
import uuid

import psutil

from procwatch.correlator.decoders import decode_command_payload
from procwatch.models import (
    CapabilityFlags,
    MissingMetadataReason,
    ProcessIdentity,
    ProcessObservation,
    utc_now_iso,
)
from procwatch.redactor import redact_text

_BOOT_ID_CACHE: str | None = None


def get_boot_id() -> str:
    """Return a boot-scoped identifier derived from OS boot time."""
    global _BOOT_ID_CACHE
    if _BOOT_ID_CACHE is not None:
        return _BOOT_ID_CACHE
    try:
        boot_ts = int(psutil.boot_time())
        _BOOT_ID_CACHE = f"boot-{boot_ts}"
    except Exception:
        _BOOT_ID_CACHE = f"session-{uuid.uuid4().hex[:12]}"
    return _BOOT_ID_CACHE


def _read_windows_process_create_100ns(pid: int) -> int | None:
    """Query exact kernel process creation time (100ns FILETIME) on Windows if accessible."""
    if sys.platform != "win32" or pid <= 0:
        return None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        create_ft = wintypes.FILETIME()
        exit_ft = wintypes.FILETIME()
        kernel_ft = wintypes.FILETIME()
        user_ft = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(create_ft),
            ctypes.byref(exit_ft),
            ctypes.byref(kernel_ft),
            ctypes.byref(user_ft),
        )
        if not ok:
            return None
        return (int(create_ft.dwHighDateTime) << 32) | int(create_ft.dwLowDateTime)
    finally:
        kernel32.CloseHandle(handle)


def _snapshot_toolhelp32_windows() -> list[tuple[int, int, str]]:
    """Return [(pid, ppid, exe_name), ...] via CreateToolhelp32Snapshot on Windows."""
    if sys.platform != "win32":
        return []

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return []
    entries: list[tuple[int, int, str]] = []
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if kernel32.Process32FirstW(snap, ctypes.byref(pe)):
            while True:
                entries.append((int(pe.th32ProcessID), int(pe.th32ParentProcessID), str(pe.szExeFile)))
                if not kernel32.Process32NextW(snap, ctypes.byref(pe)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return entries


def _is_venv_python_shim(proc: ProcessObservation) -> bool:
    """Return True if process looks like a .venv\\Scripts\\python.exe launcher shim."""
    path_or_cmd = (proc.image_path or proc.command_line_redacted or "").lower().replace("/", "\\")
    name = proc.image_name.lower()
    return ("python" in name) and ("\\.venv\\scripts\\" in path_or_cmd or "\\venv\\scripts\\" in path_or_cmd)


def collapse_venv_shims(chain: list[ProcessObservation]) -> list[ProcessObservation]:
    """Collapse .venv\\Scripts\\python.exe -> base python.exe shim pairs for display.

    Preserves the underlying raw chain separately; never mutates input nodes.
    """
    if len(chain) < 2:
        return list(chain)
    collapsed: list[ProcessObservation] = []
    skip_next = False
    for idx, node in enumerate(chain):
        if skip_next:
            skip_next = False
            continue
        if idx + 1 < len(chain):
            parent = chain[idx + 1]
            if (
                node.image_name.lower().startswith("python")
                and _is_venv_python_shim(parent)
                and node.ppid == parent.identity.pid
            ):
                # Keep the child (or venv shim) with annotated display; skip duplicate base python
                collapsed.append(node)
                skip_next = True
                continue
        collapsed.append(node)
    return collapsed


class ProcessTableCache:
    """Thread-safe, PID-reuse-aware process cache with Toolhelp32/psutil seeding."""

    def __init__(
        self,
        *,
        boot_id: str | None = None,
        max_entries: int = 8192,
        ttl_seconds: float = 300.0,
    ) -> None:
        self.boot_id = boot_id or get_boot_id()
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._processes: OrderedDict[str, ProcessObservation] = OrderedDict()
        self._active_by_pid: dict[int, str] = {}

    def seed_from_snapshot(self) -> int:
        """Seed cache with currently running processes. Returns number of seeded records."""
        count = 0
        if sys.platform == "win32":
            entries = _snapshot_toolhelp32_windows()
            now_ns = time.monotonic_ns()
            for pid, ppid, exe_name in entries:
                if pid <= 0:
                    continue
                create_100ns = _read_windows_process_create_100ns(pid)
                if create_100ns is not None:
                    ident = ProcessIdentity.canonical_kernel(self.boot_id, pid, create_100ns)
                else:
                    ident = ProcessIdentity.provisional(self.boot_id, pid, now_ns)
                obs = ProcessObservation(
                    identity=ident,
                    ppid=ppid,
                    image_name=exe_name,
                    start_ts_utc=utc_now_iso(),
                    start_monotonic_ns=now_ns,
                    source="toolhelp32_snapshot",
                    capabilities=CapabilityFlags(process_created=True),
                )
                self._enrich_from_psutil(obs, pid)
                self.record_observation(obs)
                count += 1
            return count

        # Cross-platform fallback via psutil
        now_ns = time.monotonic_ns()
        for proc in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time"]):
            try:
                info = proc.info
                pid = int(info["pid"])
                if pid <= 0:
                    continue
                ctime = info.get("create_time")
                if ctime is not None:
                    ident = ProcessIdentity.canonical_kernel(self.boot_id, pid, int(ctime * 10_000_000))
                else:
                    ident = ProcessIdentity.provisional(self.boot_id, pid, now_ns)
                raw_cmd = " ".join(info["cmdline"]) if info.get("cmdline") else None
                red_cmd = redact_text(raw_cmd, escape_controls=True) if raw_cmd else None
                decoded = decode_command_payload(raw_cmd) if raw_cmd else None
                obs = ProcessObservation(
                    identity=ident,
                    ppid=int(info["ppid"]) if info.get("ppid") is not None else None,
                    image_name=str(info.get("name") or ""),
                    image_path=str(info["exe"]) if info.get("exe") else None,
                    command_line_redacted=red_cmd,
                    decoded_payload_redacted=decoded.redacted_text if decoded else None,
                    start_ts_utc=utc_now_iso(),
                    start_monotonic_ns=now_ns,
                    source="psutil_snapshot",
                    capabilities=CapabilityFlags(
                        process_created=True,
                        command_line_captured=bool(red_cmd),
                    ),
                )
                self.record_observation(obs)
                count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return count

    def _enrich_from_psutil(self, obs: ProcessObservation, pid: int) -> None:
        """Best-effort enrichment of image_path and command line via psutil."""
        try:
            proc = psutil.Process(pid)
            exe = proc.exe()
            if exe:
                obs.image_path = exe
                if not obs.image_name:
                    obs.image_name = Path(exe).name
            cmdline_list = proc.cmdline()
            if cmdline_list:
                raw_cmd = " ".join(cmdline_list)
                obs.command_line_redacted = redact_text(raw_cmd, escape_controls=True)
                obs.capabilities.command_line_captured = True
                decoded = decode_command_payload(raw_cmd)
                if decoded and decoded.redacted_text:
                    obs.decoded_payload_redacted = decoded.redacted_text
        except psutil.AccessDenied:
            obs.add_missing_reason(MissingMetadataReason.ACCESS_DENIED)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            obs.add_missing_reason(MissingMetadataReason.EXITED_BEFORE_ENRICHMENT)
        except Exception:
            obs.add_missing_reason(MissingMetadataReason.UNKNOWN)

    def record_observation(self, obs: ProcessObservation) -> ProcessObservation:
        """Insert or update a process observation, handling PID reuse safely."""
        with self._lock:
            pid = obs.identity.pid
            existing_key = self._active_by_pid.get(pid)
            if existing_key and existing_key != obs.identity.proc_key:
                prev = self._processes.get(existing_key)
                if prev is not None and prev.is_alive:
                    # PID was reused before a stop event was seen for the previous lifetime
                    prev.exit_reason = "pid_reused"
                    prev.exit_monotonic_ns = obs.start_monotonic_ns or time.monotonic_ns()
                    prev.exit_ts_utc = prev.exit_ts_utc or utc_now_iso()

            self._processes[obs.identity.proc_key] = obs
            self._processes.move_to_end(obs.identity.proc_key)
            if obs.is_alive:
                self._active_by_pid[pid] = obs.identity.proc_key
            self._prune_if_needed()
            return obs

    def record_start(
        self,
        *,
        pid: int,
        ppid: int | None,
        image_name: str,
        session_id: int | None = None,
        command_line: str | None = None,
        source: str = "wmi_trace",
        monotonic_ns: int | None = None,
        enrich_live: bool = True,
    ) -> ProcessObservation:
        """Record a new process start event and optionally enrich live metadata."""
        now_ns = monotonic_ns if monotonic_ns is not None else time.monotonic_ns()
        create_100ns = _read_windows_process_create_100ns(pid) if enrich_live else None
        if create_100ns is not None:
            ident = ProcessIdentity.canonical_kernel(self.boot_id, pid, create_100ns)
        else:
            ident = ProcessIdentity.provisional(self.boot_id, pid, now_ns)

        red_cmd = redact_text(command_line, escape_controls=True) if command_line else None
        decoded = decode_command_payload(command_line) if command_line else None

        obs = ProcessObservation(
            identity=ident,
            ppid=ppid,
            image_name=image_name,
            command_line_redacted=red_cmd,
            decoded_payload_redacted=decoded.redacted_text if decoded else None,
            session_id=session_id,
            start_ts_utc=utc_now_iso(),
            start_monotonic_ns=now_ns,
            source=source,
            capabilities=CapabilityFlags(
                process_created=True,
                command_line_captured=bool(red_cmd),
            ),
        )
        if enrich_live and not red_cmd:
            self._enrich_from_psutil(obs, pid)
        return self.record_observation(obs)

    def record_stop(
        self,
        *,
        pid: int,
        exit_code: int | None = None,
        exit_code_known: bool = False,
        monotonic_ns: int | None = None,
    ) -> ProcessObservation | None:
        """Mark the active lifetime for `pid` as terminated."""
        now_ns = monotonic_ns if monotonic_ns is not None else time.monotonic_ns()
        with self._lock:
            key = self._active_by_pid.pop(pid, None)
            if key is None:
                return None
            obs = self._processes.get(key)
            if obs is None:
                return None
            obs.exit_ts_utc = utc_now_iso()
            obs.exit_monotonic_ns = now_ns
            obs.capabilities.process_terminated = True
            if exit_code_known and exit_code is not None:
                obs.exit_code = exit_code
                obs.capabilities.exit_code_known = True
            return obs

    def lookup_or_enrich_pid(self, pid: int) -> ProcessObservation | None:
        """Return active observation for PID, or perform on-demand Toolhelp/psutil lookup."""
        if pid <= 0:
            return None
        with self._lock:
            key = self._active_by_pid.get(pid)
            if key and key in self._processes:
                return self._processes[key]

        # On-demand lookup for processes started before or missed by trace
        now_ns = time.monotonic_ns()
        create_100ns = _read_windows_process_create_100ns(pid)
        try:
            proc = psutil.Process(pid)
            ppid = proc.ppid()
            name = proc.name()
            if create_100ns is None:
                ctime = proc.create_time()
                create_100ns = int(ctime * 10_000_000)
            ident = ProcessIdentity.canonical_kernel(self.boot_id, pid, create_100ns)
            obs = ProcessObservation(
                identity=ident,
                ppid=ppid,
                image_name=name,
                start_ts_utc=utc_now_iso(),
                start_monotonic_ns=now_ns,
                source="on_demand_psutil",
                capabilities=CapabilityFlags(process_created=True),
            )
            self._enrich_from_psutil(obs, pid)
            return self.record_observation(obs)
        except psutil.AccessDenied:
            ident = ProcessIdentity.provisional(self.boot_id, pid, now_ns)
            obs = ProcessObservation(
                identity=ident,
                image_name="<access_denied>",
                start_ts_utc=utc_now_iso(),
                start_monotonic_ns=now_ns,
                source="on_demand_psutil",
            )
            obs.add_missing_reason(MissingMetadataReason.ACCESS_DENIED)
            return self.record_observation(obs)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return None

    def get_by_key(self, proc_key: str) -> ProcessObservation | None:
        with self._lock:
            return self._processes.get(proc_key)

    def get_ancestry(self, proc_key: str, *, max_depth: int = 16) -> tuple[list[ProcessObservation], bool]:
        """Walk parent chain from `proc_key` upward.

        Returns (chain, ancestry_complete). Never invents missing parents or joins across PID reuse.
        """
        with self._lock:
            start = self._processes.get(proc_key)
            if start is None:
                return [], False

            chain: list[ProcessObservation] = [start]
            seen_keys = {proc_key}
            current = start
            complete = True

            for _ in range(max_depth):
                ppid = current.ppid
                if ppid is None or ppid <= 0 or ppid == current.identity.pid:
                    break
                parent_key = self._active_by_pid.get(ppid)
                parent = self._processes.get(parent_key) if parent_key else None

                # If not active, check most recent exited process with matching pid that started <= child
                if parent is None:
                    candidates = [
                        p
                        for p in reversed(self._processes.values())
                        if p.identity.pid == ppid
                        and (
                            p.start_monotonic_ns is None
                            or current.start_monotonic_ns is None
                            or p.start_monotonic_ns <= current.start_monotonic_ns
                        )
                    ]
                    parent = candidates[0] if candidates else None

                if parent is None:
                    # Try live lookup if parent might have existed before snapshot
                    parent = self.lookup_or_enrich_pid(ppid)

                if parent is None:
                    complete = False
                    current.add_missing_reason(MissingMetadataReason.EXITED_BEFORE_ENRICHMENT)
                    break

                if parent.identity.proc_key in seen_keys:
                    break
                seen_keys.add(parent.identity.proc_key)
                chain.append(parent)
                current = parent

            start.capabilities.ancestry_complete = complete
            return chain, complete

    def recent_processes(self, *, since_monotonic_ns: int = 0) -> list[ProcessObservation]:
        """Return processes started at or after `since_monotonic_ns`, newest first."""
        with self._lock:
            result = [
                p
                for p in reversed(self._processes.values())
                if (p.start_monotonic_ns or 0) >= since_monotonic_ns
            ]
            return result

    def refresh_recent_processes(self, *, window_ms: float = 2000.0) -> int:
        """Discover recently started live processes quickly without scanning all cmdlines."""
        now_wall = time.time()
        now_ns = time.monotonic_ns()
        cutoff_wall = now_wall - (window_ms / 1000.0)
        added = 0

        if sys.platform == "win32":
            entries = _snapshot_toolhelp32_windows()
            candidate_pids: list[tuple[int, int, str]] = []
            with self._lock:
                for pid, ppid, exe_name in entries:
                    if pid > 0 and pid not in self._active_by_pid:
                        candidate_pids.append((pid, ppid, exe_name))
            for pid, ppid, exe_name in candidate_pids:
                try:
                    proc = psutil.Process(pid)
                    ctime = float(proc.create_time())
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                if ctime < cutoff_wall:
                    continue
                age_ns = max(0, int((now_wall - ctime) * 1_000_000_000))
                est_start_ns = max(0, now_ns - age_ns)
                create_100ns = _read_windows_process_create_100ns(pid) or int(ctime * 10_000_000)
                ident = ProcessIdentity.canonical_kernel(self.boot_id, pid, create_100ns)
                obs = ProcessObservation(
                    identity=ident,
                    ppid=ppid,
                    image_name=exe_name,
                    start_ts_utc=utc_now_iso(),
                    start_monotonic_ns=est_start_ns,
                    source="toolhelp32_recent_refresh",
                    capabilities=CapabilityFlags(process_created=True),
                )
                self._enrich_from_psutil(obs, pid)
                self.record_observation(obs)
                added += 1
            return added

        for proc in psutil.process_iter(["pid", "create_time"]):
            try:
                info = proc.info
                pid = int(info["pid"])
                if pid <= 0:
                    continue
                ctime = info.get("create_time")
                if ctime is None or float(ctime) < cutoff_wall:
                    continue
                with self._lock:
                    if pid in self._active_by_pid:
                        continue
                age_ns = max(0, int((now_wall - float(ctime)) * 1_000_000_000))
                est_start_ns = max(0, now_ns - age_ns)
                ident = ProcessIdentity.canonical_kernel(self.boot_id, pid, int(float(ctime) * 10_000_000))
                obs = ProcessObservation(
                    identity=ident,
                    ppid=proc.ppid(),
                    image_name=proc.name(),
                    start_ts_utc=utc_now_iso(),
                    start_monotonic_ns=est_start_ns,
                    source="psutil_recent_refresh",
                    capabilities=CapabilityFlags(process_created=True),
                )
                self._enrich_from_psutil(obs, pid)
                self.record_observation(obs)
                added += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return added

    def _prune_if_needed(self) -> None:
        cutoff_ns = time.monotonic_ns() - int(self.ttl_seconds * 1_000_000_000)
        while len(self._processes) > self.max_entries:
            oldest_key, oldest_obs = next(iter(self._processes.items()))
            self._processes.pop(oldest_key, None)
            if self._active_by_pid.get(oldest_obs.identity.pid) == oldest_key:
                self._active_by_pid.pop(oldest_obs.identity.pid, None)
        # Also prune exited entries older than TTL
        to_delete: list[str] = []
        for key, obs in self._processes.items():
            if not obs.is_alive and (obs.exit_monotonic_ns or 0) < cutoff_ns:
                to_delete.append(key)
            else:
                break
        for key in to_delete:
            self._processes.pop(key, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._processes)
