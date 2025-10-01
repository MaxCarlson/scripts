"""
Make argparse_enforcer runnable as a module to display setup instructions.

Usage:
    python -m argparse_enforcer
    python -m argparse_enforcer.setup_instructions
"""
from .setup_instructions import print_setup_instructions

if __name__ == "__main__":
    print_setup_instructions()
