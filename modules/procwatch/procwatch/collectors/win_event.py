"""WinEvent collector wrapping NeutralizeEngine and emitting WindowObservation events."""

from __future__ import annotations

import queue

from procwatch.config import GuardConfig
from procwatch.guard.window_guard import NeutralizeEngine, RawWindowEvent, WindowBackend
from procwatch.models import CollectorStats, WindowObservation, WindowState


class WinEventCollector:
    """Manages the NeutralizeEngine lifecycle and converts raw events to WindowObservation."""

    def __init__(
        self,
        guard_config: GuardConfig | None = None,
        *,
        event_queue: queue.Queue[RawWindowEvent] | None = None,
        backend: WindowBackend | None = None,
        stats: CollectorStats | None = None,
        boot_id: str | None = None,
    ) -> None:
        self.event_queue = event_queue or queue.Queue(maxsize=4096)
        self.stats = stats or CollectorStats()
        self.engine = NeutralizeEngine(
            config=guard_config,
            backend=backend,
            event_queue=self.event_queue,
            stats=self.stats,
            boot_id=boot_id,
        )

    def start(self, *, timeout: float = 2.0) -> None:
        """Start the WinEvent hook loop in a background thread."""
        self.engine.start_background(timeout=timeout)

    def stop(self, *, timeout: float = 2.0) -> None:
        """Stop the WinEvent hook loop and restore any guard-modified windows."""
        self.engine.stop(timeout=timeout)

    @staticmethod
    def to_window_observation(raw: RawWindowEvent, *, previous: WindowObservation | None = None) -> WindowObservation:
        """Convert a RawWindowEvent into a WindowObservation, preserving title history."""
        if previous is not None:
            history = list(previous.title_history)
            if raw.title and (not history or history[-1] != raw.title):
                history.append(raw.title)
            return WindowObservation(
                window_instance_id=raw.window_instance_id,
                hwnd=raw.hwnd,
                owner_pid=raw.owner_pid,
                owner_tid=raw.owner_tid,
                window_class=raw.window_class,
                initial_title=previous.initial_title or raw.title,
                current_title=raw.title or previous.current_title,
                title_history=history,
                became_visible=previous.became_visible or raw.visible,
                stole_foreground=previous.stole_foreground or raw.is_foreground,
                first_seen_ts_utc=previous.first_seen_ts_utc,
                first_seen_monotonic_ns=previous.first_seen_monotonic_ns,
                callback_arrival_ns=raw.callback_arrival_ns,
                win_event=raw.win_event,
                state=raw.state,
                destroy_ts_utc=raw.timestamp_utc if raw.state == WindowState.DESTROYED else None,
                destroy_monotonic_ns=raw.monotonic_ns if raw.state == WindowState.DESTROYED else None,
                foreground_target_hwnd=raw.foreground_hwnd,
            )

        return WindowObservation(
            window_instance_id=raw.window_instance_id,
            hwnd=raw.hwnd,
            owner_pid=raw.owner_pid,
            owner_tid=raw.owner_tid,
            window_class=raw.window_class,
            initial_title=raw.title,
            current_title=raw.title,
            title_history=[raw.title] if raw.title else [],
            became_visible=raw.visible,
            stole_foreground=raw.is_foreground,
            first_seen_ts_utc=raw.timestamp_utc,
            first_seen_monotonic_ns=raw.monotonic_ns,
            callback_arrival_ns=raw.callback_arrival_ns,
            win_event=raw.win_event,
            state=raw.state,
            destroy_ts_utc=raw.timestamp_utc if raw.state == WindowState.DESTROYED else None,
            destroy_monotonic_ns=raw.monotonic_ns if raw.state == WindowState.DESTROYED else None,
            foreground_target_hwnd=raw.foreground_hwnd,
        )
