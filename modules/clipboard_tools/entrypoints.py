#!/usr/bin/env python3
"""
Entry points that reuse the existing pyscripts implementations.
This keeps aliases consistent across installs.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root (pyscripts, cross_platform, etc.) is importable when installed in editable mode.
REPO_ROOT = Path(__file__).resolve().parents[2]
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
    )


def copy_main():
    sys.exit(_run_copy(None))


def copy_default_main():
    sys.exit(_run_copy([]))


def copy_recursive_main():
    sys.exit(_run_copy(["-r"]))


def copy_append_main():
    sys.exit(_run_copy(["-a"]))


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


def replace_with_clipboard_main():
    from pyscripts import replace_with_clipboard as rwc

    args = rwc.parser.parse_args()
    sys.exit(rwc.replace_or_print_clipboard(args.file, args.no_stats, args.from_last_cld, args.buffer_id))


def replace_with_clipboard_from_last_main():
    from pyscripts import replace_with_clipboard as rwc

    args = rwc.parser.parse_args(["-F"])
    sys.exit(rwc.replace_or_print_clipboard(args.file, args.no_stats, args.from_last_cld, args.buffer_id))


def clipboard_diff_main():
    from pyscripts import clipboard_diff as cld

    cld.main()


def append_clipboard_main():
    from pyscripts import append_clipboard as apc

    apc.main()


def clipboard_replace_main():
    from pyscripts import clipboard_replace as crx

    crx.main()


def copy_buffer_main():
    from pyscripts import copy_buffer_to_clipboard as cb2c

    cb2c.main([])


def copy_buffer_full_main():
    from pyscripts import copy_buffer_to_clipboard as cb2c

    cb2c.main(["-f"])


def output_to_clipboard_main():
    from pyscripts import output_to_clipboard as otc

    sys.exit(otc.main([]))


def output_to_clipboard_wrap_main():
    from pyscripts import output_to_clipboard as otc

    sys.exit(otc.main(["-w"]))


def output_to_clipboard_append_main():
    from pyscripts import output_to_clipboard as otc

    sys.exit(otc.main(["-a"]))


def output_to_clipboard_wrap_append_main():
    from pyscripts import output_to_clipboard as otc

    sys.exit(otc.main(["-w", "-a"]))
