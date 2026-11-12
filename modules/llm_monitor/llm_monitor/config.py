"""Persistent user configuration discovery, parsing, and precedence resolution for LLM Monitor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

try:
    import tomllib  # Python 3.11+ standard library
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None  # type: ignore[assignment]


class ConfigError(ValueError):
    """Raised when user configuration cannot be read or contains invalid values."""


def default_config_dir(
    *,
    platform: str | None = None,
    environ: dict[str, str] | None = None,
) -> Path:
    """Return the platform-specific default directory for user configuration files."""
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform

    if plat.startswith("win"):
        root = env.get("LOCALAPPDATA") or env.get("APPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Local"
    elif plat == "darwin":
        base = Path(env.get("HOME", str(Path.home()))) / "Library" / "Application Support"
    else:
        xdg = env.get("XDG_CONFIG_HOME")
        if xdg:
            base = Path(xdg)
        else:
            base = Path(env.get("HOME", str(Path.home()))) / ".config"

    return base / "llm-monitor"


def find_config_file(
    config_path: Path | str | None = None,
    *,
    platform: str | None = None,
    environ: dict[str, str] | None = None,
) -> Path | None:
    """Find the path to the configuration file, respecting overrides and file discovery."""
    if config_path is not None:
        p = Path(config_path)
        return p if p.is_file() else None

    env = os.environ if environ is None else environ
    if "LLM_MONITOR_CONFIG" in env and env["LLM_MONITOR_CONFIG"].strip():
        env_path = Path(env["LLM_MONITOR_CONFIG"].strip())
        return env_path if env_path.is_file() else None

    cfg_dir = default_config_dir(platform=platform, environ=environ)
    if not cfg_dir.is_dir():
        return None

    toml_path = cfg_dir / "config.toml"
    if toml_path.is_file():
        return toml_path

    json_path = cfg_dir / "config.json"
    if json_path.is_file():
        return json_path

    return None


def load_user_config(
    config_path: Path | str | None = None,
    *,
    platform: str | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Load and parse the user configuration file into a dictionary."""
    resolved_path = find_config_file(config_path, platform=platform, environ=environ)
    if resolved_path is None:
        return {}

    try:
        content = resolved_path.read_text(encoding="utf-8")
    except OSError as err:
        raise ConfigError(f"Failed to read configuration file {resolved_path}: {err}") from err

    if not content.strip():
        return {}

    is_json = resolved_path.suffix.lower() == ".json"
    if is_json:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as err:
            raise ConfigError(f"Invalid JSON in configuration file {resolved_path}: {err}") from err
    else:
        if tomllib is not None:
            try:
                data = tomllib.loads(content)
            except Exception as err:
                raise ConfigError(f"Invalid TOML in configuration file {resolved_path}: {err}") from err
        else:  # pragma: no cover
            try:
                data = json.loads(content)
            except json.JSONDecodeError as err:
                raise ConfigError(
                    f"No TOML parser available and file {resolved_path} is not valid JSON: {err}"
                ) from err

    if not isinstance(data, dict):
        raise ConfigError(f"Configuration root must be a table/mapping, got {type(data).__name__}")

    return data


