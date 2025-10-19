#!/usr/bin/env python3
"""
SyncMux - A centralized, cross-device tmux session manager.

Command-line entry point for the application.
"""

import sys


def main():
    """Main entry point for the syncmux CLI."""
    from .app import SyncMuxApp

    app = SyncMuxApp()
    app.run()


if __name__ == "__main__":
    main()
