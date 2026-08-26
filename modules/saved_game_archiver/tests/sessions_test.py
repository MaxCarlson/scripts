from __future__ import annotations

from pathlib import Path

import saved_game_archiver.sessions as sessions
from saved_game_archiver.models import GameRecord
from saved_game_archiver.sessions import RunningProcess, SessionManager
from saved_game_archiver.store import StateStore


def test_effective_playtime_uses_imported_baseline_plus_tracked_without_double_counting() -> None:
    game = GameRecord(
        id="g", name="Game", imported_playtime_seconds=3600, tracked_playtime_seconds=600, steam_reported_playtime_seconds=4000
    )
    assert game.effective_playtime_seconds == 4200
    game.steam_reported_playtime_seconds = 5000
    assert game.effective_playtime_seconds == 5000


def test_session_start_end_updates_playtime_and_event_log(tmp_path: Path, monkeypatch) -> None:
    times = iter(["2026-08-25T20:00:00+00:00", "2026-08-25T20:30:00+00:00"])
    monkeypatch.setattr(sessions, "iso_now", lambda: next(times))
    store = StateStore(tmp_path)
    manager = SessionManager(store)
    game = GameRecord(id="g", name="Game")
    proc = RunningProcess(12, "/game.exe", 1.0)
    session = manager.start(game, [proc])
    finished = manager.finish(game)
    assert finished is not None and finished.id == session.id
    assert game.tracked_playtime_seconds == 1800
    events = list(store.iter_events(game_id="g"))
    assert [event["type"] for event in events] == ["session_start", "session_end"]


def test_recover_active_session_from_append_only_events(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.append_event(
        {"type": "session_start", "timestamp": "2026-08-25T20:00:00+00:00", "game_id": "g", "session_id": "s", "pids": [1], "executables": ["x"]}
    )
    game = GameRecord(id="g", name="Game", active_session_id="s")
    manager = SessionManager(store)
    manager.recover_from_events({"g": game})
    assert manager.active_session("g") is not None
