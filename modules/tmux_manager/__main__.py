"""
Entry point for running tmux_manager as a module.
Usage: python -m tmux_manager <command> [options]
"""

from .cli import main

if __name__ == '__main__':
    main()
