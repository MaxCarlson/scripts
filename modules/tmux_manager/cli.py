#!/usr/bin/env python3
"""
tmwin - Tmux Window Manager CLI
Command-line interface for advanced tmux window management.
"""

import sys
import argparse
from .window_manager import TmuxWindowManager


def main():
    win_manager = TmuxWindowManager()

    parser = argparse.ArgumentParser(
        prog='tmwin',
        description="Tmux Window Manager - Advanced window operations for tmux",
        epilog="Examples:\n"
               "  tmwin closew 4..10           # Close windows 4-10\n"
               "  tmwin mvw -i 0               # Move current window to index 0\n"
               "  tmwin mvws -s ai             # Move current window to session 'ai'\n"
               "  tmwin sww                    # Swap with fzf-selected window\n",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', title='commands', required=True)

    # closew: close window(s)
    parser_closew = subparsers.add_parser('closew',
        help="Close window(s) in current or specified session",
        description="Close windows by index, range, or comma-separated list.\n"
                   "Examples: '5', '4..10', '1,7,8,11', '4..-1'")
    parser_closew.add_argument('window_spec',
        help="Window specification (index, range like '4..10', or comma-separated like '1,7,8')")
    parser_closew.add_argument('-t', '--session', dest='session_name', default=None,
                               help="Target session (default: current session)")

    # mvw: move window same session
    parser_mvw = subparsers.add_parser('mvw',
        help="Move window to different index in same session",
        description="Move a window to a different position in the same session. "
                   "Without args, uses fzf for interactive selection.")
    parser_mvw.add_argument('-i', '--index', dest='target_index', type=int, default=None,
                            help="Target index (supports negative like -1 for last)")
    parser_mvw.add_argument('-w', '--window', dest='source_index', type=int, default=None,
                            help="Source window index (default: current window)")
    parser_mvw.add_argument('-t', '--session', dest='session_name', default=None,
                            help="Session name (default: current session)")

    # sww: swap window same session
    parser_sww = subparsers.add_parser('sww',
        help="Swap window with another in same session",
        description="Swap two windows in the same session. "
                   "Without args, uses fzf for interactive selection.")
    parser_sww.add_argument('-i', '--index', dest='target_index', type=int, default=None,
                            help="Target window index to swap with (supports negative)")
    parser_sww.add_argument('-w', '--window', dest='source_index', type=int, default=None,
                            help="Source window index (default: current window)")
    parser_sww.add_argument('-t', '--session', dest='session_name', default=None,
                            help="Session name (default: current session)")

    # mvws: move window to different session
    parser_mvws = subparsers.add_parser('mvws',
        help="Move window to different session",
        description="Move a window from one session to another. "
                   "Without args, uses fzf for interactive selection.")
    parser_mvws.add_argument('-s', '--target-session', dest='target_session', default=None,
                             help="Target session name (default: fzf select)")
    parser_mvws.add_argument('-i', '--index', dest='target_index', type=int, default=None,
                             help="Target index in destination session (default: append to end)")
    parser_mvws.add_argument('-w', '--window', dest='source_index', type=int, default=None,
                             help="Source window index (default: current window)")
    parser_mvws.add_argument('--from', dest='source_session', default=None,
                             help="Source session (default: current session)")

    # swws: swap window between sessions
    parser_swws = subparsers.add_parser('swws',
        help="Swap window with a window in different session",
        description="Swap windows between two different sessions. "
                   "Without args, uses fzf for interactive selection.")
    parser_swws.add_argument('-s', '--target-session', dest='target_session', default=None,
                             help="Target session name (default: fzf select)")
    parser_swws.add_argument('-i', '--index', dest='target_index', type=int, default=None,
                             help="Target window index (default: fzf select from target session)")
    parser_swws.add_argument('-w', '--window', dest='source_index', type=int, default=None,
                             help="Source window index (default: current window)")
    parser_swws.add_argument('--from', dest='source_session', default=None,
                             help="Source session (default: current session)")

    args = parser.parse_args()

    if not win_manager._is_tmux_installed():
        print("Error: tmux is not installed or not in PATH", file=sys.stderr)
        sys.exit(1)

    # Execute commands
    success = True

    if args.command == 'closew':
        success = win_manager.close_windows(args.window_spec, args.session_name)

    elif args.command == 'mvw':
        success = win_manager.move_window_same_session(
            target_index=args.target_index,
            source_index=args.source_index,
            session_name=args.session_name
        )

    elif args.command == 'sww':
        success = win_manager.swap_window_same_session(
            target_index=args.target_index,
            source_index=args.source_index,
            session_name=args.session_name
        )

    elif args.command == 'mvws':
        success = win_manager.move_window_to_session(
            target_session=args.target_session,
            target_index=args.target_index,
            source_index=args.source_index,
            source_session=args.source_session
        )

    elif args.command == 'swws':
        success = win_manager.swap_window_between_sessions(
            target_session=args.target_session,
            target_index=args.target_index,
            source_index=args.source_index,
            source_session=args.source_session
        )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
