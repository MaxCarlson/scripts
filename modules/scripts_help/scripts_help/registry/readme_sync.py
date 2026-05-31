"""README version-sync utilities for the scripts-help registry."""

from __future__ import annotations

import re
from pathlib import Path

from scripts_help._repo_root import find_repo_root
from scripts_help.registry.versions import is_stale

# README version tag — must appear within the first 15 lines:
#   <!-- version: X.Y.Z -->
_VERSION_RE = re.compile(r"<!--\s*version:\s*([\d]+(?:\.[\d]+)*)\s*-->", re.IGNORECASE)


def find_readme(item: dict, repo: Path | None = None) -> Path | None:
    """Return the canonical README path for a registry item, or None if not found.

    Canonical locations:
      modules/   →  modules/<name>/README.md
      pyscripts/ →  pyscripts/readme/<stem>.md
    """
    if repo is None:
        repo = find_repo_root()
    path = item["path"]
    if path.startswith("modules/"):
        p = repo / path / "README.md"
        return p if p.is_file() else None
    if path.startswith("pyscripts/") and path.endswith(".py"):
        stem = Path(path).stem
        p = repo / "pyscripts" / "readme" / f"{stem}.md"
        return p if p.is_file() else None
    return None


def read_readme_version(readme_path: Path) -> str | None:
    """Extract the <!-- version: X.Y.Z --> tag from the first 15 lines."""
    try:
        with open(readme_path, encoding="utf-8", errors="ignore") as fh:
            for _ in range(15):
                line = fh.readline()
                if not line:
                    break
                m = _VERSION_RE.search(line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def collect_readme_drift(registry: dict, read_live_version_fn) -> list[dict]:
    """Walk the registry and return items with README version issues.

    Each result dict:
      name, path, readme_path, program_version, readme_version, issue

    issue values:
      "missing"          — no README found at canonical location
      "no_version_tag"   — README exists but has no <!-- version: X.Y.Z --> tag
      "version_mismatch" — README major/minor version is behind live program version
    """
    repo = find_repo_root()
    results: list[dict] = []

    def _walk(node: dict) -> None:
        for item in node.get("items", []):
            readme = find_readme(item, repo)
            live_ver = read_live_version_fn(item["path"])
            if readme is None:
                results.append({
                    "name": item["name"],
                    "path": item["path"],
                    "readme_path": None,
                    "program_version": live_ver,
                    "readme_version": None,
                    "issue": "missing",
                })
                continue
            readme_ver = read_readme_version(readme)
            if readme_ver is None:
                results.append({
                    "name": item["name"],
                    "path": item["path"],
                    "readme_path": str(readme.relative_to(repo)),
                    "program_version": live_ver,
                    "readme_version": None,
                    "issue": "no_version_tag",
                })
            elif live_ver and is_stale(readme_ver, live_ver):
                results.append({
                    "name": item["name"],
                    "path": item["path"],
                    "readme_path": str(readme.relative_to(repo)),
                    "program_version": live_ver,
                    "readme_version": readme_ver,
                    "issue": "version_mismatch",
                })
            # else: in sync — skip
        for sub in node.get("subcategories", {}).values():
            _walk(sub)

    for cat in registry.values():
        _walk(cat)
    return results
