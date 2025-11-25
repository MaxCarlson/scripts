#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir


APP_NAME = "poe2craft"


def data_dir() -> Path:
    """
    Cross-platform writable data dir for persistent files.
    Override via POE2CRAFT_DATA_DIR.
    """
    root = os.getenv("POE2CRAFT_DATA_DIR")
    if root:
        p = Path(root)
    else:
        p = Path(user_data_dir(APP_NAME, "local"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def prices_file(league: str) -> Path:
    slug = league.strip().lower().replace(" ", "_")
    return data_dir() / f"prices_{slug}.json"


def settings_file() -> Path:
    return data_dir() / "settings.json"


def dataset_file(name: str) -> Path:
    """
    Use for definitions dumps (currencies, omens, essences, base items).
    """
    safe = name.replace("/", "_")
    return data_dir() / f"{safe}.json"
