"""CLI parser and program entry point for filter-prune."""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from . import __version__
from .models import ParsedCli, SafePruneError
from .operations import apply_targets, print_stats
from .search import apply_limit, collect_combined_targets, collect_fd_targets, collect_rg_targets
from .util import deduplicate_targets, resolve_roots, resolve_tool_config


PROGRAM_NAME = "filter-prune"
COMMAND_NAMES = {"fd", "rg"}
HELP_FLAGS = {"-h", "-?", "--help"}
VERSION_FLAGS = {"-V", "--version"}

OPERATION_KEYS = {
    "roots",
    "execute",
    "yes",
    "operation",
    "target_dir",
    "recursive",
    "allow_all",
    "limit",
    "json",
    "quiet",
    "verbose",
    "color",
    "script_command",
    "script_arg",
    "shell",
    "working_dir",
    "stop_on_error",
    "max_bytes",
    "encoding",
    "decode_errors",
    "allow_binary",
    "no_headers",
}

FD_KEYS = {
    "entry_type",
    "glob_pattern",
    "extension",
    "exclude",
    "max_depth",
    "min_depth",
    "include_hidden",
    "no_ignore",
    "ignore_case",
    "follow_links",
}

RG_KEYS = {
    "content_pattern",
    "match_mode",
    "fixed_strings",
    "glob_pattern",
    "extension",
    "exclude",
    "max_depth",
    "min_depth",
    "include_hidden",
    "no_ignore",
    "ignore_case",
    "follow_links",
}


def default_operation_args() -> argparse.Namespace:
    """Return default operation-level arguments."""
    return argparse.Namespace(
        roots=[],
        execute=False,
        yes=False,
        operation="delete",
        target_dir=None,
        recursive=False,
        allow_all=False,
        limit=None,
        json=False,
        quiet=False,
        verbose=False,
        color="auto",
        script_command=None,
        script_arg=[],
        shell=False,
        working_dir=None,
        stop_on_error=False,
        max_bytes=None,
        encoding="utf-8",
        decode_errors="replace",
        allow_binary=False,
        no_headers=False,
    )


def default_fd_args() -> argparse.Namespace:
    """Return default fd-specific arguments."""
    return argparse.Namespace(
        entry_type="file",
        glob_pattern=[],
        extension=[],
        exclude=[],
        max_depth=None,
        min_depth=None,
        include_hidden=False,
        no_ignore=True,
        ignore_case=False,
        follow_links=False,
    )


def default_rg_args() -> argparse.Namespace:
    """Return default rg-specific arguments."""
    return argparse.Namespace(
        content_pattern=[],
        match_mode="all",
        fixed_strings=False,
        glob_pattern=[],
        extension=[],
        exclude=[],
        max_depth=None,
        min_depth=None,
        include_hidden=False,
        no_ignore=True,
        ignore_case=False,
        follow_links=False,
    )


def merge_namespace_values(target: argparse.Namespace, source: argparse.Namespace, allowed_keys: set[str]) -> None:
    """Merge selected argparse values into a target namespace."""
    for key, value in vars(source).items():
        if key not in allowed_keys:
            continue

        if key == "roots":
            existing = getattr(target, "roots", [])
            setattr(target, "roots", [*existing, *value])
            continue

        if key in ("script_arg",):
            existing = getattr(target, key, [])
            setattr(target, key, [*existing, *value])
            continue

        setattr(target, key, value)


def add_help_argument(parser: argparse.ArgumentParser) -> None:
    """Add standard help options, including -?."""
    parser.add_argument(
        "-h",
        "-?",
        "--help",
        action="help",
        help="Show this help menu and exit.",
    )


