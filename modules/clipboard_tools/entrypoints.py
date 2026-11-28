#!/usr/bin/env python3
"""
Entry points that reuse the existing pyscripts implementations.
This keeps aliases consistent across installs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure repo root (pyscripts, cross_platform, etc.) is importable in both editable and wheel installs.
_CANDIDATE_ROOTS: list[Path] = [Path(__file__).resolve().parents[2]]
for _env_key in ("SCRIPTS", "SCRIPTS_REPO"):
    _env_val = os.environ.get(_env_key)
    if _env_val:
        _CANDIDATE_ROOTS.append(Path(_env_val).expanduser())

REPO_ROOT = next((p for p in _CANDIDATE_ROOTS if (p / "pyscripts").is_dir()), _CANDIDATE_ROOTS[0])
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
MODULES_DIR = REPO_ROOT / "modules"
if MODULES_DIR.exists() and str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))


def _run_copy(argv=None) -> int:
    from pyscripts import copy_to_clipboard as c2c

    args = c2c.parser.parse_args(argv)
    return c2c.copy_files_to_clipboard(
        args.files,
        raw_copy=args.raw_copy,
        wrap=args.wrap,
        whole_wrap=args.whole_wrap,
        show_full_path=args.show_full_path,
        append=args.append,
        override_append_wrapping=args.override_append_wrapping,
        no_stats=args.no_stats,
        buffer_id=args.buffer,
        literal_text=getattr(args, "text", False),
        from_stdin=getattr(args, "stdin", False),
    )


def copy_main():
    sys.exit(_run_copy(None))


def copy_default_main():
    sys.exit(_run_copy(sys.argv[1:]))


def copy_recursive_main():
    sys.exit(_run_copy(["-r"] + sys.argv[1:]))


def copy_append_main():
    sys.exit(_run_copy(["-a"] + sys.argv[1:]))


def print_clipboard_main():
    from pyscripts import print_clipboard as pc

    args = pc.parser.parse_args()
    sys.exit(
        pc.print_clipboard_main(
            args.color,
            args.no_stats,
            args.buffer,
            args.buffers_summary,
            args.buffer_details,
        )
    )


def get_clipboard_short_main():
    """Cross-platform `gcb` entry point: prints clipboard without stats by default."""
    from pyscripts import print_clipboard as pc

    args = pc.parser.parse_args(["--no-stats"] + sys.argv[1:])
    sys.exit(
        pc.print_clipboard_main(
            args.color,
            args.no_stats,
            args.buffer,
            args.buffers_summary,
            args.buffer_details,
        )
    )


def set_clipboard_short_main():
    """Cross-platform `scb` entry point: accepts literal text, file path, or stdin."""
    import argparse
    from pyscripts import set_clipboard_text as sct

    p = argparse.ArgumentParser(prog="scb", description="Set clipboard from file path, literal text, or stdin.")
    p.add_argument("input_data", nargs="?", default=None, help="File path or literal text (omit to read stdin).")
    p.add_argument("-a", "--append", action="store_true", help="Append to existing clipboard content.")
    p.add_argument("-n", "--no-stats", action="store_true", help="Suppress stats output.")
    args = p.parse_args(sys.argv[1:])

    if args.input_data is not None and Path(args.input_data).is_file():
        fwd = ["-r"]
        if args.append:
            fwd.append("-a")
        if args.no_stats:
            fwd.append("--no-stats")
        fwd.append(args.input_data)
        sys.exit(_run_copy(fwd))

    sct_args: list[str] = []
    if args.input_data is not None:
        sct_args.extend(["-t", args.input_data])
    if args.append:
        sct_args.append("-a")
    if args.no_stats:
        sct_args.append("-n")
    sys.exit(sct.main(sct_args))


def replace_with_clipboard_main():
    from pyscripts import replace_with_clipboard as rwc

    args = rwc.parser.parse_args()
    sys.exit(rwc.replace_or_print_clipboard(args.file, args.no_stats, args.from_last_cld, args.buffer_id))


def replace_with_clipboard_from_last_main():
    from pyscripts import replace_with_clipboard as rwc

    args = rwc.parser.parse_args(["-F"] + sys.argv[1:])
    sys.exit(rwc.replace_or_print_clipboard(args.file, args.no_stats, args.from_last_cld, args.buffer_id))


def clipboard_diff_main():
    from pyscripts import clipboard_diff as cld

    sys.exit(cld.main(sys.argv[1:]))


def clipboard_summary_main():
    from clipboard_tools.compare_cli import clipboard_summary_main as summary_main

    sys.exit(summary_main(sys.argv[1:]))


def compare_files_main():
    from clipboard_tools.compare_cli import compare_main

    sys.exit(compare_main(sys.argv[1:]))


def compare_files_detailed_main():
    from clipboard_tools.compare_cli import compare_detailed_main

    sys.exit(compare_detailed_main(sys.argv[1:]))


def append_clipboard_main():
    from pyscripts import append_clipboard as apc

    sys.exit(apc.main(sys.argv[1:]))


def clipboard_replace_main():
    from pyscripts import clipboard_replace as crx

    sys.exit(crx.main(sys.argv[1:]))


def copy_buffer_main():
    from pyscripts import copy_buffer_to_clipboard as cb2c

    sys.exit(cb2c.main(sys.argv[1:]))


def copy_buffer_full_main():
    from pyscripts import copy_buffer_to_clipboard as cb2c

    sys.exit(cb2c.main(["-f"] + sys.argv[1:]))


def output_to_clipboard_main():
    from pyscripts import output_to_clipboard as otc

    sys.exit(otc.main(sys.argv[1:]))


def output_to_clipboard_wrap_main():
    from pyscripts import output_to_clipboard as otc

    sys.exit(otc.main(["-w"] + sys.argv[1:]))


def output_to_clipboard_append_main():
    from pyscripts import output_to_clipboard as otc

    sys.exit(otc.main(["-a"] + sys.argv[1:]))


def output_to_clipboard_wrap_append_main():
    from pyscripts import output_to_clipboard as otc

    sys.exit(otc.main(["-w", "-a"] + sys.argv[1:]))
