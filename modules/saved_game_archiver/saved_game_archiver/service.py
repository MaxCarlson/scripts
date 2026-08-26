from __future__ import annotations

import subprocess
from pathlib import Path

from .archive import ArchiveEngine, CaptureResult
from .config import load_config, save_config
from .discovery import (
    LudusaviManifest,
    configured_and_default_steam_roots,
    discover_root_games,
    discover_steam_games,
    likely_common_save_paths,
    merge_discovered,
    merge_save_sources,
    refresh_manifest,
    resolve_ludusavi_sources,
    steam_playtime_minutes,
    steam_userdata_sources,
)
from .models import GameRecord, SaveSource
from .store import StateStore
from .utils import iso_now


class GameService:
    def __init__(self, *, config_path: Path | None = None, data_root: Path | None = None) -> None:
        self.config_path = config_path
        self.config = load_config(config_path)
        self.store = StateStore(data_root)
        self.games = self.store.load_catalog()
        self.archive = ArchiveEngine(
            Path(self.config["archive_root"]).expanduser(),
            file_stability_seconds=float(self.config["backup"]["file_stability_seconds"]),
        )

    def persist(self) -> None:
        self.store.save_catalog(self.games)
        if self.config_path is not None:
            save_config(self.config, self.config_path)

    def scan(self, *, refresh_manifest_if_missing: bool = False, persist: bool = True) -> list[str]:
        discovered = discover_steam_games(self.config) + discover_root_games(self.config)
        self.games, new_ids = merge_discovered(self.games, discovered)
        playtime = steam_playtime_minutes(configured_and_default_steam_roots(self.config))
        for game in self.games.values():
            if game.steam_app_id is not None and game.steam_app_id in playtime:
                seconds = float(playtime[game.steam_app_id] * 60)
                if game.imported_playtime_seconds <= 0:
                    game.imported_playtime_seconds = seconds
                game.steam_reported_playtime_seconds = seconds
        manifest = self._load_manifest(refresh_if_missing=refresh_manifest_if_missing)
        for game in self.games.values():
            if manifest is not None:
                merge_save_sources(game, resolve_ludusavi_sources(game, self.config, manifest))
            merge_save_sources(game, steam_userdata_sources(game, self.config))
            common = [path for path in likely_common_save_paths(game) if path.exists()]
            merge_save_sources(
                game,
                [SaveSource(f"common-{index:03d}", "files", str(path), "common-path", 0.80) for index, path in enumerate(common)],
            )
            if game.save_sources:
                game.status = "ready" if game.last_snapshot_id is None else "protected"
            elif game.executables:
                game.status = "discovered_no_save"
            else:
                game.status = "needs_executable"
        if persist:
            self.store.save_catalog(self.games)
            for game_id in new_ids:
                self.store.append_event({"type": "game_discovered", "timestamp": iso_now(), "game_id": game_id})
        return new_ids

    def refresh_manifest(self) -> tuple[Path, bool]:
        path, changed = refresh_manifest(self.config)
        save_config(self.config, self.config_path)
        return path, changed

    def capture(self, game: GameRecord, *, reason: str, session_id: str | None, playtime_seconds: float) -> CaptureResult:
        result = self.archive.capture_game(
            game,
            reason=reason,
            session_id=session_id,
            playtime_seconds=playtime_seconds,
        )
        game.last_checked_at = iso_now()
        event = {
            "type": "snapshot" if result.changed else "backup_check",
            "timestamp": game.last_checked_at,
            "game_id": game.id,
            "session_id": session_id,
            "snapshot_id": result.snapshot_id,
            "reason": reason,
            "changed": result.changed,
            "files_seen": result.files_seen,
            "changed_files": result.changed_files,
            "deleted_files": result.deleted_files,
            "bytes_added": result.bytes_added,
            "playtime_seconds": playtime_seconds,
        }
        if result.changed and result.snapshot_id:
            manifest = self.archive.load_manifest(game.id, result.snapshot_id)
            event["state_indices_changed"] = manifest.state_indices_changed
            self._run_post_snapshot_hooks(game, result.snapshot_id)
        self.store.append_event(event)
        self.store.save_catalog(self.games)
        return result

    def prune(self, game: GameRecord) -> tuple[int, int]:
        removed = self.archive.prune_game(game, self.config)
        self.store.save_catalog(self.games)
        return removed

    def get_game(self, selector: str) -> GameRecord:
        if selector in self.games:
            return self.games[selector]
        lowered = selector.casefold()
        matches = [game for game in self.games.values() if game.name.casefold() == lowered]
        if len(matches) == 1:
            return matches[0]
        partial = [game for game in self.games.values() if lowered in game.name.casefold()]
        if len(partial) == 1:
            return partial[0]
        if not matches and not partial:
            raise KeyError(f"No tracked game matches {selector!r}")
        raise KeyError(f"Game selector {selector!r} is ambiguous")

    def _load_manifest(self, *, refresh_if_missing: bool) -> LudusaviManifest | None:
        if not self.config["manifest"].get("enabled", True):
            return None
        path = Path(self.config["manifest"]["cache_path"]).expanduser()
        if not path.exists() and refresh_if_missing:
            try:
                path, _ = refresh_manifest(self.config)
                save_config(self.config, self.config_path)
            except OSError:
                return None
        if not path.exists():
            return None
        try:
            return LudusaviManifest.load(path)
        except (OSError, ValueError):
            return None

    def _run_post_snapshot_hooks(self, game: GameRecord, snapshot_id: str) -> None:
        for command in self.config.get("hooks", {}).get("post_snapshot", []):
            if not command:
                continue
            env = {
                "SGA_GAME_ID": game.id,
                "SGA_GAME_NAME": game.name,
                "SGA_SNAPSHOT_ID": snapshot_id,
                "SGA_ARCHIVE_ROOT": str(self.archive.root),
            }
            subprocess.run(command, shell=True, check=False, env={**__import__("os").environ, **env})