def add_operation_arguments(parser: argparse.ArgumentParser, suppress_defaults: bool = True) -> None:
    """Add common operation and safety arguments."""
    default = argparse.SUPPRESS if suppress_defaults else None

    parser.add_argument(
        "-r",
        "--root",
        dest="roots",
        action="append",
        default=default,
        help="Root directory to search. Can be repeated. Defaults to the current directory.",
    )
    parser.add_argument(
        "-X",
        "--execute",
        action="store_true",
        default=default,
        help="Actually apply the selected operation. Without this flag, the command is always a dry-run.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        default=default,
        help="Skip the interactive confirmation when --execute is used.",
    )
    parser.add_argument(
        "-O",
        "--operation",
        choices=("delete", "move", "quarantine", "script", "cat"),
        default=default,
        help="Operation to apply to matches. Defaults to delete. Dry-run is still default unless --execute is used.",
    )
    parser.add_argument(
        "-T",
        "--target-dir",
        default=default,
        help="Destination directory for move/quarantine operations. Required for move. Optional for quarantine.",
    )
    parser.add_argument(
        "-R",
        "--recursive",
        action="store_true",
        default=default,
        help="Allow deletion of non-empty directories. Not needed for files, move, quarantine, script, or cat.",
    )
    parser.add_argument(
        "-A",
        "--allow-all",
        action="store_true",
        default=default,
        help="Allow execution when no positive fd filter is provided.",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=default,
        help="Maximum number of final matched targets to affect or show.",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        default=default,
        help="Print JSON output instead of text output.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=default,
        help="Suppress normal text output. Errors still go to stderr.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=default,
        help="Print additional skip/failure details and combined fd/rg filter traces.",
    )
    parser.add_argument(
        "-c",
        "--color",
        choices=("auto", "always", "never"),
        default=default,
        help="Color output mode. Use auto, always, or never. Defaults to auto.",
    )
    parser.add_argument(
        "-S",
        "--script-command",
        default=default,
        help="Script operation command. Supports {path}, {root}, {relative}, {kind}, and {index}.",
    )
    parser.add_argument(
        "-B",
        "--script-arg",
        action="append",
        default=default,
        help="Script operation argument. Can be repeated. Supports {path}, {root}, {relative}, {kind}, and {index}.",
    )
    parser.add_argument(
        "-s",
        "--shell",
        action="store_true",
        default=default,
        help="Run script operation through the platform shell.",
    )
    parser.add_argument(
        "-w",
        "--working-dir",
        default=default,
        help="Script operation working directory. Supports {path}, {root}, {relative}, {kind}, and {index}. Defaults to root.",
    )
    parser.add_argument(
        "-E",
        "--stop-on-error",
        action="store_true",
        default=default,
        help="Stop operation execution after the first per-target failure.",
    )
    parser.add_argument(
        "-z",
        "--max-bytes",
        type=int,
        default=default,
        help="Cat operation maximum bytes to print per file.",
    )
    parser.add_argument(
        "-u",
        "--encoding",
        default=default,
        help="Cat operation text encoding. Defaults to utf-8.",
    )
    parser.add_argument(
        "-d",
        "--decode-errors",
        choices=("strict", "replace", "ignore"),
        default=default,
        help="Cat operation decoding error policy. Defaults to replace.",
    )
    parser.add_argument(
        "-Y",
        "--allow-binary",
        action="store_true",
        default=default,
        help="Cat operation allows binary-looking files instead of skipping them.",
    )
    parser.add_argument(
        "-N",
        "--no-headers",
        action="store_true",
        default=default,
        help="Cat operation suppresses file/folder header lines.",
    )


