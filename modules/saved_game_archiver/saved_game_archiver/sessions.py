from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import psutil

from .discovery import executable_score
from .models import ExecutableCandidate, GameRecord, SessionRecord
from .store import StateStore
from .utils import iso_now, parse_iso


@dataclass(frozen=True)
class RunningProcess:
    pid: int
    exe: str
    create_time: float


class ProcessMatcher:
    def __init__(self, auto_accept_score: float = 0.65) -> None:
        self.auto_accept_score = auto_accept_score

    def scan(self, games: dict[str, GameRecord]) -> dict[str, list[RunningProcess]]:
        result: dict[str, list[RunningProcess]] = {game_id: [] for game_id in games}
        for process in psutil.process_iter(["pid", "exe", "create_time"]):
            try:
                exe = process.info.get("exe")
                if not exe:
                    continue
                path = Path(exe)
                candidate_game = self._match_game(path, games.values())
                if candidate_game is None:
                    continue
                self._reinforce_candidate(candidate_game, path)
                result[candidate_game.id].append(
                    RunningProcess(int(process.info["pid"]), str(path), float(process.info.get("create_time") or time.time()))
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ValueError):
                continue
        return result

    def _match_game(self, executable: Path, games: Iterable[GameRecord]) -> GameRecord | None:
        exe_key = _path_key(executable)
        best: tuple[float, GameRecord] | None = None
        for game in games:
            if not game.enabled:
                continue
            for candidate in game.executables:
                if candidate.enabled and _path_key(Path(candidate.path)) == exe_key:
                    score = 2.0 if candidate.origin == "manual" else 1.0 + candidate.score
                    if best is None or score > best[0]:
                        best = (score, game)
            for install_text in game.install_dirs:
                install = Path(install_text)
                if not _is_relative_to(executable, install):
                    continue
                score = executable_score(executable, game.name, install)
                if score >= self.auto_accept_score and (best is None or score > best[0]):
                    best = (score, game)
        return best[1] if best else None

    def _reinforce_candidate(self, game: GameRecord, executable: Path) -> None:
        key = _path_key(executable)
        for candidate in game.executables:
            if _path_key(Path(candidate.path)) == key:
                candidate.observed_runs += 1
                candidate.score = min(1.0, max(candidate.score, 0.75))
                return
        score = 0.75
        for install_text in game.install_dirs:
            install = Path(install_text)
            if _is_relative_to(executable, install):
                score = max(score, executable_score(executable, game.name, install))
        game.executables.append(ExecutableCandidate(str(executable), score, "observed_process", observed_runs=1))


class SessionManager:
    def __init__(self, store: StateStore) -> None:
        self.store = store
        self._active: dict[str, SessionRecord] = {}

    def recover_from_events(self, games: dict[str, GameRecord]) -> None:
        starts: dict[str, dict] = {}
        ends: set[str] = set()
        for event in self.store.iter_events(types={"session_start", "session_end"}):
            session_id = event.get("session_id")
            if not session_id:
                continue
            if event["type"] == "session_start":
                starts[session_id] = event
            else:
                ends.add(session_id)
        for game in games.values():
            session_id = game.active_session_id
            if not session_id or session_id in ends or session_id not in starts:
                continue
            event = starts[session_id]
            self._active[game.id] = SessionRecord(
                id=session_id,
                game_id=game.id,
                started_at=event["timestamp"],
                pids=list(event.get("pids", [])),
                executable_paths=list(event.get("executables", [])),
            )

    def start(self, game: GameRecord, processes: list[RunningProcess]) -> SessionRecord:
        if game.id in self._active:
            session = self._active[game.id]
            session.pids = sorted({item.pid for item in processes})
            session.executable_paths = sorted({item.exe for item in processes})
            return session
        session = SessionRecord(
            id=f"session-{uuid.uuid4().hex[:16]}",
            game_id=game.id,
            started_at=iso_now(),
            pids=sorted({item.pid for item in processes}),
            executable_paths=sorted({item.exe for item in processes}),
        )
        self._active[game.id] = session
        game.active_session_id = session.id
        game.first_play_at = game.first_play_at or session.started_at
        game.last_play_at = session.started_at
        self.store.append_event(
            {
                "type": "session_start",
                "timestamp": session.started_at,
                "game_id": game.id,
                "session_id": session.id,
                "pids": session.pids,
                "executables": session.executable_paths,
                "playtime_seconds": game.effective_playtime_seconds,
            }
        )
        return session

    def finish(self, game: GameRecord) -> SessionRecord | None:
        session = self._active.pop(game.id, None)
        if session is None:
            return None
        ended = iso_now()
        duration = max(0.0, (parse_iso(ended) - parse_iso(session.started_at)).total_seconds())
        session.ended_at = ended
        session.duration_seconds = duration
        game.tracked_playtime_seconds += duration
        game.last_play_at = ended
        game.active_session_id = None
        self.store.append_event(
            {
                "type": "session_end",
                "timestamp": ended,
                "game_id": game.id,
                "session_id": session.id,
                "started_at": session.started_at,
                "duration_seconds": duration,
                "playtime_seconds": game.effective_playtime_seconds,
            }
        )
        return session

    def active_session(self, game_id: str) -> SessionRecord | None:
        return self._active.get(game_id)

    def live_playtime(self, game: GameRecord) -> float:
        session = self._active.get(game.id)
        if session is None:
            return game.effective_playtime_seconds
        elapsed = max(0.0, (parse_iso(iso_now()) - parse_iso(session.started_at)).total_seconds())
        base = max(game.imported_playtime_seconds + game.tracked_playtime_seconds, game.steam_reported_playtime_seconds)
        return base + elapsed


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path).casefold()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False
