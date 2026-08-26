from __future__ import annotations

from typing import Any

from .models import GameRecord
from .utils import format_playtime


class WatchDashboard:
    """Thin TermDash adapter for the long-running game/session watcher."""

    def __init__(self, games: dict[str, GameRecord]) -> None:
        from termdash import SimpleBoard, Stat

        self._Stat = Stat
        self.board = SimpleBoard(title="Saved Game Archiver — live watcher")
        for game in sorted(games.values(), key=lambda item: item.name.casefold()):
            self.board.add_row(
                game.id,
                Stat("game", game.name, format_string="{}", no_expand=False),
                Stat("status", "idle", format_string="{}", no_expand=True),
                Stat("playtime", format_playtime(game.effective_playtime_seconds), format_string="{}", no_expand=True),
                Stat("save", game.status, format_string="{}", no_expand=True),
            )

    def __enter__(self) -> "WatchDashboard":
        self.board.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.board.__exit__(exc_type, exc, tb)

    def update_game(self, game: GameRecord, running: bool, playtime_seconds: float) -> None:
        self.board.update(game.id, "status", "RUNNING" if running else "idle")
        self.board.update(game.id, "playtime", format_playtime(playtime_seconds))
        self.board.update(game.id, "save", game.status)