def add_fd_arguments(parser: argparse.ArgumentParser, suppress_defaults: bool = True) -> None:
    """Add fd/path-style filtering arguments."""
    default = argparse.SUPPRESS if suppress_defaults else None

    parser.add_argument(
        "-t",
        "--entry-type",
        choices=("file", "folder", "any"),
        default=default,
        help="Filesystem entry type to match. Defaults to file.",
    )
    parser.add_argument(
        "-g",
        "--glob-pattern",
        action="append",
        default=default,
        help="FD glob pattern to match path names. Glob matching is the default. Can be repeated.",
    )
    parser.add_argument(
        "-e",
        "--extension",
        action="append",
        default=default,
        help="FD extension filter, with or without a leading dot. Can be repeated.",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        default=default,
        help="FD glob pattern to exclude. Can be repeated.",
    )
    parser.add_argument(
        "-m",
        "--max-depth",
        type=int,
        default=default,
        help="FD maximum search depth where a top-level child has depth 1.",
    )
    parser.add_argument(
        "-M",
        "--min-depth",
        type=int,
        default=default,
        help="FD minimum search depth where a top-level child has depth 1.",
    )
    parser.add_argument(
        "-a",
        "--include-hidden",
        action="store_true",
        default=default,
        help="FD include hidden files and directories.",
    )
    parser.add_argument(
        "-I",
        "--no-ignore",
        action="store_true",
        dest="no_ignore",
        default=default,
        help="FD ignore .gitignore/.ignore rules. This is enabled by default.",
    )
    parser.add_argument(
        "-G",
        "--respect-ignore",
        action="store_false",
        dest="no_ignore",
        default=default,
        help="FD respect .gitignore/.ignore rules. This disables the default --no-ignore behavior.",
    )
    parser.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        default=default,
        help="FD use case-insensitive path matching.",
    )
    parser.add_argument(
        "-L",
        "--follow-links",
        action="store_true",
        default=default,
        help="FD follow symbolic links while searching.",
    )


def add_rg_arguments(parser: argparse.ArgumentParser, suppress_defaults: bool = True) -> None:
    """Add rg/content-style filtering arguments."""
    default = argparse.SUPPRESS if suppress_defaults else None

    parser.add_argument(
        "-p",
        "--content-pattern",
        action="append",
        default=default,
        help="RG content pattern to match. Can be repeated.",
    )
    parser.add_argument(
        "-P",
        "--match-mode",
        choices=("all", "any"),
        default=default,
        help="When multiple RG content patterns are provided, require all or any. Defaults to all.",
    )
    parser.add_argument(
        "-F",
        "--fixed-strings",
        action="store_true",
        default=default,
        help="RG treat content patterns as literal strings instead of regexes.",
    )
    parser.add_argument(
        "-g",
        "--glob-pattern",
        action="append",
        default=default,
        help="RG file glob filter. Can be repeated.",
    )
    parser.add_argument(
        "-e",
        "--extension",
        action="append",
        default=default,
        help="RG file extension filter, with or without a leading dot. Can be repeated.",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        default=default,
        help="RG glob pattern to exclude. Can be repeated.",
    )
    parser.add_argument(
        "-m",
        "--max-depth",
        type=int,
        default=default,
        help="RG maximum search depth where a top-level child has depth 1.",
    )
    parser.add_argument(
        "-M",
        "--min-depth",
        type=int,
        default=default,
        help="RG minimum search depth where a top-level child has depth 1.",
    )
    parser.add_argument(
        "-a",
        "--include-hidden",
        action="store_true",
        default=default,
        help="RG include hidden files and directories.",
    )
    parser.add_argument(
        "-I",
        "--no-ignore",
        action="store_true",
        dest="no_ignore",
        default=default,
        help="RG ignore .gitignore/.ignore rules. This is enabled by default.",
    )
    parser.add_argument(
        "-G",
        "--respect-ignore",
        action="store_false",
        dest="no_ignore",
        default=default,
        help="RG respect .gitignore/.ignore rules. This disables the default --no-ignore behavior.",
    )
    parser.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        default=default,
        help="RG use case-insensitive content/path matching.",
    )
    parser.add_argument(
        "-L",
        "--follow-links",
        action="store_true",
        default=default,
        help="RG follow symbolic links while searching.",
    )


def build_operation_parser(prog: str) -> argparse.ArgumentParser:
    """Build a parser for operation-level arguments."""
    parser = argparse.ArgumentParser(prog=prog, add_help=False)
    add_operation_arguments(parser, suppress_defaults=True)
    return parser


