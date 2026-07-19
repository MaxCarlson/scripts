"""Persistent module-local configuration for runmux."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {"terminal_record_limit": 500}


class ConfigError(RuntimeError):
    """Raised when runmux configuration is invalid."""


def config_path() -> Path:
    """Return the module-local persistent configuration path."""

    return Path(__file__).resolve().parents[2] / ".runmux" / "config.json"


def load_config() -> dict[str, Any]:
    """Load configuration and fill in defaults."""

    path = config_path()
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"Invalid runmux configuration: {path}") from error
    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid runmux configuration: {path}")
    result = dict(DEFAULT_CONFIG)
    result.update({key: value for key, value in raw.items() if key in DEFAULT_CONFIG})
    _validate_config(result)
    return result


def set_config_value(key: str, value: str) -> dict[str, Any]:
    """Validate and persist one configuration value."""

    if key not in DEFAULT_CONFIG:
        choices = ", ".join(sorted(DEFAULT_CONFIG))
        raise ConfigError(f"Unknown configuration key '{key}'. Available keys: {choices}")
    config = load_config()
    if key == "terminal_record_limit":
        try:
            config[key] = int(value)
        except ValueError as error:
            raise ConfigError("terminal_record_limit must be a non-negative integer.") from error
    _validate_config(config)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return config


def _validate_config(config: dict[str, Any]) -> None:
    limit = config.get("terminal_record_limit")
    if not isinstance(limit, int) or limit < 0:
        raise ConfigError("terminal_record_limit must be a non-negative integer.")
