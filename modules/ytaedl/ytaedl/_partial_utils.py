"""
Partial download directory utilities for ytaedl.

Each proxy channel directory now uses a ``_partial/`` subdirectory instead of
the old shared ``_tmp/`` folder.  Every URL in-progress gets its own isolated
working directory:

    B:\\stars\\<channel>\\
    ├── video1.mp4               ← completed
    └── _partial\\
        ├── a1b2c3d4e5f6\\       ← sha256(url)[:12]
        │   ├── meta.json        ← sentinel: url, file, line, slot, timestamp
        │   └── Title.mp4.part   ← yt-dlp in-progress fragments
        └── 9f8e7d6c5b4a\\
            ├── meta.json
            └── Title.f137.mp4.part

# Versioning
============

Each ``_partial/`` root contains a ``.version`` file:

    {"partial_version": "2.0.0", "created_at": <unix timestamp>}

Version scheme: MAJOR.MINOR.PATCH

- **MAJOR** version bumps are *breaking*: old-format partial directories are
  incompatible.  When the running code's major version differs from the stored
  value, ytaedl will refuse to use existing partial dirs without explicit user
  confirmation, and will offer to delete them before proceeding.
- **MINOR / PATCH** bumps are backwards-compatible within the same major.

# How to bump the major version
=================================

1. Increment ``PARTIAL_SYSTEM_VERSION`` in this file (e.g. "2.0.0" → "3.0.0").
2. Add an entry to ``PARTIAL_SYSTEM_CHANGELOG`` keyed by the new major integer.
3. On next startup the manager detects the mismatch, prints the changelog entry
   and the deletion summary, then asks the user to type DELETE to confirm.
4. Update README.md's "Partial Download System Version History" table.
5. Commit with message: "partial: bump major version to N — <reason>"

# Deletion safety
==================

- Finished ``.mp4`` files in channel directories are **never** touched.
- Only files inside ``_partial/<hash>/`` subdirectories are deleted.
- Any non-routine deletion (i.e., beyond success-time cleanup of a single
  just-completed URL) prints a summary in red and requires the user to type
  the word DELETE before proceeding.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Version constants
# ---------------------------------------------------------------------------

PARTIAL_SYSTEM_VERSION = "2.0.0"
PARTIAL_SYSTEM_MAJOR = int(PARTIAL_SYSTEM_VERSION.split(".")[0])

PARTIAL_DIR_NAME = "_partial"
VERSION_FILE_NAME = ".version"
META_FILE_NAME = "meta.json"

# Update this when bumping MAJOR — the value is printed to the user before
# they are asked to confirm deletion of old-format data.
PARTIAL_SYSTEM_CHANGELOG: Dict[int, str] = {
    2: (
        "v2.0.0: Replaced the shared _tmp/ working directory with per-URL "
        "isolated _partial/<url_hash12>/ directories.  Each directory contains "
        "a meta.json sentinel identifying the URL, allowing reliable resume "
        "detection and priority scheduling.  Old _tmp/ directories (major v1) "
        "are incompatible and must be deleted."
    ),
}

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

def _red(msg: str) -> str:
    return f"\033[31m\033[1m{msg}\033[0m"


def _reset() -> str:
    return "\033[0m"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def partial_root_for(channel_dir: Path) -> Path:
    """Return the ``_partial/`` root directory for a channel directory."""
    return channel_dir / PARTIAL_DIR_NAME


def partial_dir_for(url: str, partial_root: Path) -> Path:
    """
    Return the per-URL working directory path.

    The directory name is the first 12 hex characters of SHA-256(url), giving
    a collision probability of < 1e-10 for up to 100 000 URLs.  The same URL
    always maps to the same directory, so yt-dlp can resume across restarts.
    """
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return partial_root / h


# ---------------------------------------------------------------------------
# Meta-file I/O
# ---------------------------------------------------------------------------

def write_partial_meta(
    partial_dir: Path,
    url: str,
    file_path: str,
    line_num: int,
    slot: int,
) -> None:
    """Write a ``meta.json`` sentinel *before* starting a download."""
    partial_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "url": url,
        "file_path": str(file_path),
        "line_num": line_num,
        "started_at": time.time(),
        "worker_slot": slot,
        "partial_version": PARTIAL_SYSTEM_VERSION,
    }
    (partial_dir / META_FILE_NAME).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def read_partial_meta(partial_dir: Path) -> Optional[dict]:
    """Return ``meta.json`` contents, or ``None`` if missing or corrupt."""
    meta_path = partial_dir / META_FILE_NAME
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------

def _is_hash_dir(name: str) -> bool:
    return len(name) == 12 and all(c in "0123456789abcdef" for c in name)


def _iter_hash_subdirs(partial_root: Path):
    """Yield each ``<hash>/`` subdirectory inside a ``_partial/`` dir."""
    try:
        for sub in partial_root.iterdir():
            if sub.is_dir() and _is_hash_dir(sub.name):
                yield sub
    except PermissionError:
        pass


def scan_partial_dirs(proxy_root: Path) -> List[Tuple[str, Path]]:
    """
    Find all active partial dirs under *proxy_root* by reading ``meta.json``
    files.

    Accepts either a proxy root (containing channel subdirs each with
    ``_partial/``) or a single channel directory that directly contains
    ``_partial/``.

    Returns a list of ``(url, partial_dir)`` pairs.
    """
    results: List[Tuple[str, Path]] = []
    if not proxy_root.exists():
        return results

    def _check_partial_root(proot: Path) -> None:
        for sub in _iter_hash_subdirs(proot):
            meta = read_partial_meta(sub)
            if meta and meta.get("url"):
                results.append((meta["url"], sub))

    own_partial = proxy_root / PARTIAL_DIR_NAME
    if own_partial.is_dir():
        _check_partial_root(own_partial)

    try:
        for child in proxy_root.iterdir():
            if child.is_dir() and child.name != PARTIAL_DIR_NAME:
                proot = child / PARTIAL_DIR_NAME
                if proot.is_dir():
                    _check_partial_root(proot)
    except PermissionError:
        pass

    return results


# ---------------------------------------------------------------------------
# Size helpers
# ---------------------------------------------------------------------------

def _sizeof_tree(path: Path) -> Tuple[int, int]:
    """Return ``(file_count, total_bytes)`` for a directory tree."""
    count, total = 0, 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                count += 1
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return count, total


def _fmt_bytes(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GiB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.2f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


# ---------------------------------------------------------------------------
# Cleanup target collection
# ---------------------------------------------------------------------------

@dataclass
class CleanupTarget:
    channel_dir: Path
    partial_root: Path
    subdirs: List[Path]
    file_count: int
    total_bytes: int
    urls: List[str] = field(default_factory=list)


@dataclass
class CleanupResult:
    deleted_dirs: int
    deleted_files: int
    freed_bytes: int
    archive_entries_removed: int
    dry_run: bool


def _collect_cleanup_targets(proxy_root: Path) -> List[CleanupTarget]:
    """
    Collect all ``_partial/<hash>/`` subdirectories that exist under
    *proxy_root*, grouped by channel.
    """
    targets: List[CleanupTarget] = []
    if not proxy_root.exists():
        return targets

    def _process_partial_root(proot: Path, channel_dir: Path) -> None:
        if not proot.is_dir():
            return
        subdirs: List[Path] = []
        total_files = 0
        total_bytes = 0
        urls: List[str] = []
        for sub in sorted(_iter_hash_subdirs(proot)):
            fc, tb = _sizeof_tree(sub)
            total_files += fc
            total_bytes += tb
            subdirs.append(sub)
            meta = read_partial_meta(sub)
            if meta and meta.get("url"):
                urls.append(meta["url"])
        if subdirs:
            targets.append(CleanupTarget(
                channel_dir=channel_dir,
                partial_root=proot,
                subdirs=subdirs,
                file_count=total_files,
                total_bytes=total_bytes,
                urls=urls,
            ))

    own_partial = proxy_root / PARTIAL_DIR_NAME
    if own_partial.is_dir():
        _process_partial_root(own_partial, proxy_root)

    try:
        for child in sorted(proxy_root.iterdir()):
            if child.is_dir() and child.name != PARTIAL_DIR_NAME:
                _process_partial_root(child / PARTIAL_DIR_NAME, child)
    except PermissionError:
        pass

    return targets


# ---------------------------------------------------------------------------
# Deletion summary + confirmation
# ---------------------------------------------------------------------------

def print_deletion_summary(targets: List[CleanupTarget]) -> None:
    """Print a red-highlighted summary of what will be deleted."""
    if not targets:
        print("No partial directories found.")
        return

    total_subdirs = sum(len(t.subdirs) for t in targets)
    total_files = sum(t.file_count for t in targets)
    total_bytes = sum(t.total_bytes for t in targets)

    print(_red("=" * 72))
    print(_red("  DELETION SUMMARY — In-Progress Partial Download Directories"))
    print(_red("=" * 72))
    for t in targets:
        print(_red(f"\n  Channel: {t.channel_dir.name}"))
        print(f"    Path:  {t.partial_root}")
        print(f"    Dirs:  {len(t.subdirs)}  |  Files: {t.file_count}  |  Size: {_fmt_bytes(t.total_bytes)}")
        for url in t.urls[:5]:
            print(f"      URL: {url}")
        if len(t.urls) > 5:
            print(f"      ... and {len(t.urls) - 5} more")
    print()
    print(_red(
        f"  TOTAL: {total_subdirs} partial dirs  |  "
        f"{total_files} files  |  {_fmt_bytes(total_bytes)}"
    ))
    print(_red("=" * 72))
    print()


def confirm_deletion(prompt_suffix: str = "") -> bool:
    """
    Prompt the user to type ``DELETE`` to confirm bulk deletion.

    Returns ``True`` if confirmed, ``False`` if cancelled.
    Refuses to auto-confirm when stdin is not a TTY (e.g. pipes/CI).
    """
    if not sys.stdin.isatty():
        print(_red(
            "[ERROR] Deletion requested but stdin is not a TTY.  "
            "Cannot confirm interactively.  Use --dry-run to preview, "
            "or run in an interactive terminal."
        ))
        return False
    try:
        prompt = (
            f"{_red('Really do this? DELETE all these files?')}"
            + (f" {prompt_suffix}" if prompt_suffix else "")
            + "\nType DELETE to confirm: "
        )
        answer = input(prompt).strip()
        return answer == "DELETE"
    except (EOFError, KeyboardInterrupt):
        print()
        return False


# ---------------------------------------------------------------------------
# Archive entry removal
# ---------------------------------------------------------------------------

def remove_archive_entries_for_urls(archive_dir: Path, urls: List[str]) -> int:
    """
    Remove all archive lines that reference any URL in *urls*.

    Returns the total number of lines removed across all archive files.
    Finished MP4 files are not touched — only text archive lines.
    """
    if not archive_dir or not archive_dir.exists() or not urls:
        return 0
    url_set = set(urls)
    removed = 0
    for archive_file in archive_dir.glob("*.txt"):
        try:
            text = archive_file.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines(keepends=True)
            new_lines = [ln for ln in lines if not any(u in ln for u in url_set)]
            if len(new_lines) < len(lines):
                archive_file.write_text("".join(new_lines), encoding="utf-8")
                removed += len(lines) - len(new_lines)
        except Exception:
            pass
    return removed


# ---------------------------------------------------------------------------
# Main cleanup entry-point
# ---------------------------------------------------------------------------

def cleanup_partial_dirs(
    proxy_root: Path,
    archive_dir: Optional[Path] = None,
    dry_run: bool = False,
    require_confirm: bool = True,
) -> CleanupResult:
    """
    Delete all ``_partial/<hash>/`` dirs under *proxy_root* and, optionally,
    remove the corresponding archive entries so those URLs are retried.

    Prints a coloured deletion summary.  When *require_confirm* is True (the
    default) the user must type ``DELETE`` before anything is removed.

    Finished ``.mp4`` files are **never** touched — only files inside
    ``_partial/`` subdirectories.
    """
    targets = _collect_cleanup_targets(proxy_root)
    if not targets:
        print("No partial directories to clean up.")
        return CleanupResult(0, 0, 0, 0, dry_run)

    print_deletion_summary(targets)

    if dry_run:
        print("[DRY RUN] No files deleted.")
        return CleanupResult(0, 0, 0, 0, dry_run=True)

    if require_confirm and not confirm_deletion():
        print("Deletion cancelled.")
        return CleanupResult(0, 0, 0, 0, dry_run=False)

    deleted_dirs = 0
    deleted_files = 0
    freed_bytes = 0
    all_urls: List[str] = []

    for target in targets:
        for subdir in target.subdirs:
            meta = read_partial_meta(subdir)
            if meta and meta.get("url"):
                all_urls.append(meta["url"])
            fc, tb = _sizeof_tree(subdir)
            try:
                shutil.rmtree(subdir)
                deleted_dirs += 1
                deleted_files += fc
                freed_bytes += tb
            except Exception as exc:
                print(f"[WARN] Failed to delete {subdir}: {exc}")

    archive_removed = 0
    if archive_dir and all_urls:
        archive_removed = remove_archive_entries_for_urls(archive_dir, all_urls)

    print(
        f"[CLEANUP] Deleted {deleted_dirs} partial dirs, "
        f"{deleted_files} files, freed {_fmt_bytes(freed_bytes)}."
    )
    if archive_removed:
        print(f"[CLEANUP] Removed {archive_removed} archive entries for cleaned URLs.")
    return CleanupResult(deleted_dirs, deleted_files, freed_bytes, archive_removed, dry_run=False)


# ---------------------------------------------------------------------------
# Version management
# ---------------------------------------------------------------------------

def read_partial_version(partial_root: Path) -> Optional[str]:
    """Read the version stored in ``partial_root/.version``."""
    vfile = partial_root / VERSION_FILE_NAME
    if not vfile.exists():
        return None
    try:
        data = json.loads(vfile.read_text(encoding="utf-8"))
        return data.get("partial_version")
    except Exception:
        return None


def write_partial_version(partial_root: Path) -> None:
    """Write the current ``PARTIAL_SYSTEM_VERSION`` to ``partial_root/.version``."""
    partial_root.mkdir(parents=True, exist_ok=True)
    vfile = partial_root / VERSION_FILE_NAME
    vfile.write_text(
        json.dumps(
            {"partial_version": PARTIAL_SYSTEM_VERSION, "created_at": time.time()},
            indent=2,
        ),
        encoding="utf-8",
    )


def is_partial_version_compatible(partial_root: Path) -> Tuple[bool, Optional[str]]:
    """
    Check if ``partial_root``'s stored major version matches the running code.

    Returns ``(is_compatible, stored_version_string)``.
    A missing ``.version`` file is treated as compatible (first use).
    """
    stored = read_partial_version(partial_root)
    if stored is None:
        return True, None
    try:
        stored_major = int(stored.split(".")[0])
    except (ValueError, IndexError):
        return False, stored
    return stored_major == PARTIAL_SYSTEM_MAJOR, stored


def check_and_migrate_proxy_root(
    proxy_root: Path,
    archive_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> bool:
    """
    Scan all channel ``_partial/`` directories under *proxy_root* for major
    version mismatches.

    If any mismatch is found:
    - Print the changelog entry for the new major version.
    - Print the deletion summary (red text).
    - Prompt the user to type ``DELETE`` before deleting old-format data.

    Returns ``True`` if it is safe to proceed (no mismatch, or user confirmed
    deletion).  Returns ``False`` if the user declined — the caller should
    abort startup.
    """
    if not proxy_root.exists():
        return True

    mismatched_roots: List[Path] = []
    try:
        for child in proxy_root.iterdir():
            if not child.is_dir():
                continue
            proot = child / PARTIAL_DIR_NAME
            if not proot.is_dir():
                continue
            ok, stored_ver = is_partial_version_compatible(proot)
            if not ok and stored_ver is not None:
                mismatched_roots.append(proot)
    except PermissionError:
        pass

    if not mismatched_roots:
        return True

    print(_red("\n" + "=" * 72))
    print(_red("  PARTIAL DIRECTORY VERSION MISMATCH"))
    print(_red(f"  Running:  {PARTIAL_SYSTEM_VERSION}  (major: {PARTIAL_SYSTEM_MAJOR})"))
    for proot in mismatched_roots:
        stored_ver = read_partial_version(proot)
        print(_red(f"  Stored:   {stored_ver}  in  {proot}"))
    print()
    changelog_note = PARTIAL_SYSTEM_CHANGELOG.get(PARTIAL_SYSTEM_MAJOR, "")
    if changelog_note:
        print(f"  What changed in major v{PARTIAL_SYSTEM_MAJOR}:")
        print(f"    {changelog_note}")
    print(_red("=" * 72 + "\n"))

    # Build targets only from mismatched partial roots
    all_targets: List[CleanupTarget] = []
    for proot in mismatched_roots:
        all_targets.extend(_collect_cleanup_targets(proot.parent))

    if all_targets:
        print_deletion_summary(all_targets)
        if not dry_run:
            confirmed = confirm_deletion(
                prompt_suffix="(old-format partial dirs from a previous major version)"
            )
            if not confirmed:
                print(_red(
                    "[ERROR] Cannot continue with incompatible partial "
                    "directories.  Run with --cleanup-partial-on-start to "
                    "force-delete them, or delete them manually."
                ))
                return False
            all_urls: List[str] = [u for t in all_targets for u in t.urls]
            for target in all_targets:
                for subdir in target.subdirs:
                    try:
                        shutil.rmtree(subdir)
                    except Exception:
                        pass
            if archive_dir and all_urls:
                removed = remove_archive_entries_for_urls(archive_dir, all_urls)
                if removed:
                    print(f"[MIGRATE] Removed {removed} stale archive entries.")

    return True