def build_main_parser() -> argparse.ArgumentParser:
    """Build the top-level help parser."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Safely apply operations to files/folders using fd path filters, rg content filters, or both.",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Subcommands:\n"
            "  fd                 Match files/folders by path/name using fd.\n"
            "  rg                 Match files by content using rg.\n"
            "  fd ... rg ...      Run fd first, then narrow with rg content matches.\n"
            "  rg ... fd ...      Run rg first, then narrow with fd path/folder matches.\n\n"
            "Operation model:\n"
            "  Dry-run is always the default.\n"
            "  The default operation is delete.\n"
            "  Use --execute / -X to apply the selected operation.\n"
            "  Use --operation / -O delete|move|quarantine|script|cat.\n"
            "  Use repeated --root / -r values to search multiple directories.\n\n"
            "Script operation placeholders:\n"
            "  {path}, {root}, {relative}, {kind}, {index}\n\n"
            "Examples:\n"
            "  filter-prune fd -g \"*preview*\"\n"
            "  filter-prune -O cat -X fd -g \"*.txt\"\n"
            "  filter-prune -O script -S python -B C:\\tools\\touch.py -B \"{path}\" -X fd -g \"*.txt\"\n"
            "  filter-prune -O move -T B:\\MovedMatches -X fd -g \"*preview*\"\n"
        ),
    )
    add_help_argument(parser)
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"{PROGRAM_NAME} {__version__}",
        help="Print version information and exit.",
    )
    add_operation_arguments(parser, suppress_defaults=False)
    return parser


def build_fd_parser(prog: str = f"{PROGRAM_NAME} fd") -> argparse.ArgumentParser:
    """Build the fd subcommand parser."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Find files/folders by path/name using fd, then dry-run or execute an operation.",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "FD uses glob matching by default for --glob-pattern / -g.\n"
            "--no-ignore / -I is enabled by default; use --respect-ignore / -G to respect ignore files.\n\n"
            "Combined mode:\n"
            "  filter-prune fd [fd-options] rg [rg-options]\n"
            "Order matters: fd arguments appear before rg, then rg arguments narrow by content.\n"
        ),
    )
    add_help_argument(parser)
    add_operation_arguments(parser, suppress_defaults=True)
    add_fd_arguments(parser, suppress_defaults=True)
    return parser


def build_rg_parser(prog: str = f"{PROGRAM_NAME} rg") -> argparse.ArgumentParser:
    """Build the rg subcommand parser."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Find files by content using rg, then dry-run or execute an operation.",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "RG always returns files. Use --content-pattern / -p for content filters.\n"
            "--no-ignore / -I is enabled by default; use --respect-ignore / -G to respect ignore files.\n\n"
            "Combined mode:\n"
            "  filter-prune rg [rg-options] fd [fd-options]\n"
            "Order matters: rg arguments appear before fd, then fd arguments narrow by path/folder.\n"
        ),
    )
    add_help_argument(parser)
    add_operation_arguments(parser, suppress_defaults=True)
    add_rg_arguments(parser, suppress_defaults=True)
    return parser


def print_combo_help(order: tuple[str, str]) -> None:
    """Print a unique help menu for an exact two-subcommand combination."""
    first, second = order
    first_description = "FD path/folder candidate set" if first == "fd" else "RG content candidate set"
    second_description = "FD path/folder filter" if second == "fd" else "RG content filter"

    print(f"usage: {PROGRAM_NAME} [global-options] {first} [{first}-options] {second} [{second}-options]\n")
    print(f"Combined mode: {first} {second}")
    print()
    print("Order matters:")
    print(f"  1. {first} options apply only to the {first_description}.")
    print(f"  2. {second} options apply only to the {second_description}.")
    print("  3. Verbose mode shows which targets each filter removed.")
    print()
    print("Operations:")
    print("  -O, --operation {delete,move,quarantine,script,cat}")
    print("  -X, --execute")
    print("  -y, --yes")
    print("  -T, --target-dir DIR")
    print("  -S, --script-command COMMAND")
    print("  -B, --script-arg ARG")
    print("  -z, --max-bytes BYTES")
    print()
    print("Combined modes affect files because rg returns files.")
    print("FD folder matches restrict the candidate set to files under those folders.")
    print()
    print(f"{first.upper()} options are shown with:")
    print(f"  {PROGRAM_NAME} {first} --help")
    print()
    print(f"{second.upper()} options are shown with:")
    print(f"  {PROGRAM_NAME} {second} --help")


def split_subcommand_segments(argv: Sequence[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Split argv into global tokens and command-specific token segments."""
    command_positions = [(index, token) for index, token in enumerate(argv) if token in COMMAND_NAMES]

    if not command_positions:
        return list(argv), []

    if len(command_positions) > 2:
        raise SafePruneError("At most two subcommands are supported: fd, rg, fd rg, or rg fd.")

    command_sequence = [command for _, command in command_positions]
    if len(set(command_sequence)) != len(command_sequence):
        raise SafePruneError("Duplicate subcommands are not supported. Use fd, rg, fd rg, or rg fd.")

    global_tokens = list(argv[: command_positions[0][0]])
    segments: list[tuple[str, list[str]]] = []

    for position_index, (command_start, command_name) in enumerate(command_positions):
        next_start = command_positions[position_index + 1][0] if position_index + 1 < len(command_positions) else len(argv)
        segments.append((command_name, list(argv[command_start + 1 : next_start])))

    return global_tokens, segments


