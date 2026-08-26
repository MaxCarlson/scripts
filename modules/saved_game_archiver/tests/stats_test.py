from __future__ import annotations

from pathlib import Path

from saved_game_archiver.models import GameRecord
from saved_game_archiver.service import GameService
from saved_game_archiver.stats import render_hourly_histogram, render_overall_timeline, render_playtime_bars


def make_service(tmp_path: Path) -> GameService:
    config = tmp_path / "config.json"
    config.write_text(
        '{"archive_root": "' + (tmp_path / "archive").as_posix() + '", "manifest": {"enabled": false}}',
        encoding="utf-8",
    )
    service = GameService(config_path=config, data_root=tmp_path / "state")
    service.games = {"g": GameRecord(id="g", name="Game", tracked_playtime_seconds=3600)}
    service.store.save_catalog(service.games)
    return service


def test_playtime_graph_renders_game(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    text = render_playtime_bars(service, width=80)
    assert "Game" in text and "0001h00m00s" in text


def test_overall_timeline_and_hour_histogram_use_sessions(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.store.append_event({"type": "session_start", "timestamp": "2026-08-25T20:10:00+00:00", "game_id": "g", "session_id": "s"})
    service.store.append_event({"type": "session_end", "timestamp": "2026-08-25T21:10:00+00:00", "game_id": "g", "session_id": "s"})
    assert "Game" in render_overall_timeline(service, width=80)
    hourly = render_hourly_histogram(service)
    assert "Gaming by hour of day" in hourly


def test_playtime_graph_adds_recorded_daily_activity_sparkline(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.store.append_event({"type": "session_start", "timestamp": "2026-08-24T20:00:00+00:00", "game_id": "g", "session_id": "s"})
    service.store.append_event({"type": "session_end", "timestamp": "2026-08-24T21:00:00+00:00", "game_id": "g", "session_id": "s"})
    text = render_playtime_bars(service, width=100)
    assert "Daily activity span" in text
