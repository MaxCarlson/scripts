"""Live correlation engine joining WinEvent window observations and process ancestry."""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from procwatch.collectors.win_event import WinEventCollector
from procwatch.collectors.wmi_trace import WmiProcessEvent
from procwatch.config import CONSOLE_WINDOW_CLASSES, DEFAULT_AUTOMATION_TITLE_PATTERN, WatchConfig
from procwatch.correlator.ancestry import ProcessTableCache, collapse_venv_shims
from procwatch.guard.window_guard import RawWindowEvent
from procwatch.models import (
    CandidateInitiator,
    CollectorStats,
    ConfidenceLevel,
    LiveIncidentEvent,
    MissingMetadataReason,
    ProcessObservation,
    WindowObservation,
    WindowState,
)
import re

_AUTOMATION_RE = re.compile(DEFAULT_AUTOMATION_TITLE_PATTERN, re.IGNORECASE)


class LiveCorrelator:
    """Drains bounded collector queues and correlates window events with candidate processes."""

    def __init__(
        self,
        *,
        process_cache: ProcessTableCache,
        win_queue: queue.Queue[RawWindowEvent],
        wmi_queue: queue.Queue[WmiProcessEvent],
        watch_config: WatchConfig | None = None,
        stats: CollectorStats | None = None,
        on_incident: Callable[[LiveIncidentEvent], None] | None = None,
        wmi_missing_reason: MissingMetadataReason | None = None,
    ) -> None:
        self.process_cache = process_cache
        self.win_queue = win_queue
        self.wmi_queue = wmi_queue
        self.watch_config = watch_config or WatchConfig()
        self.stats = stats or CollectorStats()
        self.on_incident = on_incident
        self.wmi_missing_reason = wmi_missing_reason

        self._windows: dict[str, WindowObservation] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def process_wmi_event(self, ev: WmiProcessEvent) -> LiveIncidentEvent | None:
        """Update ProcessTableCache from a WMI process start/stop event."""
        if ev.kind == "start":
            obs = self.process_cache.record_start(
                pid=ev.pid,
                ppid=ev.ppid,
                image_name=ev.process_name,
                session_id=ev.session_id,
                source="wmi_trace",
                monotonic_ns=ev.monotonic_ns,
            )
            chain, _ = self.process_cache.get_ancestry(obs.identity.proc_key)
            incident = LiveIncidentEvent(
                event_type="process_start",
                timestamp_utc=ev.timestamp_utc,
                monotonic_ns=ev.monotonic_ns,
                process=obs,
                ancestry_chain=chain,
                collapsed_ancestry_chain=collapse_venv_shims(chain),
                missing_reasons=list(obs.missing_reasons),
            )
            return incident

        if ev.kind == "stop":
            obs = self.process_cache.record_stop(
                pid=ev.pid,
                exit_code=ev.exit_status,
                exit_code_known=ev.exit_code_known,
                monotonic_ns=ev.monotonic_ns,
            )
            if obs is None:
                return None
            return LiveIncidentEvent(
                event_type="process_stop",
                timestamp_utc=ev.timestamp_utc,
                monotonic_ns=ev.monotonic_ns,
                process=obs,
                missing_reasons=list(obs.missing_reasons),
            )
        return None

    def process_window_event(self, raw: RawWindowEvent) -> LiveIncidentEvent:
        """Correlate a RawWindowEvent with its owner process and candidate initiators."""
        prev = self._windows.get(raw.window_instance_id)
        win_obs = WinEventCollector.to_window_observation(raw, previous=prev)
        if raw.state == WindowState.DESTROYED:
            self._windows.pop(raw.window_instance_id, None)
        else:
            self._windows[raw.window_instance_id] = win_obs

        owner_proc = self.process_cache.lookup_or_enrich_pid(raw.owner_pid)
        ancestry: list[ProcessObservation] = []
        missing: list[MissingMetadataReason] = []
        if owner_proc is not None:
            ancestry, complete = self.process_cache.get_ancestry(owner_proc.identity.proc_key)
            if not complete:
                missing.append(MissingMetadataReason.EXITED_BEFORE_ENRICHMENT)
            for mr in owner_proc.missing_reasons:
                if mr not in missing:
                    missing.append(mr)
        else:
            missing.append(MissingMetadataReason.EXITED_BEFORE_ENRICHMENT)

        if self.wmi_missing_reason is not None and self.wmi_missing_reason not in missing:
            missing.append(self.wmi_missing_reason)

        candidates = self._find_candidate_initiators(win_obs, owner_proc)

        return LiveIncidentEvent(
            event_type="guard_decision" if raw.guard_decision is not None else "window",
            timestamp_utc=raw.timestamp_utc,
            monotonic_ns=raw.monotonic_ns,
            window=win_obs,
            process=owner_proc,
            guard_decision=raw.guard_decision,
            candidate_initiators=candidates,
            ancestry_chain=ancestry,
            collapsed_ancestry_chain=collapse_venv_shims(ancestry),
            missing_reasons=missing,
        )

    def _find_candidate_initiators(
        self,
        win: WindowObservation,
        owner_proc: ProcessObservation | None,
    ) -> list[CandidateInitiator]:
        """Find candidate initiating processes around the window creation time."""
        window_ns = int(self.watch_config.correlation_window_ms * 1_000_000)
        since_ns = max(0, win.first_seen_monotonic_ns - window_ns)
        recent = self.process_cache.recent_processes(since_monotonic_ns=since_ns)

        owner_is_wt = (
            win.window_class == "CASCADIA_HOSTING_WINDOW_CLASS"
            or (owner_proc is not None and owner_proc.image_name.lower() == "windowsterminal.exe")
        )
        candidates: list[CandidateInitiator] = []

        for proc in recent:
            if proc.identity.pid == win.owner_pid and owner_is_wt:
                # Windows Terminal hosts tabs on behalf of other processes; keep low confidence as host
                continue

            delta_ms = (win.first_seen_monotonic_ns - (proc.start_monotonic_ns or win.first_seen_monotonic_ns)) / 1_000_000.0
            if delta_ms < -250.0 or delta_ms > self.watch_config.correlation_window_ms:
                continue

            reasons: list[str] = []
            score = 0

            if proc.identity.pid == win.owner_pid:
                reasons.append("window_owner_pid")
                score += 2
            if win.current_title and proc.image_name and proc.image_name.lower() in win.current_title.lower():
                reasons.append("title_matches_image")
                score += 2
            if win.current_title and proc.command_line_redacted and _AUTOMATION_RE.search(proc.command_line_redacted):
                reasons.append("automation_cmdline_pattern")
                score += 1
            if proc.image_name.lower() in {"python.exe", "pythonw.exe", "pwsh.exe", "powershell.exe", "cmd.exe", "conhost.exe", "node.exe"}:
                reasons.append("console_or_script_runtime")
                score += 1

            if not reasons:
                continue

            if score >= 3:
                conf = ConfidenceLevel.HIGH
            elif score == 2:
                conf = ConfidenceLevel.MEDIUM
            else:
                conf = ConfidenceLevel.LOW

            candidates.append(
                CandidateInitiator(
                    proc_key=proc.identity.proc_key,
                    pid=proc.identity.pid,
                    image_name=proc.image_name,
                    command_line_redacted=proc.command_line_redacted,
                    confidence=conf,
                    reasons=reasons,
                    time_delta_ms=round(delta_ms, 2),
                )
            )

        # If classic console and owner_proc exists but wasn't in recent window (already running), include as medium
        if not candidates and owner_proc is not None and not owner_is_wt and win.window_class in CONSOLE_WINDOW_CLASSES:
            candidates.append(
                CandidateInitiator(
                    proc_key=owner_proc.identity.proc_key,
                    pid=owner_proc.identity.pid,
                    image_name=owner_proc.image_name,
                    command_line_redacted=owner_proc.command_line_redacted,
                    confidence=ConfidenceLevel.MEDIUM,
                    reasons=["direct_console_owner"],
                    time_delta_ms=0.0,
                )
            )

        candidates.sort(key=lambda c: ({"high": 0, "medium": 1, "low": 2, "unknown": 3}[c.confidence.value], abs(c.time_delta_ms or 0.0)))
        return candidates[:5]

    def drain_once(self, *, max_items: int = 128) -> int:
        """Process pending WMI and WinEvent items once. Returns number of events emitted."""
        emitted = 0
        for _ in range(max_items):
            try:
                wmi_ev = self.wmi_queue.get_nowait()
            except queue.Empty:
                break
            inc = self.process_wmi_event(wmi_ev)
            if inc is not None and self.on_incident is not None:
                self.on_incident(inc)
                emitted += 1

        for _ in range(max_items):
            try:
                win_ev = self.win_queue.get_nowait()
            except queue.Empty:
                break
            inc = self.process_window_event(win_ev)
            if self.on_incident is not None:
                self.on_incident(inc)
                emitted += 1
        return emitted

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="procwatch-correlator", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self.drain_once(max_items=512)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            count = self.drain_once()
            if count == 0:
                time.sleep(0.01)
