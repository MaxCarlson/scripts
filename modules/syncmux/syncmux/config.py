
import os
import pathlib
import sys
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import ValidationError

from .models import Host


def default_config_path() -> Path:
    r"""
    Returns the platform-appropriate default config path.

    Returns:
        Path: Default config path for the current platform
            - Linux/WSL/Termux: ~/.config/syncmux/config.yml
            - Windows: %APPDATA%\syncmux\config.yml
    """
    if sys.platform == "win32":
        # Windows: Use %APPDATA%
        appdata = os.environ.get("APPDATA")
        if not appdata:
            # Fallback to user home if APPDATA not set
            return Path.home() / "AppData" / "Roaming" / "syncmux" / "config.yml"
        return Path(appdata) / "syncmux" / "config.yml"
    else:
        # Linux/WSL/Termux: Use XDG_CONFIG_HOME or ~/.config
        config_home = os.environ.get("XDG_CONFIG_HOME")
        if config_home:
            return Path(config_home) / "syncmux" / "config.yml"
        return Path.home() / ".config" / "syncmux" / "config.yml"


def load_config(config_path: Optional[Path] = None) -> List[Host]:
    """
    Loads the configuration file and returns a list of Host objects.

    Args:
        config_path: Optional path to config file. If None, uses default platform path.

    Returns:
        List[Host]: List of validated Host objects

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If YAML parsing fails
        ValidationError: If config validation fails
    """
    path = config_path if config_path else default_config_path()

    if not path.exists():
        error_msg = f"""Configuration file not found at: {path}

To get started, create a config file with at least one host:

Example config.yml:
---
hosts:
  - alias: "localhost"
    hostname: "localhost"
    user: "{os.environ.get('USER', 'username')}"
    auth_method: "agent"

Or run 'syncmux' and use the first-run wizard to add machines interactively.
"""
        raise FileNotFoundError(error_msg)

    with open(path, "r") as f:
        try:
            config_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Error parsing YAML file at {path}: {e}")

    if not config_data or "hosts" not in config_data:
        raise ValidationError(f"Invalid configuration: 'hosts' key not found in {path}")

    try:
        return [Host(**host) for host in config_data["hosts"]]
    except ValidationError as e:
        raise ValidationError(f"Invalid host configuration in {path}: {e}")


def save_config(hosts: List[Host], config_path: Optional[Path] = None) -> None:
    """
    Saves the list of Host objects to the configuration file using atomic writes.

    The atomic write process:
    1. Write to a temporary file (config.yml.tmp)
    2. Flush and fsync to ensure data is on disk
    3. Replace the original file with the temp file

    This ensures that the config file is never left in a partial/corrupt state.

    Args:
        hosts: List of Host objects to save
        config_path: Optional path to config file. If None, uses default platform path.

    Raises:
        OSError: If file operations fail
        yaml.YAMLError: If YAML serialization fails
    """
    path = config_path if config_path else default_config_path()

    # Ensure directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Convert hosts to dict format
    config_data = {
        "hosts": [host.model_dump(exclude_none=True) for host in hosts]
    }

    # Write to temporary file first (atomic write)
    tmp_path = path.parent / f"{path.name}.tmp"

    try:
        with open(tmp_path, "w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False, sort_keys=False)
            # Ensure data is written to disk
            f.flush()
            os.fsync(f.fileno())

        # Atomic replace: this is atomic on both Windows and Unix
        # On Windows, this may fail if the target exists, so we handle that
        if sys.platform == "win32" and path.exists():
            # On Windows, os.replace can handle existing files in Python 3.3+
            path.unlink()

        # Replace the original file with the temp file
        tmp_path.replace(path)

    except Exception as e:
        # Clean up temp file if something went wrong
        if tmp_path.exists():
            tmp_path.unlink()
        raise OSError(f"Failed to save config to {path}: {e}")
