"""Live correlation engine joining WinEvent window observations and process ancestry."""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from typing import Callable

from procwatch.collectors.win_event import WinEventCollector
from procwatch.collectors.wmi_trace import WmiProcessEvent
from procwatch.config import CONSOLE_WINDOW_CLASSES, DEFAULT_AUTOMATION_TITLE_PATTERN, WatchConfig
from procwatch.correlator.agent_context import read_process_agent_context
from procwatch.correlator.ancestry import ProcessTableCache, collapse_venv_shims
from procwatch.correlator.peb_git import read_pe_subsystem, read_process_cwd, resolve_git_context
from procwatch.guard.window_guard import RawWindowEvent
from procwatch.models import (
    AgentContext,
    CandidateInitiator,
    CollectorStats,
    ConfidenceLevel,
    EdgeRelation,
    EvidenceEdge,
    GitContext,
    IncidentRecord,
    LiveIncidentEvent,
    MissingMetadataReason,
    ProcessObservation,
    WindowObservation,
    WindowState,
)
from procwatch.storage import FlightRecorderStorage

logger = logging.getLogger(__name__)
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
        storage: FlightRecorderStorage | None = None,
    ) -> None:
        self.process_cache = process_cache
        self.win_queue = win_queue
        self.wmi_queue = wmi_queue
        self.watch_config = watch_config or WatchConfig()
        self.stats = stats or CollectorStats()
        self.on_incident = on_incident
        self.wmi_missing_reason = wmi_missing_reason
        self.storage = storage

        self._windows: dict[str, WindowObservation] = {}
        self._git_cache: dict[str, GitContext | None] = {}
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
            self._persist_process_safe(obs, ancestry=chain)
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
            self._persist_process_safe(obs)
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

        if (
            win_obs.window_class in CONSOLE_WINDOW_CLASSES
            and self.wmi_missing_reason in (MissingMetadataReason.ACCESS_DENIED, MissingMetadataReason.SOURCE_UNAVAILABLE)
        ):
            self.process_cache.refresh_recent_processes(window_ms=self.watch_config.correlation_window_ms)

        candidates = self._find_candidate_initiators(win_obs, owner_proc)

        incident = LiveIncidentEvent(
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
        self._persist_window_incident_safe(incident)
        return incident

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
            if delta_ms < -500.0 or delta_ms > self.watch_config.correlation_window_ms:
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
        # Ensure parent console shells (e.g. cmd.exe spawning ping.exe/conhost.exe) are also surfaced.
        seen_pids = {c.pid for c in candidates}
        for proc in recent:
            if proc.identity.pid not in seen_pids or proc.ppid is None:
                continue
            parent = self.process_cache.lookup_or_enrich_pid(proc.ppid)
            if parent is None or parent.identity.pid in seen_pids:
                continue
            if owner_is_wt and parent.identity.pid == win.owner_pid:
                continue
            if parent.image_name.lower() in {"cmd.exe", "pwsh.exe", "powershell.exe", "python.exe", "pythonw.exe", "node.exe"}:
                seen_pids.add(parent.identity.pid)
                delta_ms = (win.first_seen_monotonic_ns - (parent.start_monotonic_ns or win.first_seen_monotonic_ns)) / 1_000_000.0
                candidates.append(
                    CandidateInitiator(
                        proc_key=parent.identity.proc_key,
                        pid=parent.identity.pid,
                        image_name=parent.image_name,
                        command_line_redacted=parent.command_line_redacted,
                        confidence=ConfidenceLevel.MEDIUM,
                        reasons=["parent_of_candidate_child"],
                        time_delta_ms=round(delta_ms, 2),
                    )
                )
        return candidates[:5]

    def _persist_process_safe(
        self,
        obs: ProcessObservation,
        *,
        ancestry: list[ProcessObservation] | None = None,
    ) -> None:
        if self.storage is None:
            return
        try:
            cwd = read_process_cwd(obs.identity.pid)
            pe_sub = read_pe_subsystem(obs.image_path)
            git_ctx = resolve_git_context(cwd, cache=self._git_cache) if cwd else None
            agent_ctx: AgentContext | None = read_process_agent_context(
                obs.identity.pid,
                ancestry=ancestry,
            )
            self.storage.upsert_process(
                obs,
                cwd=cwd,
                git_repo=git_ctx.repo_root if git_ctx else None,
                git_worktree=git_ctx.worktree_path if git_ctx else None,
                git_branch=git_ctx.branch if git_ctx else None,
                pe_subsystem=pe_sub,
                agent_context=agent_ctx,
            )
        except Exception as exc:
            logger.debug("Flight recorder process persistence failed: %s", exc)

    def _persist_window_incident_safe(self, incident: LiveIncidentEvent) -> None:
        if self.storage is None or incident.window is None:
            return
        try:
            win = incident.window
            owner_key = incident.process.identity.proc_key if incident.process else None
            if incident.process is not None:
                self._persist_process_safe(incident.process, ancestry=incident.ancestry_chain)

            guard_action = (
                incident.guard_decision.intended_action if incident.guard_decision else None
            )
            self.storage.upsert_window(
                win,
                owner_proc_key=owner_key,
                guard_action=guard_action,
            )

            should_record_incident = (
                incident.guard_decision is not None
                or win.window_class in CONSOLE_WINDOW_CLASSES
                or bool(incident.candidate_initiators)
            )
            if not should_record_incident:
                return

            top_candidate = incident.candidate_initiators[0] if incident.candidate_initiators else None
            primary_key = top_candidate.proc_key if top_candidate else owner_key
            confidence = top_candidate.confidence if top_candidate else ConfidenceLevel.LOW
            collapsed = incident.collapsed_ancestry_chain
            root_key = collapsed[-1].identity.proc_key if collapsed else primary_key

            if primary_key:
                self.storage.insert_edge(
                    EvidenceEdge(
                        from_node_id=primary_key,
                        to_node_id=f"win:{win.window_instance_id}",
                        relation=(
                            EdgeRelation.HOSTED_BY
                            if win.window_class == "CASCADIA_HOSTING_WINDOW_CLASS"
                            else EdgeRelation.CORRELATED_WITH
                        ),
                        source="live_correlator",
                        method="+".join(top_candidate.reasons) if top_candidate and top_candidate.reasons else "hwnd_owner",
                        confidence=0.85 if confidence == ConfidenceLevel.HIGH else (0.6 if confidence == ConfidenceLevel.MEDIUM else 0.35),
                    )
                )

            category = "guard_action" if incident.guard_decision is not None else (
                "console_popup" if win.window_class in CONSOLE_WINDOW_CLASSES else "window_event"
            )
            summary = f"{win.window_class} '{win.current_title or ''}'".strip()
            if top_candidate:
                summary += f" -> {top_candidate.image_name} (PID {top_candidate.pid})"
            elif incident.process:
                summary += f" -> {incident.process.image_name} (PID {incident.process.identity.pid})"

            self.storage.insert_incident(
                IncidentRecord(
                    created_ts_utc=incident.timestamp_utc,
                    category=category,
                    primary_proc_key=primary_key,
                    root_initiator_key=root_key,
                    window_instance_id=win.window_instance_id,
                    confidence=confidence,
                    summary_text=summary,
                    alternative_candidates=[
                        {
                            "proc_key": c.proc_key,
                            "pid": c.pid,
                            "image_name": c.image_name,
                            "confidence": c.confidence.value,
                            "reasons": list(c.reasons),
                        }
                        for c in incident.candidate_initiators[1:]
                    ],
                    missing_reasons=[mr.value for mr in incident.missing_reasons],
                ),
                window_ids=[win.window_instance_id],
            )
        except Exception as exc:
            logger.debug("Flight recorder incident persistence failed: %s", exc)

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
