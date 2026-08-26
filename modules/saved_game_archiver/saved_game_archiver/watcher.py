from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from .discovery import correlated_save_sources, merge_save_sources
from .models import GameRecord
from .retention import parse_interval
from .service import GameService
from .sessions import ProcessMatcher, SessionManager
from .utils import iso_now, parse_iso

try:  # pragma: no cover - environment validation covers watchdog when installed.
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover
    FileSystemEventHandler = object  # type: ignore[assignment,misc]
    Observer = None  # type: ignore[assignment]


@dataclass
class RuntimeGameState:
    signature: dict[str, tuple[int, int]] = field(default_factory=dict)
    dirty_since: float | None = None
    last_change_at: float | None = None
    process_missing_since: float | None = None
    last_periodic: dict[str, float] = field(default_factory=dict)


class _SaveEventHandler(FileSystemEventHandler):  # type: ignore[misc]
    def __init__(self, watcher: "GameWatcher", game_id: str) -> None:
        super().__init__()
        self.watcher = watcher
        self.game_id = game_id

    def on_any_event(self, event: Any) -> None:
        if getattr(event, "is_directory", False):
            return
        self.watcher.mark_dirty(self.game_id)


class GameWatcher:
    def __init__(self, service: GameService) -> None:
        self.service = service
        self.config = service.config
        self.matcher = ProcessMatcher(float(self.config["watcher"]["auto_accept_executable_score"]))
        self.sessions = SessionManager(service.store)
        self.sessions.recover_from_events(service.games)
        self.runtime: dict[str, RuntimeGameState] = {game_id: RuntimeGameState() for game_id in service.games}
        self.lock = Lock()
        self.observer = Observer() if Observer is not None else None
        self._watched: set[tuple[str, str]] = set()
        self._install_watches()

    def _install_watches(self) -> None:
        if self.observer is None:
            return
        for game in self.service.games.values():
            for source in game.save_sources:
                if source.kind != "files":
                    continue
                target = Path(source.path).expanduser()
                watch_dir = target if target.is_dir() else target.parent
                while not watch_dir.exists() and watch_dir.parent != watch_dir:
                    watch_dir = watch_dir.parent
                key = (game.id, str(watch_dir).casefold())
                if not watch_dir.is_dir() or key in self._watched:
                    continue
                self.observer.schedule(_SaveEventHandler(self, game.id), str(watch_dir), recursive=True)
                self._watched.add(key)

    def mark_dirty(self, game_id: str) -> None:
        now = time.monotonic()
        with self.lock:
            state = self.runtime.setdefault(game_id, RuntimeGameState())
            state.dirty_since = state.dirty_since or now
            state.last_change_at = now

    def run(self, *, once: bool = False, dashboard: Any | None = None) -> None:
        if self.observer is not None:
            self.observer.start()
        try:
            while True:
                self.tick(dashboard=dashboard)
                if once:
                    return
                time.sleep(float(self.config["watcher"]["process_poll_seconds"]))
        finally:
            if self.observer is not None:
                self.observer.stop()
                self.observer.join(timeout=5)

    def tick(self, *, dashboard: Any | None = None) -> None:
        running = self.matcher.scan(self.service.games)
        now = time.monotonic()
        settle = float(self.config["backup"]["running_settle_seconds"])
        exit_grace = float(self.config["watcher"]["process_exit_grace_seconds"])
        for game_id, game in self.service.games.items():
            state = self.runtime.setdefault(game_id, RuntimeGameState())
            processes = running.get(game_id, [])
            active = self.sessions.active_session(game_id)
            if processes:
                state.process_missing_since = None
                session = self.sessions.start(game, processes)
                correlated = correlated_save_sources(game, since_epoch=parse_iso(session.started_at).timestamp())
                threshold = float(self.config["watcher"]["auto_accept_save_confidence"])
                accepted = [source for source in correlated if source.confidence >= threshold]
                if accepted:
                    before = len(game.save_sources)
                    merge_save_sources(game, accepted)
                    if len(game.save_sources) != before:
                        self._install_watches()
                        self.service.store.append_event(
                            {
                                "type": "save_source_discovered",
                                "timestamp": iso_now(),
                                "game_id": game.id,
                                "session_id": session.id,
                                "sources": [source.to_dict() for source in accepted],
                            }
                        )
                signature = save_signature(game)
                if state.signature and signature != state.signature:
                    self.mark_dirty(game_id)
                state.signature = signature
                self._capture_running_if_due(game, session.id, state, now, settle)
            elif active is not None:
                if state.process_missing_since is None:
                    state.process_missing_since = now
                elif now - state.process_missing_since >= exit_grace:
                    self._finish_session(game, active.id)
                    state.process_missing_since = None
                    state.dirty_since = None
                    state.last_change_at = None
                    state.signature = save_signature(game)
            else:
                state.signature = save_signature(game)
            if dashboard is not None:
                dashboard.update_game(game, bool(processes), self.sessions.live_playtime(game))
        self.service.store.save_catalog(self.service.games)

    def _capture_running_if_due(
        self,
        game: GameRecord,
        session_id: str,
        state: RuntimeGameState,
        now: float,
        settle: float,
    ) -> None:
        rates = list(self.config["backup"].get("running_rates", ["change"]))
        if "change" in rates and state.dirty_since is not None and state.last_change_at is not None:
            if now - state.last_change_at >= settle:
                self.service.capture(
                    game,
                    reason="in_session",
                    session_id=session_id,
                    playtime_seconds=self.sessions.live_playtime(game),
                )
                state.dirty_since = None
                state.last_change_at = None
        for rate in rates:
            if rate == "change":
                continue
            interval = parse_interval(rate)
            last = state.last_periodic.get(rate, 0.0)
            if now - last >= interval:
                self.service.capture(
                    game,
                    reason="in_session",
                    session_id=session_id,
                    playtime_seconds=self.sessions.live_playtime(game),
                )
                state.last_periodic[rate] = now

    def _finish_session(self, game: GameRecord, session_id: str) -> None:
        live_playtime = self.sessions.live_playtime(game)
        result = self.service.capture(game, reason="session_exit", session_id=session_id, playtime_seconds=live_playtime)
        finished = self.sessions.finish(game)
        if finished is not None and result.snapshot_id is not None:
            self.service.archive.pin_exit_checkpoint(
                game,
                snapshot_id=result.snapshot_id,
                session_id=finished.id,
                keep=int(self.config["backup"]["exit_checkpoint_keep"]),
                playtime_seconds=game.effective_playtime_seconds,
            )
            self.service.store.append_event(
                {
                    "type": "exit_checkpoint",
                    "timestamp": iso_now(),
                    "game_id": game.id,
                    "session_id": finished.id,
                    "snapshot_id": result.snapshot_id,
                    "playtime_seconds": game.effective_playtime_seconds,
                }
            )
            self.service.prune(game)


def save_signature(game: GameRecord) -> dict[str, tuple[int, int]]:
    signature: dict[str, tuple[int, int]] = {}
    for source in game.save_sources:
        if not source.enabled or source.kind != "files":
            continue
        path = Path(source.path).expanduser()
        if path.is_file():
            try:
                stat = path.stat()
                signature[f"{source.id}:{path.name}"] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                pass
            continue
        if not path.is_dir():
            continue
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            try:
                stat = child.stat()
                relative = child.relative_to(path).as_posix()
            except (OSError, ValueError):
                continue
            signature[f"{source.id}:{relative}"] = (stat.st_size, stat.st_mtime_ns)
    return signature
