"""Version reading and staleness-checking for the help registry."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def _parse_version(v: str) -> tuple[int, ...]:
    """Return a tuple of ints from a version string, e.g. '1.4.0' → (1, 4, 0)."""
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) if parts else ()


def read_live_version(path: str) -> str | None:
    """
    Read the current version of a module from its source files.
    Returns None for pyscripts (unversioned) or if no version can be found.
    path is relative to repo root, e.g. "modules/clip_tools".
    """
    if not path.startswith("modules/"):
        return None

    abs_path = REPO_ROOT / path

    # 1. pyproject.toml (most authoritative)
    toml_path = abs_path / "pyproject.toml"
    if toml_path.exists():
        ver = _read_toml_version(toml_path)
        if ver:
            return ver

    # 2. __init__.py __version__
    init_path = abs_path / "__init__.py"
    if init_path.exists():
        ver = _read_init_version(init_path)
        if ver:
            return ver

    return None


def _read_toml_version(toml_path: Path) -> str | None:
    # Use tomllib (3.11+ stdlib) when available, else regex fallback.
    try:
        if sys.version_info >= (3, 11):
            import tomllib
            with open(toml_path, "rb") as fh:
                data = tomllib.load(fh)
            return data.get("project", {}).get("version")
        else:
            import tomli  # type: ignore[import]
            with open(toml_path, "rb") as fh:
                data = tomli.load(fh)
            return data.get("project", {}).get("version")
    except Exception:
        pass

    # Regex fallback (handles the consistent `version = "X.Y.Z"` pattern)
    try:
        text = toml_path.read_text(encoding="utf-8")
        m = re.search(r'^\s*version\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        return m.group(1) if m else None
    except Exception:
        return None


def _read_init_version(init_path: Path) -> str | None:
    try:
        text = init_path.read_text(encoding="utf-8")
        m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        return m.group(1) if m else None
    except Exception:
        return None


def is_stale(registry_version: str, live_version: str) -> bool:
    """
    Return True if live_version has a higher major or minor number than
    registry_version, indicating the registry entry may be outdated.
    Patch-only bumps (x.y.Z) are ignored.
    """
    reg = _parse_version(registry_version)
    live = _parse_version(live_version)

    reg_major  = reg[0]  if len(reg)  > 0 else 0
    reg_minor  = reg[1]  if len(reg)  > 1 else 0
    live_major = live[0] if len(live) > 0 else 0
    live_minor = live[1] if len(live) > 1 else 0

    return (live_major, live_minor) > (reg_major, reg_minor)


def collect_stale_items(registry: dict) -> list[dict]:
    """
    Walk the registry and return a list of items whose live version has a
    higher major/minor than the recorded version.
    Each result dict has keys: name, path, registry_version, live_version.
    """
    stale: list[dict] = []

    def _walk(node: dict) -> None:
        for item in node.get("items", []):
            reg_ver = item.get("version")
            if not reg_ver:
                continue
            live_ver = read_live_version(item["path"])
            if live_ver and is_stale(reg_ver, live_ver):
                stale.append({
                    "name": item["name"],
                    "path": item["path"],
                    "registry_version": reg_ver,
                    "live_version": live_ver,
                })
        for sub in node.get("subcategories", {}).values():
            _walk(sub)

    for cat in registry.values():
        _walk(cat)

    return stale
