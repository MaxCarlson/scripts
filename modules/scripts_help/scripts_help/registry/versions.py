"""Version reading and staleness-checking for the help registry."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from scripts_help._repo_root import find_repo_root


def _parse_version(v: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) if parts else ()


def read_live_version(path: str) -> str | None:
    """
    Read the current version of a module or pyscript from its source files.

    For modules (path starts with "modules/"):
      1. pyproject.toml [project] version
      2. __init__.py __version__ fallback

    For pyscripts (path starts with "pyscripts/"):
      Reads __version__ from the top of the .py file.

    Returns None if no version can be found.
    """
    abs_path = find_repo_root() / path

    if path.startswith("modules/"):
        toml_path = abs_path / "pyproject.toml"
        if toml_path.exists():
            ver = _read_toml_version(toml_path)
            if ver:
                return ver
        init_path = abs_path / "__init__.py"
        if init_path.exists():
            return _read_init_version(init_path)
        return None

    if path.startswith("pyscripts/") and path.endswith(".py"):
        if abs_path.exists():
            return _read_script_version(abs_path)
        return None

    return None


def _read_toml_version(toml_path: Path) -> str | None:
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

    try:
        text = toml_path.read_text(encoding="utf-8")
        m = re.search(r'^\s*version\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        return m.group(1) if m else None
    except Exception:
        return None


def _read_script_version(script_path: Path) -> str | None:
    """Read __version__ from a standalone pyscript (first 60 lines only)."""
    try:
        text = ""
        with open(script_path, encoding="utf-8") as fh:
            for _ in range(60):
                line = fh.readline()
                if not line:
                    break
                text += line
        m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
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
    """True if live major/minor is higher than the recorded version. Patch bumps are ignored."""
    reg  = _parse_version(registry_version)
    live = _parse_version(live_version)
    reg_maj,  reg_min  = (reg[0]  if len(reg)  > 0 else 0), (reg[1]  if len(reg)  > 1 else 0)
    live_maj, live_min = (live[0] if len(live) > 0 else 0), (live[1] if len(live) > 1 else 0)
    return (live_maj, live_min) > (reg_maj, reg_min)


def collect_stale_items(registry: dict) -> list[dict]:
    """Walk the registry and return items whose live version has a higher major/minor."""
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
