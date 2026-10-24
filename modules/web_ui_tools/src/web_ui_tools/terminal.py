"""Bounded incremental filtering of terminal control sequences for plain-text views."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class TerminalParserState:
    """Serializable parser state carried between output chunks."""

    mode: str = "text"
    sequence_length: int = 0


class TerminalTextSanitizer:
    """Remove ANSI/control sequences while preserving ordinary text and line breaks.

    This is not a terminal emulator. Styling, cursor movement, clipboard controls, and other
    escape-driven actions are discarded. State survives chunk boundaries and sequence length is
    capped so a malformed unterminated sequence cannot consume unbounded memory.
    """

    def __init__(self, *, max_sequence_length: int = 4096, state: TerminalParserState | None = None) -> None:
        if max_sequence_length < 8:
            raise ValueError("max_sequence_length must be at least 8")
        self.max_sequence_length = max_sequence_length
        self.state = state or TerminalParserState()

    def feed(self, text: str) -> str:
        """Return safe plain text for one decoded UTF-8 chunk."""

        output: list[str] = []
        mode = self.state.mode
        sequence_length = self.state.sequence_length
        for character in text:
            value = ord(character)
            if mode == "text":
                if character == "\x1b":
                    mode = "escape"
                    sequence_length = 0
                elif character == "\u009b":
                    mode = "csi"
                    sequence_length = 0
                elif character in {"\u0090", "\u0098", "\u009e", "\u009f"}:
                    mode = "string"
                    sequence_length = 0
                elif character == "\u009d":
                    mode = "osc"
                    sequence_length = 0
                elif character in {"\n", "\r", "\t"} or not unicodedata.category(character).startswith("C"):
                    output.append(character)
            elif mode == "escape":
                if character == "[":
                    mode = "csi"
                    sequence_length = 0
                elif character == "]":
                    mode = "osc"
                    sequence_length = 0
                elif character in {"P", "X", "^", "_"}:
                    mode = "string"
                    sequence_length = 0
                elif 0x20 <= value <= 0x2F:
                    mode = "escape-intermediate"
                    sequence_length = 1
                else:
                    mode = "text"
                    sequence_length = 0
            elif mode == "escape-intermediate":
                sequence_length += 1
                if 0x30 <= value <= 0x7E or sequence_length >= self.max_sequence_length:
                    mode = "text"
                    sequence_length = 0
            elif mode == "csi":
                sequence_length += 1
                if 0x40 <= value <= 0x7E or sequence_length >= self.max_sequence_length:
                    mode = "text"
                    sequence_length = 0
            elif mode in {"osc", "string"}:
                sequence_length += 1
                if character in {"\x07", "\u009c"}:
                    mode = "text"
                    sequence_length = 0
                elif character == "\x1b":
                    mode = "string-escape"
                elif sequence_length >= self.max_sequence_length:
                    mode = "text"
                    sequence_length = 0
            elif mode == "string-escape":
                sequence_length += 1
                if character == "\\" or sequence_length >= self.max_sequence_length:
                    mode = "text"
                    sequence_length = 0
                else:
                    mode = "string"
        self.state = TerminalParserState(mode, sequence_length)
        return "".join(output)
