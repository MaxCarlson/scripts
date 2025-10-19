#!/usr/bin/env python3
"""
SyncMux - A centralized, cross-device tmux session manager.

Command-line entry point for the application.
"""

import argparse
import sys


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
        version="syncmux 0.1.0"
    )

    args = parser.parse_args()

    from .app import SyncMuxApp

    app = SyncMuxApp()
    app.run()


if __name__ == "__main__":
    main()
