"""
Combined argument parsers for ``ytaedl run <profile>`` sub-subcommands.

Each combined parser covers all core run flags PLUS the profile-specific flags,
arranged in labelled, colour-coded sections so ``--help`` is easy to scan.

Usage (via cli.py):
    ytaedl run watcher  -t 8 -P B:\\stars\\ -F 75   → make_run_watcher_parser()
    ytaedl run grid     -t 8 -X                      → make_run_grid_parser()
    ytaedl run webview  -t 8 -W                      → make_run_webview_parser()
    ytaedl run disable  -t 8 -n                      → make_run_disable_parser()
"""

from __future__ import annotations

import argparse
import textwrap
from typing import Optional

from . import __version__ as YTAEDL_VERSION
from .manager import (
    _add_disable_args,
    _add_grid_args,
    _add_run_core_args,
    _add_watcher_args,
    _add_webview_args,
)

# ---------------------------------------------------------------------------
# Coloured section formatter
# ---------------------------------------------------------------------------

_RESET = "\033[0m"

_PROFILE_COLORS = {
    "run":     "\033[1;34m",  # bold blue
    "watcher": "\033[1;32m",  # bold green
    "grid":    "\033[1;33m",  # bold yellow
    "webview": "\033[1;35m",  # bold magenta
    "disable": "\033[1;31m",  # bold red
}


class ColoredSectionHelpFormatter(argparse.HelpFormatter):
    """
    Argparse formatter that colours argument group headings.

    Any group whose title contains a profile keyword (run, watcher, grid,
    webview, disable) gets the corresponding ANSI colour.  Other headings use
    bold white.  Resets cleanly on terminals that do not support ANSI.
    """

    _BOLD_WHITE = "\033[1m"

    def start_section(self, heading: Optional[str]) -> None:
        if heading:
            color = self._BOLD_WHITE
            for key, code in _PROFILE_COLORS.items():
                if key in heading.lower():
                    color = code
                    break
            heading = f"{color}{heading}{_RESET}"
        super().start_section(heading)


# ---------------------------------------------------------------------------
# Combined parser factory helpers
# ---------------------------------------------------------------------------

def _base_combined_parser(
    profile: str,
    prog: str,
    description: str,
    epilog: str = "",
) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=prog,
        description=f"ytaedl {YTAEDL_VERSION}\n\n{description}",
        epilog=epilog or None,
        formatter_class=ColoredSectionHelpFormatter,
    )
    # Core run flags — shown with help in their own section
    run_group = p.add_argument_group("run — core manager flags")
    _add_run_core_args(run_group)
    return p


# ---------------------------------------------------------------------------
# ytaedl run watcher
# ---------------------------------------------------------------------------

def make_run_watcher_parser() -> argparse.ArgumentParser:
    """Parser for ``ytaedl run watcher [options]``."""
    p = _base_combined_parser(
        profile="watcher",
        prog="ytaedl run watcher",
        description=textwrap.dedent("""\
            Start the interactive download manager with the MP4 watcher enabled.
            --enable-mp4-watcher is automatically active; all core run flags apply.
        """),
        epilog=textwrap.dedent("""\
            Examples:
              ytaedl run watcher -t 8 -P B:\\stars\\ -F 75
              ytaedl run watcher -t 8 -P B:\\stars\\ -T --space-remaining 200GB
        """),
    )
    watcher_group = p.add_argument_group(
        "watcher — MP4 watcher options  (--enable-mp4-watcher is active automatically)"
    )
    _add_watcher_args(watcher_group, suppress=False)
    # Keep other profile flags defined (suppressed) so the namespace is complete
    _add_grid_args(p, suppress=True)
    _add_webview_args(p, suppress=True)
    _add_disable_args(p, suppress=True)
    return p


# ---------------------------------------------------------------------------
# ytaedl run grid
# ---------------------------------------------------------------------------

