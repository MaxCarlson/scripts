#!/usr/bin/env python3
"""
Unpack a single text bundle (with lines like `-- FILE: path/to/file`)
into real files on disk.

Usage:
  python unpack_repo_txt.py -i agt.txt -o ./agt
  python unpack_repo_txt.py -i agt.txt -o . --force
  python unpack_repo_txt.py -i agt.txt -o ./agt --dry-run

Notes:
- Content before the first `-- FILE:` marker is ignored.
- Files are created relative to the output directory.
- Existing files are not overwritten unless --force is used.
"""

from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path
import re

FILE_MARKER_RE = re.compile(r"^\s*--\s*FILE:\s*(.+?)\s*$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Unpack a repo text bundle into files.")
    p.add_argument(
        "-i",
        "--input",
        required=True,
        help="Path to the input text file (e.g., agt.txt)",
    )
    p.add_argument(
        "-o",
        "--out",
        default=".",
        help="Output directory to write files into (default: current dir)",
    )
    p.add_argument(
        "-f", "--force", action="store_true", help="Overwrite files that already exist"
    )
    p.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing",
    )
    p.add_argument(
        "--strip-leading-newline",
        action="store_true",
        help="Strip a single leading blank line from each file's content",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    in_path = Path(args.input)
    out_dir = Path(args.out)

    if not in_path.exists():
        print(f"error: input file not found: {in_path}", file=sys.stderr)
        return 2

    try:
        raw = in_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"error: failed to read input: {e}", file=sys.stderr)
        return 2

    lines = raw.splitlines(keepends=True)

    # State
    current_rel: Path | None = None
    current_buf: list[str] = []
    files: list[tuple[Path, str]] = []

    def flush_current():
        nonlocal current_rel, current_buf, files
        if current_rel is None:
            return
        content = "".join(current_buf)
        if args.strip_leading_newline and content.startswith("\n"):
            content = content[1:]
        files.append((current_rel, content))
        current_rel, current_buf = None, []

    for ln in lines:
        m = FILE_MARKER_RE.match(ln)
        if m:
            # New file begins; flush any previous
            flush_current()
            rel = m.group(1).strip()
            # Normalize any accidental quoting or trailing markers
            rel = rel.strip(" \t")
            current_rel = Path(rel)
            continue
        if current_rel is not None:
            current_buf.append(ln)
        else:
            # Ignore header / preamble until first -- FILE:
            continue

    # Final flush
    flush_current()

    if not files:
        print("error: no `-- FILE: ...` markers found in input.", file=sys.stderr)
        return 3

    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    skipped = 0
    overwritten = 0

    for rel_path, content in files:
        dest = (out_dir / rel_path).resolve()
        # Safety: confine writes under the out_dir
        try:
            dest.relative_to(out_dir.resolve())
        except Exception:
            print(
                f"warn: refusing to write outside output dir: {dest}", file=sys.stderr
            )
            skipped += 1
            continue

        if args.dry_run:
            print(f"[dry-run] write: {dest} ({len(content)} bytes)")
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and not args.force:
            print(f"[skip] exists: {dest}")
            skipped += 1
            continue

        if dest.exists() and args.force:
            overwritten += 1
        else:
            created += 1

        try:
            dest.write_text(content, encoding="utf-8")
            print(f"[ok] wrote: {dest}")
        except Exception as e:
            print(f"[error] failed writing {dest}: {e}", file=sys.stderr)

    if args.dry_run:
        print(f"\nSummary (dry-run): would write {len(files)} files under {out_dir}")
    else:
        print(
            f"\nSummary: created={created} overwritten={overwritten} skipped={skipped} out={out_dir}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