def parse_cli(argv: Optional[Sequence[str]] = None) -> ParsedCli:
    """Parse a composable fd/rg CLI."""
    raw_args = list(sys.argv[1:] if argv is None else argv)

    if not raw_args:
        build_main_parser().print_help()
        raise SystemExit(0)

    if any(token in VERSION_FLAGS for token in raw_args):
        print(f"{PROGRAM_NAME} {__version__}")
        raise SystemExit(0)

    command_tokens = [token for token in raw_args if token in COMMAND_NAMES]
    help_requested = any(token in HELP_FLAGS for token in raw_args)

    if help_requested:
        if len(command_tokens) >= 2:
            print_combo_help((command_tokens[0], command_tokens[1]))
        elif len(command_tokens) == 1:
            if command_tokens[0] == "fd":
                build_fd_parser().print_help()
            else:
                build_rg_parser().print_help()
        else:
            build_main_parser().print_help()
        raise SystemExit(0)

    global_tokens, segments = split_subcommand_segments(raw_args)

    if not segments:
        raise SafePruneError("A subcommand is required. Use fd, rg, fd rg, or rg fd.")

    operation = default_operation_args()
    fd_args = default_fd_args() if any(command == "fd" for command, _ in segments) else None
    rg_args = default_rg_args() if any(command == "rg" for command, _ in segments) else None

    global_parser = build_operation_parser(PROGRAM_NAME)
    global_namespace = global_parser.parse_args(global_tokens)
    merge_namespace_values(operation, global_namespace, OPERATION_KEYS)

    order: list[str] = []

    for command, segment_tokens in segments:
        order.append(command)

        if command == "fd":
            parser = build_fd_parser(f"{PROGRAM_NAME} {' '.join(order)}")
            namespace = parser.parse_args(segment_tokens)
            merge_namespace_values(operation, namespace, OPERATION_KEYS)
            if fd_args is None:
                fd_args = default_fd_args()
            merge_namespace_values(fd_args, namespace, FD_KEYS)
        elif command == "rg":
            parser = build_rg_parser(f"{PROGRAM_NAME} {' '.join(order)}")
            namespace = parser.parse_args(segment_tokens)
            merge_namespace_values(operation, namespace, OPERATION_KEYS)
            if rg_args is None:
                rg_args = default_rg_args()
            merge_namespace_values(rg_args, namespace, RG_KEYS)
        else:
            raise SafePruneError(f"Unsupported subcommand: {command}")

    return ParsedCli(
        operation=operation,
        order=tuple(order),
        fd=fd_args,
        rg=rg_args,
    )


