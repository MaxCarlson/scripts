from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True, slots=True)
class CliArgument:
    dest: str
    flags: Tuple[str, ...] = ()
    is_positional: bool = False
    action_type: str = "store"
    type_fn: Optional[Callable[[str], Any]] = None
    default: Any = None
    choices: Optional[Tuple[Any, ...]] = None
    required: bool = False
    help: Optional[str] = None
    metavar: Optional[str] = None
    nargs: Optional[int | str] = None


@dataclass(frozen=True, slots=True)
class CliCommand:
    name: str
    prog: str
    description: Optional[str] = None
    help: Optional[str] = None
    epilog: Optional[str] = None
    arguments: Tuple[CliArgument, ...] = field(default_factory=tuple)
    subcommands: Dict[str, CliCommand] = field(default_factory=dict)
    subparsers_dest: Optional[str] = None


def introspect_parser(
    parser: argparse.ArgumentParser,
    *,
    name: Optional[str] = None,
    help_text: Optional[str] = None,
) -> CliCommand:
    """Recursively introspect an argparse.ArgumentParser into an immutable CliCommand tree."""
    cmd_name = name or parser.prog or "root"
    arguments: List[CliArgument] = []
    subcommands: Dict[str, CliCommand] = {}
    subparsers_dest: Optional[str] = None

    for action in parser._actions:
        # Ignore help actions and suppressed actions
        if isinstance(action, argparse._HelpAction) or action.help == argparse.SUPPRESS:
            continue

        if isinstance(action, argparse._SubParsersAction):
            subparsers_dest = action.dest
            for sub_name, sub_parser in action.choices.items():
                if sub_parser is parser:
                    continue
                # Some actions share choices under aliases; deduplicate by object identity
                if any(sub_name == existing_name for existing_name in subcommands):
                    continue
                sub_help = getattr(action._choices_actions[len(subcommands)], "help", None) if hasattr(action, "_choices_actions") else None
                # Check choices actions mapping for accurate help text
                for choice_action in getattr(action, "_choices_actions", []):
                    if getattr(choice_action, "dest", None) == sub_name:
                        sub_help = choice_action.help
                        break
                subcommands[sub_name] = introspect_parser(
                    sub_parser,
                    name=sub_name,
                    help_text=sub_help or getattr(sub_parser, "description", None),
                )
            continue

        flags = tuple(action.option_strings)
        is_positional = len(flags) == 0

        action_type = "store"
        if isinstance(action, getattr(argparse, "BooleanOptionalAction", type("dummy", (), {}))):
            action_type = "boolean_optional"
        elif isinstance(action, argparse._StoreTrueAction):
            action_type = "store_true"
        elif isinstance(action, argparse._StoreFalseAction):
            action_type = "store_false"
        elif isinstance(action, argparse._AppendAction):
            action_type = "append"
        elif isinstance(action, argparse._CountAction):
            action_type = "count"

        choices_tuple = tuple(action.choices) if action.choices is not None else None

        arguments.append(
            CliArgument(
                dest=action.dest,
                flags=flags,
                is_positional=is_positional,
                action_type=action_type,
                type_fn=action.type,
                default=action.default,
                choices=choices_tuple,
                required=bool(action.required),
                help=action.help,
                metavar=action.metavar if isinstance(action.metavar, str) else None,
                nargs=action.nargs,
            )
        )

    return CliCommand(
        name=cmd_name,
        prog=parser.prog,
        description=parser.description,
        help=help_text,
        epilog=parser.epilog,
        arguments=tuple(arguments),
        subcommands=subcommands,
        subparsers_dest=subparsers_dest,
    )
