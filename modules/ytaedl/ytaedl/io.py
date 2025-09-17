#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""File/URL I/O helpers (with archive utilities)."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Set


def read_urls_from_files(paths: Iterable[Path]) -> List[str]:
    """
    Read all non-comment, non-empty lines from the provided files.

    Rules:
    - Full-line comments starting with '#', ';', or ']' are ignored.
    - Inline comments after ' # ' or ' ; ' are stripped (space then hash/semicolon).
    - Returns a de-duplicated list while preserving first-seen order.
    """
    out: List[str] = []
    seen: Set[str] = set()
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            ln = raw.strip()
            if not ln:
                continue
            if ln.startswith("#") or ln.startswith(";") or ln.startswith("]"):
                continue
            # strip common inline comments
            for marker in (" # ", " ; "):
                if marker in ln:
                    ln = ln.split(marker, 1)[0].strip()
            if not ln or ln in seen:
                continue
            seen.add(ln)
            out.append(ln)
    return out


def load_archive(path: Path | str) -> Set[str]:
    """Load a simple newline-delimited archive file into a set."""
    p = Path(path)
    if not p.exists():
        return set()
    try:
        return {
            ln.strip()
            for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines()
            if ln.strip()
        }
    except Exception:
        return set()


def save_archive(path: Path | str, urls: Iterable[str]) -> None:
    """
    Overwrite the archive file with the given URLs.

    Kept for compatibility with tests that import `save_archive`.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # normalize and stable order
    normed = [u.strip() for u in urls if str(u).strip()]
    # keep deterministic order without losing duplicates semantics in most callers
    seen: Set[str] = set()
    unique = []
    for u in normed:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    p.write_text("\n".join(unique) + ("\n" if unique else ""), encoding="utf-8")


def write_to_archive(path: Path | str, url: str) -> None:
    """Append a single URL (trimmed) to the archive file, creating parents as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(str(url).strip() + "\n")


def expand_url_dirs(dirs: Iterable[Path]) -> List[Path]:
    """Collect *.txt files from the given directories (non-recursive), sorted."""
    out: List[Path] = []
    for d in dirs:
        d = Path(d)
        if d.is_dir():
            out.extend(sorted(d.glob("*.txt")))
    return out
