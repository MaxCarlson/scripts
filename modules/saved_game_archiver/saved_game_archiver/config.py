from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "archive_root": None,
    "game_roots": [],
    "steam_roots": [],
    "manifest": {
        "enabled": True,
        "url": "https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/data/manifest.yaml",
        "cache_path": None,
        "etag": None,
    },
    "backup": {
        "normal_retention": "24h 7d 4w 12m",
        "running_rates": ["change", "15m"],
        "running_settle_seconds": 2.0,
        "file_stability_seconds": 0.25,
        "in_session_keep_cycles": 2,
        "exit_checkpoint_keep": 10,
        "maintenance_interval": "15m",
    },
    "watcher": {
        "process_poll_seconds": 2.0,
        "save_poll_seconds": 1.0,
        "process_exit_grace_seconds": 5.0,
        "auto_accept_executable_score": 0.65,
        "auto_accept_save_confidence": 0.80,
    },
    "scheduler": {
        "watch_task_name": "SavedGameArchiverWatch",
        "maintenance_task_name": "SavedGameArchiverMaintenance",
        "watch_at_logon": True,
    },
    "hooks": {"post_snapshot": []},
}


def default_data_dir() -> Path:
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "saved_game_archiver"
    xdg = os.environ.get("XDG_STATE_HOME")
    return Path(xdg).expanduser() / "saved_game_archiver" if xdg else Path.home() / ".local" / "state" / "saved_game_archiver"


def default_config_path() -> Path:
    return default_data_dir() / "config.json"


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = Path(path or default_config_path())
    if not config_path.exists():
        config = copy.deepcopy(DEFAULT_CONFIG)
    else:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        config = _merge(DEFAULT_CONFIG, raw)
    if not config["archive_root"]:
        config["archive_root"] = str(default_data_dir() / "archive")
    if not config["manifest"]["cache_path"]:
        config["manifest"]["cache_path"] = str(default_data_dir() / "manifest.yaml")
    return config


def save_config(config: dict[str, Any], path: Path | None = None) -> Path:
    target = Path(path or default_config_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def set_dotted(config: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    cursor = config
    for part in parts[:-1]:
        child = cursor.setdefault(part, {})
        if not isinstance(child, dict):
            raise ValueError(f"Cannot set {dotted_key}: {part} is not an object")
        cursor = child
    cursor[parts[-1]] = value
