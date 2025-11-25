#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def now_ts() -> float:
    return time.time()


def age_hours(since_ts: float) -> float:
    return max(0.0, (now_ts() - since_ts) / 3600.0)


DEFAULT_SETTINGS: Dict[str, Any] = {
    "default_league": "Standard",
    "auto_hours": None,  # don't auto-refresh unless set
    "last_price_update": {},  # map: league_slug -> ts
}