def get_web_config(raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract and validate the `[web]` configuration section."""
    if raw_config is None:
        raw_config = load_user_config()

    web_section = raw_config.get("web")
    if not isinstance(web_section, dict):
        # Fall back to top-level if no [web] section
        web_section = raw_config

    result: dict[str, Any] = {}

    if "port" in web_section and web_section["port"] is not None:
        port = int(web_section["port"])
        if not 1 <= port <= 65535:
            raise ValueError(f"port must be between 1 and 65535, got {port}")
        result["port"] = port

    if "endpoint" in web_section and web_section["endpoint"] is not None:
        result["endpoint"] = str(web_section["endpoint"]).rstrip("/")

    if "gateway" in web_section and web_section["gateway"] is not None:
        result["gateway"] = bool(web_section["gateway"])

    if "gateway_upstream" in web_section and web_section["gateway_upstream"] is not None:
        result["gateway_upstream"] = str(web_section["gateway_upstream"]).rstrip("/")

    if "record_inferences" in web_section and web_section["record_inferences"] is not None:
        val = str(web_section["record_inferences"]).lower().strip()
        if val in {"none", "off", "disabled", ""}:
            result["record_inferences"] = None
        elif val in {"metadata", "content"}:
            result["record_inferences"] = val
        else:
            raise ValueError(
                f"record_inferences must be 'metadata', 'content', 'none', or 'off'; got {val!r}"
            )

    # Support both no_browser = true and browser = false
    if "no_browser" in web_section and web_section["no_browser"] is not None:
        result["no_browser"] = bool(web_section["no_browser"])
    elif "browser" in web_section and web_section["browser"] is not None:
        result["no_browser"] = not bool(web_section["browser"])

    if "database" in web_section and web_section["database"]:
        result["database"] = str(web_section["database"]).strip()
    elif "database" in web_section and not web_section["database"]:
        result["database"] = None

    if "refresh_interval" in web_section and web_section["refresh_interval"] is not None:
        interval = float(web_section["refresh_interval"])
        if interval <= 0:
            raise ValueError(f"refresh_interval must be greater than zero, got {interval}")
        result["refresh_interval"] = interval

    if "gateway_timing" in web_section and web_section["gateway_timing"] is not None:
        result["gateway_timing"] = bool(web_section["gateway_timing"])

    return result


def resolve_web_options(
    cli_args: Any,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve web execution parameters with precedence:

    Explicit CLI arguments > user configuration > built-in defaults.
    """
    if config is None:
        config = get_web_config()

    # Built-in defaults
    default_port = 8788
    default_endpoint = "http://127.0.0.1:1234"
    default_refresh_interval = 2.0

    # 1. Port
    port = cli_args.port if getattr(cli_args, "port", None) is not None else config.get("port", default_port)

    # 2. Endpoint
    endpoint = (
        cli_args.endpoint
        if getattr(cli_args, "endpoint", None) is not None
        else config.get("endpoint", default_endpoint)
    )

    # 3. Gateway enabled
    gateway_cli = getattr(cli_args, "gateway", None)
    if gateway_cli is not None:
        gateway_enabled = bool(gateway_cli)
    else:
        gateway_enabled = bool(config.get("gateway", False))

    # 4. Gateway upstream
    gw_upstream_cli = getattr(cli_args, "gateway_upstream", None)
    if gw_upstream_cli is not None:
        gateway_upstream = gw_upstream_cli
    elif "gateway_upstream" in config and config["gateway_upstream"]:
        gateway_upstream = config["gateway_upstream"]
    else:
        gateway_upstream = endpoint

    # 5. Browser suppression (no_browser)
    no_browser_cli = getattr(cli_args, "no_browser", None)
    if no_browser_cli is not None:
        no_browser = bool(no_browser_cli)
    else:
        no_browser = bool(config.get("no_browser", False))

    # 6. Recording mode
    rec_cli = getattr(cli_args, "record_inferences", None)
    if rec_cli is not None:
        rec_val = str(rec_cli).lower().strip()
        if rec_val in {"none", "off", "disabled"}:
            record_inferences = None
        else:
            record_inferences = rec_cli
    elif gateway_cli is False:
        # Gateway was explicitly disabled on CLI; suppress configured recording
        record_inferences = None
    else:
        rec_val = config.get("record_inferences")
        if rec_val in {"none", "off", "disabled", None}:
            record_inferences = None
        else:
            record_inferences = rec_val

    # 7. Database path
    db_cli = getattr(cli_args, "database", None)
    if db_cli is not None:
        database = str(db_cli)
    elif config.get("database"):
        database = str(config["database"])
    else:
        database = None

    # 8. Refresh interval
    interval_cli = getattr(cli_args, "refresh_interval", None)
    if interval_cli is not None:
        refresh_interval = float(interval_cli)
    else:
        refresh_interval = float(config.get("refresh_interval", default_refresh_interval))

    # 9. Gateway timing
    timing_cli = getattr(cli_args, "gateway_timing", None)
    if timing_cli is not None:
        gateway_timing = bool(timing_cli)
    else:
        gateway_timing = bool(config.get("gateway_timing", False))

    return {
        "port": port,
        "endpoint": endpoint,
        "gateway_enabled": gateway_enabled,
        "gateway": gateway_enabled,
        "gateway_upstream": gateway_upstream,
        "no_browser": no_browser,
        "record_inferences": record_inferences,
        "database": database,
        "refresh_interval": refresh_interval,
        "gateway_timing": gateway_timing,
    }
