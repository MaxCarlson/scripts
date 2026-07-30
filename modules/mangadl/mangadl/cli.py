from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Sequence

from . import cli_core as _core
from .covers import configure_parser as configure_covers_parser
from .covers import parse_path_maps
from .covers import run_cli as run_covers_cli


def __getattr__(name: str) -> object:
    return getattr(_core, name)


def _subparser(parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return subparsers.choices[name]


def _add_covers_command(parser: argparse.ArgumentParser) -> None:
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    if "covers" in subparsers.choices:
        return
    covers = subparsers.add_parser(
        "covers",
        help="Match URL-folder entries to downloaded series and manage source covers.",
        description=(
            "Scan url*.txt files, match each URL to an existing downloaded folder, "
            "download the source cover, and optionally upload/lock it in Kavita."
        ),
    )
    configure_covers_parser(covers)


def _add_run_cover_arguments(parser: argparse.ArgumentParser, *, advanced: bool) -> None:
    run = _subparser(parser, "run")
    hidden = argparse.SUPPRESS
    run.add_argument(
        "-X",
        "--no-download-covers",
        action="store_false",
        dest="download_covers",
        default=True,
        help="Do not download managed source covers after successful supported-site jobs.",
    )
    run.add_argument(
        "-F",
        "--apply-kavita-covers",
        action="store_true",
        help="Upload and lock managed covers in Kavita after successful jobs." if advanced else hidden,
    )
    run.add_argument(
        "-j",
        "--kavita-url",
        help="Kavita base URL, such as http://192.168.50.100:5000." if advanced else hidden,
    )
    run.add_argument(
        "-S",
        "--kavita-api-key-env",
        default="KAVITA_API_KEY",
        help="Environment variable containing the Kavita Auth Key." if advanced else hidden,
    )
    run.add_argument(
        "-L",
        "--kavita-path-map",
        action="append",
        default=[],
        metavar="LOCAL=KAVITA",
        help="Translate local paths to Kavita-visible paths; repeatable." if advanced else hidden,
    )


def build_parser(argv_hint: Sequence[str] | None = None) -> argparse.ArgumentParser:
    raw = list(argv_hint or ())
    shape = _core.normalize_command_shape(raw)
    parser = _core.build_parser(raw)
    _add_covers_command(parser)
    _add_run_cover_arguments(parser, advanced=bool(shape.advanced_config))
    return parser


def _configure_run_cover_environment(args: argparse.Namespace) -> None:
    os.environ["MANGADL_DOWNLOAD_COVERS"] = "1" if args.download_covers else "0"
    os.environ["MANGADL_APPLY_KAVITA_COVERS"] = "1" if args.apply_kavita_covers else "0"
    os.environ["MANGADL_KAVITA_API_KEY_ENV"] = args.kavita_api_key_env
    os.environ["MANGADL_KAVITA_PATH_MAPS"] = json.dumps(args.kavita_path_map)
    if args.kavita_url:
        os.environ["MANGADL_KAVITA_URL"] = args.kavita_url
    else:
        os.environ.pop("MANGADL_KAVITA_URL", None)


def _run_command(raw_argv: list[str], parser: argparse.ArgumentParser) -> int:
    shape = _core.normalize_command_shape(raw_argv)
    args = parser.parse_args(list(shape.argv))
    args.run_mode = shape.run_mode
    args.advanced_config = shape.advanced_config
    if args.apply_kavita_covers:
        if not args.download_covers:
            raise ValueError("--apply-kavita-covers cannot be combined with --no-download-covers")
        if not args.kavita_url:
            raise ValueError("--apply-kavita-covers requires --kavita-url")
        api_key = os.environ.get(args.kavita_api_key_env, "")
        if not api_key:
            raise ValueError(
                f"--apply-kavita-covers requires a non-empty {args.kavita_api_key_env} environment variable"
            )
    parse_path_maps(args.kavita_path_map)
    _configure_run_cover_environment(args)
    return _core._run(args)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser(raw_argv)
    try:
        if raw_argv and raw_argv[0] == "covers":
            return run_covers_cli(parser.parse_args(raw_argv))
        if raw_argv and raw_argv[0] == "run":
            return _run_command(raw_argv, parser)
        return _core.main(raw_argv)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 2
