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

DEFAULT_MEDIA_EXT = {
    "mp4","mkv","webm","mov","avi","mpg","mpeg","m4v",
    "mp3","m4a","aac","flac","wav","ogg","opus"
}

_PATTERNS: Sequence[Tuple[re.Pattern, str]] = (
    (re.compile(r"(?i)^(?P<stem>.+)\.part(?:[\.-].*)?$"), r"\g<stem>"),
    (re.compile(r"(?i)^(?P<stem>.+\.(?P<ext>[a-z0-9]{2,5}))[-\.]?frag\d+(?:\..*)?$"), r"\g<stem>"),
    (re.compile(r"(?i)^(?P<stem>.+)[-\.]frag\d+(?:\..*)?$"), r"\g<stem>"),
    (re.compile(r"(?i)^(?P<stem>.+)\.part[-\.]frag\d+(?:\..*)?$"), r"\g<stem>"),
)

def is_partial_or_frag(p: Path) -> bool:
    n = p.name.lower()
    return (".part" in n) or ("frag" in n)

def derive_base_candidates(filename: str) -> List[str]:
    cands: List[str] = []
    for pat, repl in _PATTERNS:
        m = pat.match(filename)
        if m:
            val = pat.sub(repl, filename)
            if val and val not in cands:
                cands.append(val)
    if filename.lower().endswith(".part"):
        base = filename[:-5]
        if base and base not in cands:
            cands.append(base)
    return cands

@dataclass
class Classified:
    safe_to_delete: List[Path]
    keep_for_now: List[Path]

def classify_part_and_frag(
    root: Path,
    recent_hours: int = 24,
    old_days: int = 7,
    media_ext: Optional[Sequence[str]] = None,
) -> Tuple[Classified, Dict[Path, Dict[str, int]]]:
    exts = {e.lower().lstrip(".") for e in (media_ext or DEFAULT_MEDIA_EXT)}
    now = time.time()
    recent_cutoff = now - (recent_hours * 3600)
    old_cutoff = now - (old_days * 86400)

    safe_to_delete: List[Path] = []   # completed leftovers OR old orphans
    keep_for_now: List[Path] = []     # maybe-active or unknown

    per_folder_counts: Dict[Path, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for dirpath, _, files in os.walk(root):
        d = Path(dirpath)
        names_ci = {f.casefold(): f for f in files}
        for fname in files:
            p = d / fname
            if not is_partial_or_frag(p):
                continue

            # Does a plausible full file exist in the same dir?
            base_found = False
            base_is_media = False
            for cand in derive_base_candidates(fname):
                if cand.casefold() in names_ci:
                    base_found = True
                    if Path(names_ci[cand.casefold()]).suffix.lower().lstrip(".") in exts:
                        base_is_media = True
                    break

            mtime = p.stat().st_mtime
            if base_found and base_is_media:
                bucket = "completed_leftovers"
                safe_to_delete.append(p)
            else:
                if mtime >= recent_cutoff:
                    bucket = "maybe_active"
                    keep_for_now.append(p)
                else:
                    if mtime <= old_cutoff:
                        bucket = "orphans_old"
                        safe_to_delete.append(p)
                    else:
                        bucket = "orphans_unknown"
                        keep_for_now.append(p)

            per_folder_counts[d][bucket] += 1

    return Classified(safe_to_delete, keep_for_now), per_folder_counts

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
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def find_duplicate_full_files(root: Path, media_ext: Optional[Sequence[str]] = None) -> Dict[str, List[Path]]:
    exts = list(media_ext or DEFAULT_MEDIA_EXT)
    size_groups: Dict[int, List[Path]] = defaultdict(list)
    for p in iter_full_media_files(root, exts):
        try:
            size_groups[p.stat().st_size].append(p)
        except FileNotFoundError:
            continue
    dups: Dict[str, List[Path]] = {}
    for files in size_groups.values():
        if len(files) < 2:
            continue
        for p in files:
            try:
                h = sha256_of_file(p)
            except FileNotFoundError:
                continue
            dups.setdefault(h, []).append(p)
    return {h: ps for h, ps in dups.items() if len(ps) >= 2}

def _human_rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except Exception:
        return str(p)

def _print_counts(per_folder: Dict[Path, Dict[str, int]], root: Path) -> None:
    if not per_folder:
        print("\nNo .part/*frag* files found.")
        return
    print("\nPer-folder counts:")
    for folder in sorted(per_folder, key=lambda x: str(x).casefold()):
        counts = per_folder[folder]
        total = sum(counts.values())
        if not total:
            continue
        print(f"  {_human_rel(folder, root)}")
        for k in ("completed_leftovers","orphans_old","maybe_active","orphans_unknown"):
            if counts.get(k, 0):
                print(f"    {k:20s}: {counts[k]}")
        print(f"    {'total':20s}: {total}")

def _dump(title: str, items: List[Path], root: Path) -> None:
    print(f"\n[{title}] ({len(items)})")
    for p in sorted(items, key=lambda x: _human_rel(x, root).casefold()):
        print("  " + _human_rel(p, root))

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cleanup_part_frag",
        description="Scan recursively for .part/*frag* files, bucket into safe_to_delete vs keep_for_now, "
                    "optionally find duplicate full media files, and (optionally) delete safe items."
    )
    ap.add_argument("-p","--path", required=True, help="Root folder to scan.")
    ap.add_argument("-r","--recent_hours", type=int, default=24,
                    help="Modified within this many hours -> keep_for_now (maybe active). Default: 24")
    ap.add_argument("-a","--age_days", type=int, default=7,
                    help="Without a base full file, older than this many days -> safe_to_delete. Default: 7")
    ap.add_argument("-e","--media_ext", nargs="*", default=sorted(DEFAULT_MEDIA_EXT),
                    help="Full media extensions (no dot) used for base matching and duplicates.")
    ap.add_argument("-d","--find_duplicates", action="store_true",
                    help="Also report duplicate full media files (size+SHA256).")
    ap.add_argument("-D","--delete", action="store_true",
                    help="Offer to delete items in safe_to_delete after confirmation.")
    ap.add_argument("-n","--no-prompt", action="store_true",
                    help="Delete without confirmation (danger). Implies --delete.")
    ap.add_argument("-v","--verbose", action="store_true", help="Verbose output.")
    return ap

