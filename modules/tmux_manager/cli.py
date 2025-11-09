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
        prog='tmx',
        description="Tmux Manager - Advanced tmux session and window operations",
        epilog="Examples:\n"
               "  tmx closew 4..10             # Close windows 4-10\n"
               "  tmx mvw -i 0                 # Move current window to index 0\n"
               "  tmx mvws -s ai               # Move current window to session 'ai'\n"
               "  tmx sww                      # Swap with fzf-selected window\n"
               "  tmx spawn -c 3 -p 2          # Create 3 windows with 2 panes each\n"
               "  tmx jump ai                  # Jump to session 'ai'\n",
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

    # spawn: create new windows
    parser_spawn = subparsers.add_parser('spawn',
        help="Spawn new window(s) with optional panes",
        description="Create one or more windows, optionally with multiple panes.")
    parser_spawn.add_argument('-c', '--count', dest='count', type=int, default=1,
                              help="Number of windows to create (default: 1)")
    parser_spawn.add_argument('-p', '--panes', dest='panes_per_window', type=int, default=1,
                              help="Number of panes per window (default: 1)")
    parser_spawn.add_argument('-i', '--index', dest='target_index', type=int, default=None,
                              help="Index where to insert windows (default: after current window)")
    parser_spawn.add_argument('-t', '--session', dest='session_name', default=None,
                              help="Target session (default: current session)")
    parser_spawn.add_argument('-n', '--name', dest='window_name', default=None,
                              help="Name for the window(s)")

    # jump: jump to session
    parser_jump = subparsers.add_parser('jump',
        help="Jump to (switch to or attach) a session",
        description="Jump to a session. Uses fzf for selection if no session specified.")
    parser_jump.add_argument('session_name', nargs='?', default=None,
                             help="Session to jump to (default: fzf select)")

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

    elif args.command == 'spawn':
        success = win_manager.spawn_windows(
            count=args.count,
            panes_per_window=args.panes_per_window,
            target_index=args.target_index,
            session_name=args.session_name,
            window_name=args.window_name
        )

    elif args.command == 'jump':
        success = win_manager.jump_to_session(session_name=args.session_name)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
