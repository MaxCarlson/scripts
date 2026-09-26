"""Parse live CLI help text into browsable arguments and subcommands."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class HelpArgument:
    short: str | None
    long: str | None
    usage: str
    description: str

    @property
    def label(self) -> str:
        parts = [part for part in (self.short, self.long) if part]
        return "  ".join(parts) if parts else self.usage


@dataclass(frozen=True)
class HelpSubcommand:
    name: str
    description: str = ""


@dataclass(frozen=True)
class ParsedHelp:
    arguments: tuple[HelpArgument, ...]
    subcommands: tuple[HelpSubcommand, ...]


_SHORT_RE = re.compile(r"(?<!\S)(-[A-Za-z0-9?])(?=[,\s=]|$)")
_LONG_RE = re.compile(r"(?<!\S)(--[A-Za-z0-9][A-Za-z0-9_-]*)(?=[,\s=]|$)")
_OPTION_START_RE = re.compile(r"^\s+(-[^\s].*?)(?:\s{2,}|\t+)(\S.*)$")
_SECTION_RE = re.compile(r"^\s*([A-Za-z][A-Za-z /_-]+):\s*$")
_SUBCOMMAND_SET_RE = re.compile(r"^\s*\{([A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)+)\}")


def _option_parts(usage: str) -> tuple[str | None, str | None]:
    short_match = _SHORT_RE.search(usage)
    long_match = _LONG_RE.search(usage)
    return (
        short_match.group(1) if short_match else None,
        long_match.group(1) if long_match else None,
    )


def _append_continuation(arguments: list[HelpArgument], line: str) -> None:
    if not arguments:
        return
    text = line.strip()
    if not text:
        return
    previous = arguments[-1]
    description = f"{previous.description} {text}".strip()
    arguments[-1] = HelpArgument(
        short=previous.short,
        long=previous.long,
        usage=previous.usage,
        description=description,
    )


def parse_help_text(text: str) -> ParsedHelp:
    """Parse argparse/click-style help without importing the target program.

    Descriptions are taken from the program's emitted help text.  The parser is
    intentionally conservative: unknown layouts remain readable as raw help in
    the caller rather than being guessed into incorrect arguments.
    """

    lines = text.splitlines()
    arguments: list[HelpArgument] = []
    subcommands: dict[str, HelpSubcommand] = {}
    current_section = ""
    argparse_names: set[str] = set()
    last_was_option = False

    for line in lines:
        section = _SECTION_RE.match(line)
        if section and not line.lstrip().startswith("-"):
            current_section = section.group(1).strip().casefold()
            last_was_option = False
            continue

        set_match = _SUBCOMMAND_SET_RE.match(line)
        if set_match and (
            "positional" in current_section
            or "command" in current_section
            or "subcommand" in current_section
        ):
            argparse_names.update(
                name.strip() for name in set_match.group(1).split(",") if name.strip()
            )
            last_was_option = False
            continue

        option = _OPTION_START_RE.match(line)
        if option:
            usage = option.group(1).strip()
            description = option.group(2).strip()
            short, long = _option_parts(usage)
            if short or long:
                arguments.append(
                    HelpArgument(
                        short=short,
                        long=long,
                        usage=usage,
                        description=description,
                    )
                )
                last_was_option = True
                continue

        command_line = re.match(r"^\s{2,}([A-Za-z0-9][A-Za-z0-9_-]*)\s{2,}(.*\S)\s*$", line)
        if command_line:
            name = command_line.group(1)
            description = command_line.group(2).strip()
            in_command_section = "command" in current_section or "subcommand" in current_section
            if in_command_section or name in argparse_names:
                subcommands[name] = HelpSubcommand(name=name, description=description)
                last_was_option = False
                continue

        # Argparse normally indents wrapped option descriptions farther than
        # the option declaration itself.
        if last_was_option and line.startswith(("      ", "\t\t")) and line.strip():
            _append_continuation(arguments, line)
            continue

        if line.strip():
            last_was_option = False

    for name in sorted(argparse_names):
        subcommands.setdefault(name, HelpSubcommand(name=name))

    return ParsedHelp(
        arguments=tuple(arguments),
        subcommands=tuple(subcommands.values()),
    )


def format_argument(argument: HelpArgument) -> str:
    """Render short flag first, then long flag, then the live description."""

    pieces = []
    if argument.short:
        pieces.append(argument.short)
    if argument.long:
        pieces.append(argument.long)
    if not pieces:
        pieces.append(argument.usage)

    flags = "  ".join(pieces)
    if argument.description:
        return f"{flags:<24} {argument.description}"
    return flags
