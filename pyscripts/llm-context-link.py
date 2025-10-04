#!/usr/bin/env python3
"""
LLM Context File Linker

Links LLM context files (AGENTS.md, GEMINI.md) from dotfiles to a target directory.
Supports symlinks, hardlinks, and copy fallback across all platforms (Windows 11, Termux, WSL2, Ubuntu).

Usage:
    llm-context-link.py [TARGET_DIR] [OPTIONS]

Examples:
    llm-context-link.py                    # Link to $SCRIPTS or ~/scripts
    llm-context-link.py ~/my-project       # Link to specific directory
    llm-context-link.py -o ~/my-project    # Overwrite existing links
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Import cross_platform utilities
try:
    from cross_platform import create_link, LinkType, LinkResult, SystemUtils
except ImportError:
    print("Error: cross_platform module not found. Please install it first:", file=sys.stderr)
    print("  cd ~/scripts && python setup.py", file=sys.stderr)
    sys.exit(1)


def get_dotfiles_dir() -> Path:
    """Get the dotfiles directory path."""
    dotfiles = os.environ.get("DOTFILES")
    if dotfiles:
        return Path(dotfiles)
    return Path.home() / "dotfiles"


def get_default_target_dir() -> Path:
    """Get the default target directory for links."""
    scripts = os.environ.get("SCRIPTS")
    if scripts:
        return Path(scripts)
    return Path.home() / "scripts"


def link_context_files(
    target_dir: Path,
    *,
    overwrite: bool = False,
    verbose: bool = False,
) -> bool:
    """
    Link LLM context files to target directory.

    Args:
        target_dir: Target directory for links
        overwrite: Whether to overwrite existing files
        verbose: Enable verbose output

    Returns:
        True if all links created successfully, False otherwise
    """
    # Get source files
    dotfiles = get_dotfiles_dir()
    source_dir = dotfiles / "symlinked" / "llms" / "scripts"
    agents_src = source_dir / "AGENTS.md"
    gemini_src = source_dir / "GEMINI.md"

    # Validate source files
    if not agents_src.exists():
        print(f"Error: Source file not found: {agents_src}", file=sys.stderr)
        return False
    if not gemini_src.exists():
        print(f"Error: Source file not found: {gemini_src}", file=sys.stderr)
        return False

    # Ensure target directory exists
    if not target_dir.exists():
        if verbose:
            print(f"Creating target directory: {target_dir}")
        target_dir.mkdir(parents=True, exist_ok=True)

    # Link files
    print(f"Linking LLM context files to: {target_dir}")
    success_count = 0
    total_files = 2

    for source_file in [agents_src, gemini_src]:
        target_file = target_dir / source_file.name

        # Create link with fallback
        result = create_link(
            source_file,
            target_file,
            link_type=LinkType.SYMLINK,
            fallback_copy=True,
            overwrite=overwrite,
        )

        if result.success:
            link_type_str = result.link_type.value if result.link_type else "unknown"
            print(f"✓ {link_type_str.capitalize()}: {source_file.name}")
            success_count += 1
            if verbose:
                print(f"  Source: {source_file}")
                print(f"  Target: {target_file}")
        else:
            print(f"✗ Failed: {source_file.name}", file=sys.stderr)
            if result.error:
                print(f"  Error: {result.error}", file=sys.stderr)

    # Summary
    print()
    if success_count == total_files:
        print("All context files linked successfully!")
        return True
    else:
        print(f"Some files failed to link ({success_count}/{total_files} succeeded)", file=sys.stderr)
        return False


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Link LLM context files (AGENTS.md, GEMINI.md) to a target directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Link to $SCRIPTS or ~/scripts
  %(prog)s ~/my-project       # Link to specific directory
  %(prog)s -o ~/my-project    # Overwrite existing links

Source files (from dotfiles):
  - AGENTS.md   (for OpenAI Codex and other AI agents)
  - GEMINI.md   (for Gemini CLI)
        """,
    )

    parser.add_argument(
        "target_dir",
        nargs="?",
        type=Path,
        default=None,
        help="Target directory for links (default: $SCRIPTS or ~/scripts)",
    )
    parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        help="Overwrite existing files/links",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    # Determine target directory
    target_dir = args.target_dir if args.target_dir else get_default_target_dir()

    # Link files
    success = link_context_files(
        target_dir,
        overwrite=args.overwrite,
        verbose=args.verbose,
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
