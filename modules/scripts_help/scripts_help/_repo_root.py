"""Locate the scripts repository root at runtime."""

from __future__ import annotations

import os
from pathlib import Path


def _is_repo_root(p: Path) -> bool:
    return (p / "pyscripts").is_dir() and (p / "modules").is_dir()


def find_repo_root() -> Path:
    """
    Return the scripts repository root.

    Search order:
      1. $SCRIPTS env var (fastest; set by shell config in this repo)
      2. Walk up from CWD (works when run from inside the repo)
      3. Walk up from this file (works for editable installs inside the repo)

    Raises RuntimeError if none of the above succeed.
    """
    scripts_env = os.environ.get("SCRIPTS")
    if scripts_env:
        p = Path(scripts_env)
        if _is_repo_root(p):
            return p.resolve()

    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if _is_repo_root(candidate):
            return candidate.resolve()

    here = Path(__file__).resolve()
    for candidate in here.parents:
        if _is_repo_root(candidate):
            return candidate.resolve()

    raise RuntimeError(
        "Could not find the scripts repository root.\n"
        "Set the SCRIPTS environment variable to the repo path, or run from inside the repo."
    )
