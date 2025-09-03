# File: scripts/modules/cross_platform/fs_utils.py
"""
cross_platform.fs_utils

Centralized, cross-platform filesystem utilities used by many scripts.

Highlights
- Safe relative path formatting that never raises on Windows drive/anchor/case differences.
- Exact suffix matching ('.jpg' != '.jpeg'); case-insensitive by default.
- Directory walking with excludes, depth limits, and optional symlink following.
- Aggregation helpers (per-directory match counts) and summary table lines.
- Best-effort file deletion with error collection.

Design
- Functions return plain data (lists, dicts, strings); callers decide how to print.
- No Rich dependency here; integrate with cross_platform.debug_utils console if desired.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence

import os


# ------------------------------
# Data structures
# ------------------------------

@dataclass(frozen=True)
class FsSearchResult:
    """Result of a directory scan by extension."""
    searched_dirs: List[Path]
    matched_files: List[Path]


# ------------------------------
# Core helpers
# ------------------------------

def normalize_ext(ext: str) -> str:
    """
    Normalize a file extension string to not include the leading dot.

    Raises:
        ValueError: if the extension is empty after stripping.
    """
    s = (ext or "").strip()
    if not s:
        raise ValueError("Extension cannot be empty")
    return s.lstrip(".")


def matches_ext(p: Path, want_ext: str, *, case_sensitive: bool = False) -> bool:
    """
    Return True if Path `p` has an exact extension of `want_ext`.
    Exact means '.jpg' != '.jpeg'. Case-insensitive by default.

    Examples:
        a.jpg vs 'jpg' => True
        a.JPG vs 'jpg' => True (unless case_sensitive=True)
        a.jpeg vs 'jpg' => False
    """
    suff = p.suffix  # includes leading dot if present
    if not suff:
        return False
    have = suff[1:]  # strip dot
    return have == want_ext if case_sensitive else have.lower() == want_ext.lower()


def _dir_depth(p: Path) -> int:
    """Count path parts; account for normalized absolute path."""
    return len(p.parts)


def iter_dirs(
    root: Path,
    *,
    follow_symlinks: bool = False,
    exclude_dir_globs: Sequence[str] | None = None,
    max_depth: int | None = None,
) -> Iterator[Path]:
    """
    Yield directories starting at `root` (including root), respecting excludes/depth.
    Excludes are matched against directory *names* (not full paths).
    """
    exclude_dir_globs = tuple(exclude_dir_globs or ())
    root_abs = root.resolve()
    root_depth = _dir_depth(root_abs)

    for dirpath, dirnames, _ in os.walk(root_abs, followlinks=follow_symlinks):
        current = Path(dirpath)

        # Filter dirnames in-place (prunes traversal)
        if exclude_dir_globs:
            dirnames[:] = [
                d for d in dirnames
                if not any(Path(d).match(pattern) for pattern in exclude_dir_globs)
            ]

        # Depth gate
        if max_depth is not None:
            current_depth = _dir_depth(Path(dirpath)) - root_depth
            if current_depth >= max_depth:
                dirnames[:] = []  # stop descending further

        yield current


def find_files_by_extension(
    root: Path,
    extension: str,
    *,
    case_sensitive: bool = False,
    follow_symlinks: bool = False,
    exclude_dir_globs: Sequence[str] | None = None,
    max_depth: int | None = None,
) -> FsSearchResult:
    """
    Return directories searched and files that match an exact extension suffix.
    """
    root_abs = root.resolve()
    if not root_abs.exists() or not root_abs.is_dir():
        raise FileNotFoundError(f"Path does not exist or is not a directory: {root}")

    ext = normalize_ext(extension)
    searched_dirs: List[Path] = []
    matched: List[Path] = []

    for d in iter_dirs(
        root_abs,
        follow_symlinks=follow_symlinks,
        exclude_dir_globs=exclude_dir_globs or (),
        max_depth=max_depth,
    ):
        searched_dirs.append(d)
        try:
            for child in d.iterdir():
                if child.is_file() and matches_ext(child, ext, case_sensitive=case_sensitive):
                    matched.append(child)
        except PermissionError:
            # Skip unreadable directories
            continue

    return FsSearchResult(searched_dirs=searched_dirs, matched_files=matched)


def delete_files(files: Iterable[Path]) -> list[tuple[Path, Exception]]:
    """
    Attempt to delete each file, returning a list of (path, error) for failures.
    Non-files are silently ignored (no error).
    """
    failures: list[tuple[Path, Exception]] = []
    for p in files:
        try:
            if p.is_file():
                p.unlink()
        except Exception as ex:  # noqa: BLE001
            failures.append((p, ex))
    return failures


# ------------------------------
# Relative path safety
# ------------------------------

def safe_relative_to(child: Path, base: Path) -> Path | str:
    """
    Robust replacement for Path.relative_to(base) that *never raises*.

    Behavior:
    - If `child` is inside `base` (after resolving), returns a **Path** relative to `base`.
    - Otherwise, returns the **absolute path string** to `child`.

    This guarantees callers never see `ValueError` and also avoids confusing
    results like `'..'`-prefixed paths when the child isn't actually within the base.
    """
    # Resolve without strict to tolerate broken symlinks / permission issues
    child_res = child.resolve(strict=False)
    base_res = base.resolve(strict=False)

    try:
        return child_res.relative_to(base_res)
    except Exception:
        # Not within base -> return absolute string
        return str(child_res)


def relpath_str(p: Path, root: Path, *, absolute_paths: bool = False) -> str:
    """
    Return a string for `p` that is either absolute, or safely relative to `root`
    using `safe_relative_to`. Never raises.
    """
    if absolute_paths:
        return str(p.resolve(strict=False))
    rel = safe_relative_to(p, root)
    return str(rel)


# ------------------------------
# Aggregation & summary
# ------------------------------

def aggregate_counts_by_parent(files: Iterable[Path]) -> Dict[Path, int]:
    """Return {directory_path: count} for parents of given files."""
    counts: Dict[Path, int] = {}
    for f in files:
        parent = f.parent
        counts[parent] = counts.get(parent, 0) + 1
    return counts


def dir_summary_lines(
    root: Path,
    counts: Dict[Path, int],
    *,
    top_n: int = 50,
    show_all: bool = False,
    absolute_paths: bool = False,
) -> List[str]:
    """
    Build printable lines for a simple folders-with-matches table.

    Uses `safe_relative_to` to avoid ValueError on mismatched absolute/relative roots.
    If a path isn't inside `root`, an absolute path will be shown (by design).
    """
    if not counts:
        return ["No folders contained matching files."]

    items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    if not show_all:
        items = items[:top_n]

    # Compute safe names and width
    names: List[str] = []
    for p, _ in items:
        names.append(relpath_str(p, root, absolute_paths=absolute_paths))
    name_w = max(6, max(len(s) for s in names))

    hdr = f"{'Folder'.ljust(name_w)}  {'Count':>7}"
    lines = ["📁 Folders with matches", hdr, "-" * len(hdr)]
    for (p, c), disp in zip(items, names):
        lines.append(f"{disp.ljust(name_w)}  {c:7d}")
    return lines


# ------------------------------
# Convenience: module-level wrapper
# ------------------------------

def scanned_files_by_extension(
    root: Path,
    extension: str,
    *,
    case_sensitive: bool = False,
    follow_symlinks: bool = False,
    exclude_dir_globs: Sequence[str] | None = None,
    max_depth: int | None = None,
) -> FsSearchResult:
    """Thin wrapper for find_files_by_extension to keep naming parallel with scripts."""
    return find_files_by_extension(
        root,
        extension,
        case_sensitive=case_sensitive,
        follow_symlinks=follow_symlinks,
        exclude_dir_globs=exclude_dir_globs,
        max_depth=max_depth,
    )