def validate_depth_pair(min_depth: Optional[int], max_depth: Optional[int], label: str) -> None:
    """Validate min/max depth combinations."""
    if min_depth is not None and min_depth < 0:
        raise SafePruneError(f"{label} --min-depth cannot be negative.")

    if max_depth is not None and max_depth < 0:
        raise SafePruneError(f"{label} --max-depth cannot be negative.")

    if min_depth is not None and max_depth is not None and min_depth > max_depth:
        raise SafePruneError(f"{label} --min-depth cannot be greater than --max-depth.")


def has_positive_fd_filter(fd_args: argparse.Namespace) -> bool:
    """Return True when fd execution is constrained by a meaningful positive filter."""
    return bool(
        getattr(fd_args, "glob_pattern", None)
        or getattr(fd_args, "extension", None)
        or getattr(fd_args, "min_depth", None) is not None
        or getattr(fd_args, "max_depth", None) is not None
    )


def validate_args(parsed: ParsedCli) -> None:
    """Validate parsed arguments."""
    op_args = parsed.operation

    if getattr(op_args, "limit", None) is not None and op_args.limit < 1:
        raise SafePruneError("--limit must be greater than zero.")

    if getattr(op_args, "quiet", False) and getattr(op_args, "verbose", False):
        raise SafePruneError("--quiet and --verbose cannot be used together.")

    if getattr(op_args, "operation", "delete") == "move" and not getattr(op_args, "target_dir", None):
        raise SafePruneError("The move operation requires --target-dir / -T.")

    if getattr(op_args, "operation", "delete") == "script" and not getattr(op_args, "script_command", None):
        raise SafePruneError("The script operation requires --script-command / -S.")

    if getattr(op_args, "max_bytes", None) is not None and op_args.max_bytes < 1:
        raise SafePruneError("--max-bytes must be greater than zero.")

    if parsed.fd is not None:
        validate_depth_pair(parsed.fd.min_depth, parsed.fd.max_depth, "FD")

    if parsed.rg is not None:
        validate_depth_pair(parsed.rg.min_depth, parsed.rg.max_depth, "RG")
        if not parsed.rg.content_pattern:
            raise SafePruneError("The rg subcommand requires --content-pattern / -p.")

    if not getattr(op_args, "execute", False):
        return

    if parsed.order == ("fd",) and parsed.fd is not None:
        if not has_positive_fd_filter(parsed.fd) and not getattr(op_args, "allow_all", False):
            raise SafePruneError(
                "Refusing to execute with fd because no positive fd filter was provided. "
                "Add --glob-pattern / -g, --extension / -e, depth bounds, or pass --allow-all / -A."
            )


def run(parsed: ParsedCli):
    """Run the selected subcommand sequence."""
    validate_args(parsed)
    roots = resolve_roots(parsed.operation.roots)

    trace = None
    command_name = " ".join(parsed.order)
    tool_config = resolve_tool_config()

    if parsed.order == ("fd",):
        if parsed.fd is None:
            raise SafePruneError("fd arguments were not parsed.")
        targets = collect_fd_targets(parsed.fd, parsed.operation, tool_config)
    elif parsed.order == ("rg",):
        if parsed.rg is None:
            raise SafePruneError("rg arguments were not parsed.")
        targets = collect_rg_targets(parsed.rg, parsed.operation, tool_config)
    elif parsed.order in (("fd", "rg"), ("rg", "fd")):
        targets, trace = collect_combined_targets(parsed, tool_config)
    else:
        raise SafePruneError(f"Unsupported subcommand sequence: {command_name}")

    targets = apply_limit(deduplicate_targets(targets), parsed.operation.limit)
    return apply_targets(targets, roots, parsed.operation, command_name, trace=trace)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Program entry point."""
    try:
        parsed = parse_cli(argv)
        stats = run(parsed)
        print_stats(stats, parsed.operation)
        return 1 if stats.failed_count else 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except SafePruneError as exc:
        print(f"{PROGRAM_NAME}: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"{PROGRAM_NAME}: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
