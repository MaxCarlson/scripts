#!/usr/bin/env python3
"""
SyncMux - A centralized, cross-device tmux session manager.

Command-line entry point for the application.
"""

import argparse
import logging
import sys
from pathlib import Path

from . import __version__


def main():
    """Main entry point for the syncmux CLI."""
    parser = argparse.ArgumentParser(
        prog="syncmux",
        description="A centralized, cross-device tmux session manager",
        epilog="Use keyboard shortcuts within the TUI: j/k to navigate, Enter to select, n to create session, d to kill session, r to refresh, q to quit"
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"syncmux {__version__}"
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        metavar="PATH",
        help="Path to config file (default: platform-specific, see docs)"
    )
    parser.add_argument(
        "-l", "--log-level",
        choices=["info", "debug", "warning", "error"],
        default="info",
        help="Set logging level (default: info)"
    )

    args = parser.parse_args()

    # Configure logging based on log level
    log_levels = {
        "info": logging.INFO,
        "debug": logging.DEBUG,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    logging.basicConfig(
        level=log_levels[args.log_level],
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    from .app import SyncMuxApp

    app = SyncMuxApp(config_path=args.config)
    app.run()


if __name__ == "__main__":
    main()
