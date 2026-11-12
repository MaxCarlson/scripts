"""Explicitly authorized benchmark CLI dispatcher and entry point."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

from . import __version__
from .cli_commands import (
    add_experiment_parser,
    add_external_parser,
    add_models_parser,
    add_root_task_parsers,
    add_setup_parser,
    add_suite_parser,
    add_task_parser,
    handle_experiment,
    handle_external,
    handle_models,
    handle_setup,
    handle_suite,
    handle_task,
)
from .identity import get_effective_lmstudio_model_ids
from .models_lifecycle import (  # re-exported for backwards compatibility and test monkeypatching
    get_loaded_models,
    list_codex_models,
    list_downloaded_models,
    list_gemini_models,
)

__all__ = [
    "get_effective_lmstudio_model_ids",
    "get_loaded_models",
    "list_codex_models",
    "list_downloaded_models",
    "list_gemini_models",
    "main",
    "parser",
]


def parser() -> argparse.ArgumentParser:
    """Build the root agent-bench CLI parser with modular command groups."""
    root = argparse.ArgumentParser(
        prog="agent-bench",
        description="Independently verify first-attempt local coding work and multi-model benchmark experiments",
    )
    root.add_argument("-V", "--version", action="version", version=__version__)
    actions = root.add_subparsers(dest="command")

    # 1. Root task command aliases (plan, run, status, cleanup, smoke) for backward compatibility
    add_root_task_parsers(actions)

    # 2. Canonical task namespace
    add_task_parser(actions)

    # 3. Setup namespace (plan, install, status, verify, upgrade)
    add_setup_parser(actions)

    # 4. Suite namespace (persistent cohort lifecycle)
    add_suite_parser(actions)

    # 5. Model inventory namespace
    add_models_parser(actions)

    # 6. Multi-model experiment namespace
    add_experiment_parser(actions)

    # 7. External Harbor benchmark namespace
    add_external_parser(actions)

    return root


def main(argv: list[str] | None = None) -> int:
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if args.command is None:
        argument_parser.print_help()
        return 0

    if args.command in ("run", "smoke") and not getattr(args, "execute", False):
        print(
            f"agent-bench: {args.command} requires explicit -x/--execute authorization",
            file=sys.stderr,
        )
        return 2

    try:
        if args.command == "setup":
            return handle_setup(args, argument_parser)
        elif args.command == "suite":
            return handle_suite(args)
        elif args.command in ("task", "plan", "run", "status", "cleanup", "smoke"):
            return handle_task(args)
        elif args.command == "models":
            return handle_models(args)
        elif args.command == "experiment":
            return handle_experiment(args, argument_parser)
        elif args.command == "external":
            return handle_external(args, argument_parser)
        else:
            argument_parser.print_help()
            return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        print(
            "agent-bench: interrupted; inspect status before dispatching again",
            file=sys.stderr,
        )
        return 130
    except Exception as error:  # CLI boundary: preserve actionable errors without credential disclosure.
        message = (
            type(error).__name__
            if isinstance(error, httpx.HTTPError)
            else str(error)
        )
        password = os.environ.get("OPENCODE_SERVER_PASSWORD")
        if password:
            message = message.replace(password, "***")
        print(f"agent-bench: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
