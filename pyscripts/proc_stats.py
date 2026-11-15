#!/usr/bin/env python3
"""
Legacy-compatible entry point for proc_stats.py.

Delegates to system_manager.process_watch.cli.main_legacy while preserving
the original CLI flags (-n, -g, -s, -a ms, -u ms) and bare-glob substring match.
"""
__version__ = "0.2.0"

import sys
from pathlib import Path


def main(argv=None) -> int:
    try:
        from system_manager.process_watch.cli import main_legacy
    except ImportError:
        repo_root = Path(__file__).resolve().parents[1]
        modules_dir = repo_root / "modules"
        if str(modules_dir) not in sys.path:
            sys.path.insert(0, str(modules_dir))
        from system_manager.process_watch.cli import main_legacy
    return main_legacy(argv)


if __name__ == "__main__":
    raise SystemExit(main())
