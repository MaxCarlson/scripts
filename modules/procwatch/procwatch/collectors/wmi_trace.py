"""Event-driven WMI Win32_ProcessStartTrace / Win32_ProcessStopTrace collector."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import sys
import threading
import time
from typing import Any

from procwatch.models import CollectorStats, MissingMetadataReason, utc_now_iso

WBEM_E_ACCESS_DENIED = -2147217405  # 0x80041003
WBEM_E_TIMED_OUT = -2147209215  # 0x80043001


@dataclass(slots=True)
class WmiProcessEvent:
    """Lightweight event emitted by WmiProcessTraceCollector."""

    kind: str  # "start" | "stop"
    pid: int
    ppid: int | None
    process_name: str
    session_id: int | None = None
    exit_status: int | None = None
    exit_code_known: bool = False
    timestamp_utc: str = ""
    monotonic_ns: int = 0


def _extract_com_hresult(exc: Exception) -> int | None:
    """Extract the inner WMI HRESULT from a pywintypes.com_error if present."""
    args = getattr(exc, "args", ())
    if len(args) >= 3 and isinstance(args[2], tuple) and len(args[2]) >= 6:
        code = args[2][5]
        if isinstance(code, int):
            return code
    if args and isinstance(args[0], int):
        return args[0]
    return None


class WmiProcessTraceCollector:
    """Subscribes to Win32_ProcessStartTrace and Win32_ProcessStopTrace on COM threads."""

    def __init__(
        self,
        *,
        event_queue: queue.Queue[WmiProcessEvent] | None = None,
        stats: CollectorStats | None = None,
        poll_timeout_ms: int = 200,
    ) -> None:
        self.event_queue = event_queue or queue.Queue(maxsize=4096)
        self.stats = stats or CollectorStats()
        self.poll_timeout_ms = poll_timeout_ms
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._ready_events: list[threading.Event] = []
        self.status: str = "uninitialized"
        self.last_error: str | None = None
        self.missing_reason: MissingMetadataReason | None = None

    def start(self, *, timeout: float = 3.0) -> str:
        """Start background WMI trace subscription threads. Returns collector status."""
        if sys.platform != "win32":
            self.status = "unavailable"
            self.missing_reason = MissingMetadataReason.SOURCE_UNAVAILABLE
            self.last_error = "WMI process trace requires Windows (win32)."
            self.stats.wmi_status = self.status
            return self.status

        if any(t.is_alive() for t in self._threads):
            return self.status

        self._stop_event.clear()
        self._threads.clear()
        self._ready_events.clear()
        self.status = "starting"
        self.last_error = None
        self.missing_reason = None

        for kind, query in (
            ("start", "SELECT * FROM Win32_ProcessStartTrace"),
            ("stop", "SELECT * FROM Win32_ProcessStopTrace"),
        ):
            ready = threading.Event()
            self._ready_events.append(ready)
            t = threading.Thread(
                target=self._run_trace_loop,
                args=(kind, query, ready),
                name=f"procwatch-wmi-{kind}",
                daemon=True,
            )
            self._threads.append(t)
            t.start()

        for ready in self._ready_events:
            ready.wait(timeout=timeout)

        if self.status == "starting":
            self.status = "active"
        self.stats.wmi_status = self.status
        return self.status

    def stop(self, *, timeout: float = 2.0) -> None:
        """Signal WMI trace threads to exit cleanly and join them."""
        self._stop_event.set()
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=timeout)
        self._threads.clear()

    def _run_trace_loop(self, kind: str, query: str, ready: threading.Event) -> None:
        import pythoncom  # type: ignore[import-not-found]
        import win32com.client  # type: ignore[import-not-found]

        pythoncom.CoInitialize()
        try:
            self._run_trace_inner(win32com.client, kind, query, ready)
        finally:
            pythoncom.CoUninitialize()

    def _run_trace_inner(self, win32com_client: Any, kind: str, query: str, ready: threading.Event) -> None:
        try:
            locator = win32com_client.Dispatch("WbemScripting.SWbemLocator")
            service = locator.ConnectServer(".", r"root\cimv2")
            event_source: Any = service.ExecNotificationQuery(query)
        except Exception as exc:
            hresult = _extract_com_hresult(exc)
            if hresult == WBEM_E_ACCESS_DENIED or "Access denied" in str(exc):
                self.status = "access_denied"
                self.missing_reason = MissingMetadataReason.ACCESS_DENIED
                self.last_error = (
                    "WMI Win32_ProcessStartTrace/StopTrace requires elevated/performance-log privileges "
                    "(WBEM_E_ACCESS_DENIED). Running in degraded mode using WinEvent + Toolhelp32/psutil."
                )
            else:
                self.status = "unavailable"
                self.missing_reason = MissingMetadataReason.SOURCE_UNAVAILABLE
                self.last_error = f"WMI trace subscription failed: {exc}"
            self.stats.wmi_status = self.status
            ready.set()
            return

        ready.set()
        while not self._stop_event.is_set():
            try:
                ev = event_source.NextEvent(self.poll_timeout_ms)
            except Exception as exc:
                hresult = _extract_com_hresult(exc)
                if hresult == WBEM_E_TIMED_OUT or "timed out" in str(exc).lower():
                    continue
                self.last_error = f"WMI NextEvent({kind}) error: {exc}"
                break

            now_ns = time.monotonic_ns()
            now_utc = utc_now_iso()
            pid = int(getattr(ev, "ProcessID", 0) or 0)
            ppid_raw = getattr(ev, "ParentProcessID", None)
            ppid = int(ppid_raw) if ppid_raw is not None else None
            name = str(getattr(ev, "ProcessName", "") or "")
            sess_raw = getattr(ev, "SessionID", None)
            session_id = int(sess_raw) if sess_raw is not None else None

            exit_status: int | None = None
            exit_known = False
            if kind == "stop":
                raw_exit = getattr(ev, "ExitStatus", None)
                if raw_exit is not None:
                    exit_status = int(raw_exit)
                    exit_known = True
                self.stats.wmi_stops_received += 1
            else:
                self.stats.wmi_starts_received += 1

            item = WmiProcessEvent(
                kind=kind,
                pid=pid,
                ppid=ppid,
                process_name=name,
                session_id=session_id,
                exit_status=exit_status,
                exit_code_known=exit_known,
                timestamp_utc=now_utc,
                monotonic_ns=now_ns,
            )
            try:
                self.event_queue.put_nowait(item)
            except queue.Full:
                self.stats.wmi_events_dropped += 1
