from __future__ import annotations

from pathlib import Path

from saved_game_archiver.discovery import (
    LudusaviManifest,
    discover_root_games,
    discover_steam_library_roots,
    executable_score,
    merge_discovered,
    parse_vdf,
    resolve_ludusavi_sources,
    save_state_key,
    steam_playtime_minutes,
)
from saved_game_archiver.models import GameRecord


def test_vdf_parser_handles_nested_objects() -> None:
    raw = parse_vdf('"AppState" { "appid" "123" "name" "Example" }')
    assert raw["AppState"]["appid"] == "123"


def test_configured_game_root_treats_each_child_as_game(tmp_path: Path) -> None:
    root = tmp_path / "games"; root.mkdir()
    (root / "Alpha").mkdir(); (root / "Beta").mkdir()
    games = discover_root_games({"game_roots": [str(root)]})
    assert {game.name for game in games} == {"Alpha", "Beta"}


def test_game_root_and_steam_discovery_reconcile_by_install_dir(tmp_path: Path) -> None:
    install = tmp_path / "Game"; install.mkdir()
    root_game = GameRecord(id="root", name="Game", install_dirs=[str(install)], discovery_origins=["root"])
    steam_game = GameRecord(id="steam-12", name="Game", install_dirs=[str(install)], steam_app_id=12, discovery_origins=["steam"])
    merged, new = merge_discovered({}, [root_game, steam_game])
    assert len(merged) == 1
    only = next(iter(merged.values()))
    assert only.steam_app_id == 12
    assert set(only.discovery_origins) == {"root", "steam"}


def test_libraryfolders_vdf_discovers_extra_library(tmp_path: Path) -> None:
    steam = tmp_path / "Steam"; apps = steam / "steamapps"; apps.mkdir(parents=True)
    other = tmp_path / "Other"
    (apps / "libraryfolders.vdf").write_text(
        f'"libraryfolders" {{ "0" {{ "path" "{steam.as_posix()}" }} "1" {{ "path" "{other.as_posix()}" }} }}',
        encoding="utf-8",
    )
    roots = discover_steam_library_roots(steam)
    assert steam in roots and other in roots


def test_steam_localconfig_playtime_is_parsed(tmp_path: Path) -> None:
    steam = tmp_path / "Steam"; config = steam / "userdata" / "1" / "config"; config.mkdir(parents=True)
    (config / "localconfig.vdf").write_text(
        '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "Apps" { "123" { "Playtime" "456" } } } } } }',
        encoding="utf-8",
    )
    assert steam_playtime_minutes([steam])[123] == 456


def test_executable_scoring_rejects_uninstaller_and_prefers_game_name(tmp_path: Path) -> None:
    install = tmp_path / "Cool Game"; install.mkdir()
    game = install / "CoolGame.exe"; game.write_bytes(b"x" * (6 * 1024 * 1024))
    uninstaller = install / "unins000.exe"; uninstaller.write_bytes(b"x")
    assert executable_score(game, "Cool Game", install) > 0.8
    assert executable_score(uninstaller, "Cool Game", install) < 0.2


def test_ludusavi_resolution_keeps_expected_path_before_first_launch(tmp_path: Path) -> None:
    install = tmp_path / "Example"
    game = GameRecord(id="steam-123", name="Example", install_dirs=[str(install)], steam_app_id=123)
    manifest = LudusaviManifest(
        {
            "Example": {
                "files": {"<base>/saves": {"tags": ["save"]}},
                "installDir": {"Example": {}},
                "steam": {"id": 123},
            }
        }
    )
    config = {"game_roots": [str(tmp_path)], "steam_roots": []}
    sources = resolve_ludusavi_sources(game, config, manifest)
    assert len(sources) == 1
    assert Path(sources[0].path) == install / "saves"


def test_state_key_never_merges_distinct_character_dirs() -> None:
    assert save_state_key("src", "S1/autosave.sav") != save_state_key("src", "S2/autosave.sav")


def test_session_correlation_finds_recent_named_save_directory(tmp_path: Path, monkeypatch) -> None:
    import time
    import saved_game_archiver.discovery as discovery

    root = tmp_path / "Local"; root.mkdir()
    candidate = root / "Cool Game"; candidate.mkdir()
    (candidate / "slot.sav").write_bytes(b"x")
    monkeypatch.setattr(discovery, "common_save_search_roots", lambda: [root])
    game = GameRecord(id="g", name="Cool Game")
    sources = discovery.correlated_save_sources(game, since_epoch=time.time() - 60)
    assert any(Path(source.path) == candidate and source.confidence >= 0.8 for source in sources)
