#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
llm_patcher.cli

Console interface for applying LEP/v1 edits from:
- a file
- stdin
- the clipboard (via user's cross_platform module if present, else optional pyperclip)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

# IMPORTANT: absolute import so tests can `import cli` without a package context
from applier import apply_from_text


def _get_clipboard_text() -> Optional[str]:
    """
    Try to read text from clipboard with the user's cross_platform module.
    Fallback to pyperclip if available. Returns None if neither works.
    """
    # Preferred: user-provided cross_platform package
    try:
        from cross_platform.clipboard_utils import get_clipboard  # type: ignore
        text = get_clipboard()
        if text is not None and text != "":
            return text
    except Exception:
        pass

    # Fallback: pyperclip (optional extra)
    try:
        import pyperclip  # type: ignore
        text = pyperclip.paste()
        if text is not None and text != "":
            return text
    except Exception:
        pass

    return None


def _read_input_source(args: argparse.Namespace) -> str:
    if args.file and args.file != "-":
        return Path(args.file).read_text(encoding="utf-8")

    if args.clipboard:
        text = _get_clipboard_text()
        if text is None:
            print(
                "Clipboard is unavailable. Please install and/or expose one of:\n"
                "  - cross_platform.clipboard_utils (preferred)\n"
                "  - pyperclip (pip install llm-patcher[clipboard])\n",
                file=sys.stderr,
            )
            sys.exit(1)
        return text

    # stdin (default) or explicit '-'
    data = sys.stdin.read()
    if not data:
        print("No input received on stdin. Use --file or --clipboard.", file=sys.stderr)
        sys.exit(1)
    return data


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="llm-patcher",
        description=(
            "Apply LLM-produced edits in LEP/v1 JSON (single code block).\n"
            "Input can be a file, stdin (default), or clipboard."
        ),
    )
    p.add_argument(
        "--file", "-f", type=str, default="-",
        help="Path to file containing LEP JSON or fenced block. Use '-' for stdin (default)."
    )
    p.add_argument(
        "--clipboard", action="store_true",
        help="Read LEP JSON / fenced block text from clipboard."
    )
    p.add_argument(
        "--repo-root", type=str, default=".",
        help="Repository root (default: current directory)."
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Analyze and report but do not write."
    )
    p.add_argument(
        "--force", action="store_true",
        help="Ignore preimage sha256 mismatches."
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="Less verbose output."
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    lep_text = _read_input_source(args)
    code = apply_from_text(
        lep_text,
        repo_root=args.repo_root,
        dry_run=args.dry_run,
        force=args.force,
        quiet=args.quiet,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