def make_run_grid_parser() -> argparse.ArgumentParser:
    """Parser for ``ytaedl run grid [options]``."""
    p = _base_combined_parser(
        profile="grid",
        prog="ytaedl run grid",
        description=textwrap.dedent("""\
            Start the interactive download manager with yt-dlp grid search enabled.
            --yt-dlp-grid-search is automatically active; all core run flags apply.
        """),
        epilog=textwrap.dedent("""\
            Examples:
              ytaedl run grid -t 4 -P B:\\stars\\
              ytaedl run grid -t 4 -B ./logs/grid.db -V my-experiment
        """),
    )
    grid_group = p.add_argument_group(
        "grid — yt-dlp grid-search options  (--yt-dlp-grid-search is active automatically)"
    )
    _add_grid_args(grid_group, suppress=False)
    _add_watcher_args(p, suppress=True)
    _add_webview_args(p, suppress=True)
    _add_disable_args(p, suppress=True)
    return p


# ---------------------------------------------------------------------------
# ytaedl run webview
# ---------------------------------------------------------------------------

def make_run_webview_parser() -> argparse.ArgumentParser:
    """Parser for ``ytaedl run webview [options]``."""
    p = _base_combined_parser(
        profile="webview",
        prog="ytaedl run webview",
        description=textwrap.dedent("""\
            Start the interactive download manager with the TUI web mirror enabled.
            --web-view is automatically active; all core run flags apply.
        """),
        epilog=textwrap.dedent("""\
            Examples:
              ytaedl run webview -t 8 -P B:\\stars\\
              ytaedl run webview -t 8 -Y my-dashboard
        """),
    )
    webview_group = p.add_argument_group(
        "webview — TUI mirror options  (--web-view is active automatically)"
    )
    _add_webview_args(webview_group, suppress=False)
    _add_watcher_args(p, suppress=True)
    _add_grid_args(p, suppress=True)
    _add_disable_args(p, suppress=True)
    return p


# ---------------------------------------------------------------------------
# ytaedl run disable
# ---------------------------------------------------------------------------

def make_run_disable_parser() -> argparse.ArgumentParser:
    """Parser for ``ytaedl run disable [options]``."""
    p = _base_combined_parser(
        profile="disable",
        prog="ytaedl run disable",
        description=textwrap.dedent("""\
            Start the interactive download manager with specific features disabled.
            All listed disable flags are off by default; only set the ones you need.
        """),
        epilog=textwrap.dedent("""\
            Examples:
              ytaedl run disable -t 8 -P B:\\stars\\ -n           # no extdl fallback
              ytaedl run disable -t 8 -P B:\\stars\\ -K           # skip simulate check
              ytaedl run disable -t 8 -P B:\\stars\\ -n -K -j 2  # multiple
        """),
    )
    disable_group = p.add_argument_group(
        "disable — feature-disable and fallback-tuning flags"
    )
    _add_disable_args(disable_group, suppress=False)
    _add_watcher_args(p, suppress=True)
    _add_grid_args(p, suppress=True)
    _add_webview_args(p, suppress=True)
    return p


# ---------------------------------------------------------------------------
# Profile → parser mapping
# ---------------------------------------------------------------------------

_PROFILE_PARSERS = {
    "watcher": make_run_watcher_parser,
    "grid":    make_run_grid_parser,
    "webview": make_run_webview_parser,
    "disable": make_run_disable_parser,
}

#: Flags auto-enabled by each profile (injected into the namespace before
#: passing to run_main).
_PROFILE_AUTO_ENABLE: dict[str, dict[str, object]] = {
    "watcher": {"enable_mp4_watcher": True},
    "grid":    {"yt_dlp_grid_search": True},
    "webview": {"web_view": True},
    "disable": {},
}


def make_profile_parser(profile: str) -> argparse.ArgumentParser:
    """Return the combined parser for *profile* (watcher / grid / webview / disable)."""
    factory = _PROFILE_PARSERS.get(profile)
    if factory is None:
        raise ValueError(f"Unknown run profile: {profile!r}")
    return factory()


def profile_auto_flags(profile: str) -> dict[str, object]:
    """Return a dict of flag attributes to inject into the namespace for *profile*."""
    return dict(_PROFILE_AUTO_ENABLE.get(profile, {}))
