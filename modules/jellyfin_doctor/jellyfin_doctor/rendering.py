"""In-place rendering abstraction with optional termdash support."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


class StatusRenderer:
    """Small renderer that prefers termdash but can fall back to plain terminal output."""

    def __init__(self, *, in_place: bool = False, title: str = "Jellyfin Doctor") -> None:
        self.in_place = in_place
        self.title = title
        self._dash: Any | None = None
        self.backend = "plain"
        if in_place:
            try:
                from termdash import Line, Stat, TermDash

                dash = TermDash()
                dash.add_line("title", Line("title", stats=[Stat("title", title, prefix="", format_string="{}")]))
                self._dash = dash
                self._line_cls = Line
                self._stat_cls = Stat
                self.backend = "termdash"
            except Exception:
                self._dash = None

    def __enter__(self) -> StatusRenderer:
        if self._dash is not None:
            self._dash.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._dash is not None:
            self._dash.stop()

    def render(self, rows: Mapping[str, Any]) -> None:
        """Render status rows."""
        if self._dash is not None:
            for key, value in rows.items():
                if key == "title":
                    continue
                try:
                    self._dash.add_line(
                        key,
                        self._line_cls(key, stats=[self._stat_cls("value", value, format_string="{}")]),
                    )
                except Exception:
                    self._dash.update_stat(key, "value", value)
            return
        if self.in_place and os.name != "nt":
            print("\033[2J\033[H", end="")
        for key, value in rows.items():
            print(f"{key}: {value}")
