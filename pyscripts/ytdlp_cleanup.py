# file: cleanup_part_frag.py
# -*- coding: utf-8 -*-
"""
Cleanup helper for .part and *-frag* files and duplicate full files.

Usage examples:
  # Dry-run (default): show what would be removed and folder counts
  python cleanup_part_frag.py -p "/path/to/root"

  # Consider recent activity window of 12 hours; “old” means 3 days
  python cleanup_part_frag.py -p "/path" -r 12 -a 3

  # Also search for duplicate full media files (by size + SHA256)
  python cleanup_part_frag.py -p "/path" -d

  # Delete only safe categories after a single confirmation prompt
  python cleanup_part_frag.py -p "/path" --delete

  # Non-interactive delete (CAUTION)
  python cleanup_part_frag.py -p "/path" --delete --no-prompt
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# -------------------------------
# Configuration & Patterns
# -------------------------------

# Common "full" media file extensions (lowercased, without dot)
DEFAULT_MEDIA_EXT = {
    "mp4",
    "mkv",
    "webm",
    "mov",
    "avi",
    "mpg",
    "mpeg",
    "m4v",
    "mp3",
    "m4a",
    "aac",
    "flac",
    "wav",
    "ogg",
    "opus",
}

# Regexes to detect partial/fragment styles and derive their "base" filename.
# We attempt multiple transforms until one yields a plausible base name.
_PATTERNS: Sequence[Tuple[re.Pattern, str]] = (
    # 1) filename.ext.part  -> filename.ext
    (re.compile(r"(?i)^(?P<stem>.+)\.part(?:[\.-].*)?$"), r"\g<stem>"),
    # 2) filename.mp4-frag123 -> filename.mp4
    (
        re.compile(r"(?i)^(?P<stem>.+\.(?P<ext>[a-z0-9]{2,5}))[-\.]?frag\d+(?:\..*)?$"),
        r"\g<stem>",
    ),
    # 3) filename-fragXX (no explicit ext) -> filename  (least specific)
    (re.compile(r"(?i)^(?P<stem>.+)[-\.]frag\d+(?:\..*)?$"), r"\g<stem>"),
    # 4) filename.part-fragXXX -> filename
    (re.compile(r"(?i)^(?P<stem>.+)\.part[-\.]frag\d+(?:\..*)?$"), r"\g<stem>"),
)


def is_partial_or_frag(p: Path) -> bool:
    n = p.name.lower()
    return (".part" in n) or ("frag" in n)


def derive_base_candidates(filename: str) -> List[str]:
    """
    Given a partial/frag filename, return candidate base names in the same folder.
    We try a few regex transformations. Duplicates are removed while preserving order.
    """
    cands: List[str] = []
    for pat, repl in _PATTERNS:
        m = pat.match(filename)
        if m:
            val = pat.sub(repl, filename)
            if val and val not in cands:
                cands.append(val)
    # Also: if something like "name.ext.part" didn't match earlier forms
    if filename.lower().endswith(".part"):
        base = filename[:-5]
        if base and base not in cands:
            cands.append(base)
    return cands


def path_casefold(p: Path) -> str:
    return str(p.name).casefold()


# -------------------------------
# Data structures
# -------------------------------


@dataclass
class Classified:
    completed_leftovers: List[Path]
    maybe_active: List[Path]
    orphans_old: List[Path]
    orphans_unknown: List[Path]

    def all_paths(self) -> List[Path]:
        return (
            self.completed_leftovers
            + self.maybe_active
            + self.orphans_old
            + self.orphans_unknown
        )


# -------------------------------
# Core classification
# -------------------------------


def classify_part_and_frag(
    root: Path,
    recent_hours: int = 24,
    old_days: int = 7,
    media_ext: Optional[Sequence[str]] = None,
) -> Tuple[Classified, Dict[Path, Dict[str, int]]]:
    """
    Walk 'root' and classify partial/frag files.
    Returns:
        - Classified lists
        - per_folder_counts: {folder: {'completed_leftovers': X, 'maybe_active': Y, ...}}
    """
    exts = {e.lower().lstrip(".") for e in (media_ext or DEFAULT_MEDIA_EXT)}
    now = time.time()
    recent_cutoff = now - (recent_hours * 3600)
    old_cutoff = now - (old_days * 86400)

    completed_leftovers: List[Path] = []
    maybe_active: List[Path] = []
    orphans_old: List[Path] = []
    orphans_unknown: List[Path] = []

    per_folder_counts: Dict[Path, Dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    for dirpath, _, files in os.walk(root):
        d = Path(dirpath)
        # Build a quick set for name lookups within the same folder (case-insensitive)
        names_ci = {f.casefold(): f for f in files}
        for fname in files:
            p = d / fname
            if not is_partial_or_frag(p):
                continue

            # Derive possible base names that may exist in the same directory.
            candidates = derive_base_candidates(fname)
            base_found = False
            base_path: Optional[Path] = None
            for cand in candidates:
                cand_ci = cand.casefold()
                if cand_ci in names_ci:
                    base_found = True
                    base_path = d / names_ci[cand_ci]
                    break

            st = p.stat()
            mtime = st.st_mtime

            # If a base file exists and appears like a "full" media file -> leftover
            if base_found and base_path:
                if base_path.suffix.lower().lstrip(".") in exts:
                    completed_leftovers.append(p)
                    per_folder_counts[d]["completed_leftovers"] += 1
                    continue

            # No base file in same folder. Decide if "active" or orphan (old/unknown)
            if mtime >= recent_cutoff:
                maybe_active.append(p)
                per_folder_counts[d]["maybe_active"] += 1
            else:
                if mtime <= old_cutoff:
                    orphans_old.append(p)
                    per_folder_counts[d]["orphans_old"] += 1
                else:
                    orphans_unknown.append(p)
                    per_folder_counts[d]["orphans_unknown"] += 1

    classified = Classified(
        completed_leftovers=completed_leftovers,
        maybe_active=maybe_active,
        orphans_old=orphans_old,
        orphans_unknown=orphans_unknown,
    )
    return classified, per_folder_counts


# -------------------------------
# Duplicate detection for full files
# -------------------------------


def iter_full_media_files(root: Path, media_ext: Sequence[str]) -> Iterable[Path]:
    exts = {e.lower().lstrip(".") for e in (media_ext or [])}
    for dirpath, _, files in os.walk(root):
        d = Path(dirpath)
        for fname in files:
            p = d / fname
            if is_partial_or_frag(p):
                continue
            if p.suffix.lower().lstrip(".") in exts:
                yield p


def sha256_of_file(p: Path, bufsize: int = 2**20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            chunk = f.read(bufsize)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def find_duplicate_full_files(
    root: Path, media_ext: Optional[Sequence[str]] = None
) -> Dict[str, List[Path]]:
    """
    Return {hash: [paths...]} for duplicates (2+ paths) among full media files.
    """
    exts = list(media_ext or DEFAULT_MEDIA_EXT)
    # First group by size (fast pre-filter)
    size_groups: Dict[int, List[Path]] = defaultdict(list)
    for p in iter_full_media_files(root, exts):
        try:
            size_groups[p.stat().st_size].append(p)
        except FileNotFoundError:
            continue

    dups: Dict[str, List[Path]] = {}
    for size, files in size_groups.items():
        if len(files) < 2:
            continue
        for p in files:
            try:
                h = sha256_of_file(p)
            except FileNotFoundError:
                continue
            dups.setdefault(h, []).append(p)

    # Keep only real duplicates (>=2 paths per hash)
    return {h: ps for h, ps in dups.items() if len(ps) >= 2}


# -------------------------------
# Deletion (with single confirmation)
# -------------------------------


def delete_paths(paths: Iterable[Path]) -> Tuple[int, List[Tuple[Path, str]]]:
    """
    Delete files, returning (count_deleted, failures[(path, reason)]).
    """
    deleted = 0
    failures: List[Tuple[Path, str]] = []
    for p in paths:
        try:
            p.unlink()
            deleted += 1
        except Exception as e:
            failures.append((p, str(e)))
    return deleted, failures


# -------------------------------
# Printing helpers
# -------------------------------


def human_rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def print_folder_counts(
    per_folder_counts: Dict[Path, Dict[str, int]], root: Path
) -> None:
    if not per_folder_counts:
        print("\nNo .part/*frag* files found.")
        return
    print("\nPer-folder counts:")
    for folder in sorted(per_folder_counts.keys(), key=lambda x: str(x).casefold()):
        counts = per_folder_counts[folder]
        total = sum(counts.values())
        if total == 0:
            continue
        print(f"  {human_rel(folder, root)}")
        for k in (
            "completed_leftovers",
            "maybe_active",
            "orphans_old",
            "orphans_unknown",
        ):
            if counts.get(k, 0):
                print(f"    {k:20s}: {counts[k]}")
        print(f"    {'total':20s}: {total}")


def print_classified(classified: Classified, root: Path) -> None:
    def dump(title: str, items: List[Path]) -> None:
        print(f"\n[{title}] ({len(items)})")
        for p in sorted(items, key=lambda x: human_rel(x, root).casefold()):
            print("  " + human_rel(p, root))

    dump(
        "completed_leftovers (full file exists in same folder)",
        classified.completed_leftovers,
    )
    dump("maybe_active (recently modified)", classified.maybe_active)
    dump("orphans_old (no full file, old)", classified.orphans_old)
    dump("orphans_unknown (no full file, not old)", classified.orphans_unknown)


def print_duplicates(dups: Dict[str, List[Path]], root: Path) -> None:
    if not dups:
        print("\nNo duplicate full media files found.")
        return
    print("\n[duplicate_full_files] (by SHA256, groups >= 2)")
    for h, paths in dups.items():
        print(f"  hash={h[:12]}…  count={len(paths)}")
        for p in sorted(paths, key=lambda x: human_rel(x, root).casefold()):
            print(f"    {human_rel(p, root)}")


# -------------------------------
# CLI
# -------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cleanup_part_frag",
        description="Scan for .part and *frag* files, classify, and optionally delete safe leftovers.",
    )
    ap.add_argument("-p", "--path", required=True, help="Root folder to scan.")
    ap.add_argument(
        "-r",
        "--recent_hours",
        type=int,
        default=24,
        help="Files modified within this many hours are treated as 'maybe_active'. Default: 24",
    )
    ap.add_argument(
        "-a",
        "--age_days",
        type=int,
        default=7,
        help="Without a full file present, files older than this many days are 'orphans_old'. Default: 7",
    )
    ap.add_argument(
        "-e",
        "--media_ext",
        nargs="*",
        default=sorted(DEFAULT_MEDIA_EXT),
        help="Full media extensions considered when matching bases and duplicates (no dots).",
    )
    ap.add_argument(
        "-d",
        "--find_duplicates",
        action="store_true",
        help="Also find duplicate full media files across subfolders (size + SHA256).",
    )
    ap.add_argument(
        "-D",
        "--delete",
        action="store_true",
        help="After scan, offer to delete 'completed_leftovers' and 'orphans_old'. Dry-run otherwise.",
    )
    ap.add_argument(
        "-n",
        "--no-prompt",
        action="store_true",
        help="Do deletions without confirmation (DANGER). Implies --delete.",
    )
    ap.add_argument("-v", "--verbose", action="store_true", help="More chatter.")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"ERROR: path does not exist: {root}", file=sys.stderr)
        return 2

    if args.no_prompt:
        args.delete = True

    if args.verbose:
        print(f"Scanning: {root}")
        print(f"recent_hours={args.recent_hours}  age_days={args.age_days}")
        print(f"media_ext={args.media_ext}")

    classified, per_folder_counts = classify_part_and_frag(
        root=root,
        recent_hours=args.recent_hours,
        old_days=args.age_days,
        media_ext=args.media_ext,
    )

    print_folder_counts(per_folder_counts, root)
    print_classified(classified, root)

    dups = {}
    if args.find_duplicates:
        print("\nScanning for duplicate full media files (this may take a while)…")
        dups = find_duplicate_full_files(root, media_ext=args.media_ext)
        print_duplicates(dups, root)

    # Deletion flow
    if args.delete:
        delete_candidates = sorted(
            set(classified.completed_leftovers + classified.orphans_old),
            key=lambda p: human_rel(p, root).casefold(),
        )
        if not delete_candidates:
            print("\nNothing to delete from safe categories.")
            return 0

        print("\n[Deletion preview]")
        for p in delete_candidates:
            print("  " + human_rel(p, root))
        if not args.no_prompt:
            ans = input("\nProceed to DELETE the above files? [y/N]: ").strip().lower()
            if ans not in ("y", "yes"):
                print("Aborted. No files were deleted.")
                return 0

        deleted, failures = delete_paths(delete_candidates)
        print(f"\nDeleted {deleted} file(s).")
        if failures:
            print("Failures:")
            for p, reason in failures:
                print(f"  {human_rel(p, root)}  ->  {reason}")
    else:
        print("\nDry run complete. No files were deleted.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