def delete_paths(paths: Iterable[Path]) -> Tuple[int, List[Tuple[Path, str]]]:
    deleted = 0
    failures: List[Tuple[Path, str]] = []
    for p in paths:
        try:
            p.unlink()
            deleted += 1
        except Exception as e:
            failures.append((p, str(e)))
    return deleted, failures

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"ERROR: path does not exist: {root}", file=sys.stderr)
        return 2

    classified, per_folder = classify_part_and_frag(
        root=root,
        recent_hours=args.recent_hours,
        old_days=args.age_days,
        media_ext=args.media_ext,
    )

    _print_counts(per_folder, root)
    _dump("safe_to_delete (completed leftovers + old orphans)", classified.safe_to_delete, root)
    _dump("keep_for_now (maybe active or unknown)", classified.keep_for_now, root)

    if args.find_duplicates:
        print("\nScanning for duplicate full media files…")
        dups = find_duplicate_full_files(root, args.media_ext)
        if not dups:
            print("No duplicate full media files found.")
        else:
            print("[duplicate_full_files]")
            for h, paths in dups.items():
                print(f"  hash={h[:12]}… count={len(paths)}")
                for p in sorted(paths, key=lambda x: _human_rel(x, root).casefold()):
                    print("    " + _human_rel(p, root))

    if args.no_prompt:
        args.delete = True

    if args.delete and classified.safe_to_delete:
        print("\n[Deletion preview]")
        for p in sorted(classified.safe_to_delete, key=lambda x: _human_rel(x, root).casefold()):
            print("  " + _human_rel(p, root))
        if not args.no_prompt:
            ans = input("\nProceed to DELETE the above files? [y/N]: ").strip().lower()
            if ans not in ("y","yes"):
                print("Aborted. No files were deleted.")
                return 0
        deleted, failures = delete_paths(classified.safe_to_delete)
        print(f"\nDeleted {deleted} file(s).")
        if failures:
            print("Failures:")
            for p, reason in failures:
                print(f"  {_human_rel(p, root)} -> {reason}")
    else:
        print("\nDry run complete. No files were deleted.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
