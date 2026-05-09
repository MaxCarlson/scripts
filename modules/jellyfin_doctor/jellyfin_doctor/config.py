"""Configuration containers for Jellyfin Doctor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import JellyfinPaths


@dataclass(frozen=True)
class RuntimeConfig:
    """Common runtime options shared by CLI commands."""

    paths: JellyfinPaths
    verbose: bool = False
    quiet: bool = False
    dry_run: bool = False
    yes: bool = False
    json_output: bool = False
    config_file: Path | None = None

