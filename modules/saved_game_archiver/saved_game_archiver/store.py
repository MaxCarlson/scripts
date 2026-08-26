from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from .config import default_data_dir
from .models import GameRecord


class StateStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or default_data_dir())
        self.catalog_path = self.root / "catalog.json"
        self.events_path = self.root / "events.jsonl"

    def load_catalog(self) -> dict[str, GameRecord]:
        if not self.catalog_path.exists():
            return {}
        raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        return {game_id: GameRecord.from_dict(data) for game_id, data in raw.get("games", {}).items()}

    def save_catalog(self, games: dict[str, GameRecord]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "games": {key: value.to_dict() for key, value in sorted(games.items())}}
        temp = self.catalog_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, self.catalog_path)

    def append_event(self, event: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, sort_keys=True, separators=(",", ":"))
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def iter_events(self, *, game_id: str | None = None, types: set[str] | None = None) -> Iterable[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self.events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                if game_id is not None and item.get("game_id") != game_id:
                    continue
                if types is not None and item.get("type") not in types:
                    continue
                events.append(item)
        return events
