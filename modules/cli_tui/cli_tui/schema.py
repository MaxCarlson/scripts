from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


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
        if isinstance(action, (argparse._HelpAction, argparse._VersionAction)) or action.help == argparse.SUPPRESS:
            continue

        if isinstance(action, argparse._SubParsersAction):
            subparsers_dest = action.dest
            for sub_name, sub_parser in action.choices.items():
                if sub_parser is parser:
                    continue
                # Some actions share choices under aliases; deduplicate by object identity
                if any(sub_name == existing_name for existing_name in subcommands):
                    continue
                sub_help = getattr(sub_parser, "description", None)
                for choice_action in getattr(action, "_choices_actions", []):
                    if getattr(choice_action, "dest", None) == sub_name:
                        sub_help = choice_action.help or sub_help
                        break
                subcommands[sub_name] = introspect_parser(
                    sub_parser,
                    name=sub_name,
                    help_text=sub_help,
                )
            continue

        flags = tuple(action.option_strings)
        is_positional = len(flags) == 0

        action_types = {
            argparse._StoreAction: "store",
            argparse._StoreTrueAction: "store_true",
            argparse._StoreFalseAction: "store_false",
            argparse._AppendAction: "append",
            argparse._CountAction: "count",
        }
        boolean_optional_action = getattr(argparse, "BooleanOptionalAction", None)
        if boolean_optional_action is not None:
            action_types[boolean_optional_action] = "boolean_optional"
        extend_action = getattr(argparse, "_ExtendAction", None)
        if extend_action is not None:
            action_types[extend_action] = "extend"

        action_type = action_types.get(type(action))
        if action_type is None:
            raise ValueError(
                f"Argument '{action.dest}' uses unsupported argparse action "
                f"'{type(action).__name__}'"
            )

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
