from __future__ import annotations

from pathlib import Path

from saved_game_archiver.application import build_parser, main


def test_main_help_exposes_requested_structured_areas(capsys) -> None:
    parser = build_parser()
    text = parser.format_help()
    for command in ("schedule", "stats", "modify", "config", "watch"):
        assert command in text


def test_schedule_running_short_options_parse() -> None:
    args = build_parser().parse_args(["schedule", "running", "-r", "change", "5m", "-s", "1", "-k", "2", "-e", "10"])
    assert args.rates == ["change", "5m"]
    assert args.keep_cycles == 2


def test_game_root_mutation_is_dry_run_by_default(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    game_root = tmp_path / "games"; game_root.mkdir()
    assert main(["-c", str(config), "config", "game-root", "add", str(game_root)]) == 0
    assert not config.exists()


def test_game_root_apply_writes_json(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    data = tmp_path / "state"
    game_root = tmp_path / "games"; game_root.mkdir()
    assert main(["-c", str(config), "-d", str(data), "config", "game-root", "add", str(game_root), "--apply"]) == 0
    assert config.exists()


def test_state_index_collision_is_rejected(tmp_path: Path) -> None:
    from saved_game_archiver.models import GameRecord
    from saved_game_archiver.store import StateStore

    config = tmp_path / "config.json"
    config.write_text('{"archive_root": "' + (tmp_path / "archive").as_posix() + '", "manifest": {"enabled": false}}', encoding="utf-8")
    data = tmp_path / "state"
    store = StateStore(data)
    game = GameRecord(id="g", name="Game", save_states={"src:a": 0, "src:b": 1})
    store.save_catalog({"g": game})
    assert main(["-c", str(config), "-d", str(data), "modify", "state", "set", "g", "src:b", "0", "--apply"]) == 2
