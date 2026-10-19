from __future__ import annotations

import curses
from typing import Any, List, Sequence, Tuple

from .schema import CliArgument


class BaseWidget:
    """Base class for interactive form widgets."""

    def __init__(self, arg: CliArgument, value: Any) -> None:
        self.arg = arg
        self.value = value
        self.label = self._build_label()
        self.help_text = arg.help or ""
        self.is_editing: bool = False

    def _build_label(self) -> str:
        if self.arg.flags:
            # e.g. "--destination (-d)"
            long_flag = next((f for f in self.arg.flags if f.startswith("--")), None)
            short_flag = next(
                (f for f in self.arg.flags if not f.startswith("--")), None
            )
            if long_flag and short_flag:
                return f"{long_flag} ({short_flag})"
            return long_flag or short_flag or self.arg.dest
        return self.arg.dest

    def handle_key(self, key: int) -> bool:
        """Handle key input. Return True if handled."""
        return False

    def render_line(self, width: int, is_focused: bool) -> str:
        """Render widget line for console."""
        focus_mark = "▶ " if is_focused else "  "
        return f"{focus_mark}{self.label}: {self.value}"

    def render_lines(self, width: int, is_focused: bool) -> List[str]:
        """Render widget line(s) fitting width."""
        return [self.render_line(width, is_focused)]


class BooleanWidget(BaseWidget):
    """Checkbox widget for boolean flags."""

    def __init__(self, arg: CliArgument, value: Any) -> None:
        super().__init__(arg, bool(value))

    def handle_key(self, key: int) -> bool:
        # Space, Enter, or 't' toggles
        if key in (ord(" "), 10, 13, ord("t")):
            self.value = not self.value
            return True
        return False

    def render_line(self, width: int, is_focused: bool) -> str:
        focus_mark = "▶ " if is_focused else "  "
        box = "[X]" if self.value else "[ ]"
        return f"{focus_mark}{box} {self.label}"


class ChoiceWidget(BaseWidget):
    """Dropdown/cycler widget for choices."""

    def __init__(self, arg: CliArgument, value: Any) -> None:
        super().__init__(arg, value)
        self.choices: Tuple[Any, ...] = arg.choices or ()
        if self.choices and self.value not in self.choices:
            self.value = self.choices[0]

    def handle_key(self, key: int) -> bool:
        if not self.choices:
            return False
        idx = self.choices.index(self.value) if self.value in self.choices else 0

        # Right arrow, Space, or Enter cycles forward
        if key in (curses.KEY_RIGHT, ord("l"), ord(" "), 10, 13):
            next_idx = (idx + 1) % len(self.choices)
            self.value = self.choices[next_idx]
            return True
        # Left arrow cycles backward
        elif key in (curses.KEY_LEFT, ord("h")):
            prev_idx = (idx - 1 + len(self.choices)) % len(self.choices)
            self.value = self.choices[prev_idx]
            return True
        return False

    def render_line(self, width: int, is_focused: bool) -> str:
        focus_mark = "▶ " if is_focused else "  "
        choice_str = f"◀ {self.value} ▶" if is_focused else f"< {self.value} >"
        return f"{focus_mark}{self.label}: {choice_str}"


class TextWidget(BaseWidget):
    """Single-line text input field."""

    def __init__(self, arg: CliArgument, value: Any) -> None:
        if isinstance(value, (list, tuple)) and not value:
            display_val = ""
        elif value is None or str(value) == "[]":
            display_val = ""
        else:
            display_val = str(value)
        super().__init__(arg, display_val)
        self.cursor_pos: int = len(self.value)

    def handle_key(self, key: int) -> bool:
        if not self.is_editing:
            # Enter or 'e' enters editing mode
            if key in (10, 13, ord("e")):
                self.is_editing = True
                self.cursor_pos = len(self.value)
                return True
            return False

        # In editing mode:
        if key in (10, 13, 27):  # Enter or Esc ends editing mode
            self.is_editing = False
            return True
        elif key in (curses.KEY_BACKSPACE, 127, 8):  # Backspace
            if self.cursor_pos > 0:
                self.value = (
                    self.value[: self.cursor_pos - 1] + self.value[self.cursor_pos :]
                )
                self.cursor_pos -= 1
            return True
        elif key in (curses.KEY_DC,):  # Delete
            if self.cursor_pos < len(self.value):
                self.value = (
                    self.value[: self.cursor_pos] + self.value[self.cursor_pos + 1 :]
                )
            return True
        elif key in (curses.KEY_LEFT,):
            if self.cursor_pos > 0:
                self.cursor_pos -= 1
            return True
        elif key in (curses.KEY_RIGHT,):
            if self.cursor_pos < len(self.value):
                self.cursor_pos += 1
            return True
        elif 32 <= key <= 126:  # Printable character
            ch = chr(key)
            self.value = (
                self.value[: self.cursor_pos] + ch + self.value[self.cursor_pos :]
            )
            self.cursor_pos += 1
            return True
        return False

    def render_line(self, width: int, is_focused: bool) -> str:
        focus_mark = "▶ " if is_focused else "  "
        prefix = f"{focus_mark}{self.label}: "
        avail = max(10, width - len(prefix) - 4)
        val = str(self.value or "")
        if self.is_editing:
            if len(val) > avail:
                start = max(0, self.cursor_pos - avail + 2)
                sub_val = val[start : start + avail]
                val_display = f"[{sub_val}▏]"
            else:
                val_display = f"[{val}▏]"
        else:
            if len(val) > avail:
                val_display = f"[ ...{val[-(avail - 3) :]} ]"
            else:
                val_display = f"[ {val or '—'} ]"
        return f"{prefix}{val_display}"


class CountWidget(BaseWidget):
    """Counter widget for count actions (e.g. -v, -vv)."""

    def __init__(self, arg: CliArgument, value: Any, max_count: int = 5) -> None:
        try:
            int_val = int(value)
        except (ValueError, TypeError):
            int_val = int(arg.default or 0)
        super().__init__(arg, int_val)
        self.max_count = max_count

    def handle_key(self, key: int) -> bool:
        if key in (curses.KEY_RIGHT, ord("l"), ord("+")):
            if self.value < self.max_count:
                self.value += 1
                return True
        elif key in (curses.KEY_LEFT, ord("h"), ord("-")):
            if self.value > 0:
                self.value -= 1
                return True
        elif key in (ord(" "), 10, 13):
            self.value = (self.value + 1) % (self.max_count + 1)
            return True
        return False

    def render_line(self, width: int, is_focused: bool) -> str:
        focus_mark = "▶ " if is_focused else "  "
        val_str = f"◀ {self.value} ▶" if is_focused else f"< {self.value} >"
        short_flag = next((f for f in self.arg.flags if not f.startswith("--")), None)
        hint = ""
        if self.value > 0 and short_flag:
            hint = f" ({short_flag * self.value})"
        return f"{focus_mark}{self.label}: {val_str}{hint}"


class MultiChoiceWidget(BaseWidget):
    """Multi-selection widget for list or choices."""

    def __init__(self, arg: CliArgument, options: Sequence[Any], value: Any) -> None:
        super().__init__(arg, list(value) if isinstance(value, (list, tuple)) else [])
        self.options: Tuple[Any, ...] = tuple(options)
        self.cursor_option_idx: int = 0

    def handle_key(self, key: int) -> bool:
        if key in (curses.KEY_RIGHT, ord("l")):
            if self.options:
                self.cursor_option_idx = (self.cursor_option_idx + 1) % len(
                    self.options
                )
            return True
        elif key in (curses.KEY_LEFT, ord("h")):
            if self.options:
                self.cursor_option_idx = (
                    self.cursor_option_idx - 1 + len(self.options)
                ) % len(self.options)
            return True
        elif key in (ord(" "), 10, 13):
            if self.options:
                opt = self.options[self.cursor_option_idx]
                val_list = list(self.value)
                if opt in val_list:
                    val_list.remove(opt)
                else:
                    val_list.append(opt)
                self.value = val_list
            return True
        return False

    def render_lines(self, width: int, is_focused: bool) -> List[str]:
        focus_mark = "▶ " if is_focused else "  "
        label_prefix = f"{focus_mark}{self.label}: "
        indent_prefix = " " * len(label_prefix)

        rendered_opts: List[str] = []
        for idx, opt in enumerate(self.options):
            checked = "[X]" if opt in self.value else "[ ]"
            if is_focused and idx == self.cursor_option_idx:
                rendered_opts.append(f"<{checked} {opt}>")
            else:
                rendered_opts.append(f"{checked} {opt}")

        if not rendered_opts:
            return [label_prefix]

        lines: List[str] = []
        current_line = label_prefix
        avail_width = max(20, width)

        for opt_str in rendered_opts:
            candidate = (
                f"{current_line}{opt_str}"
                if current_line == label_prefix
                else f"{current_line}  {opt_str}"
            )
            if len(candidate) <= avail_width or (
                current_line == label_prefix
                and len(candidate) <= len(label_prefix) + len(opt_str)
            ):
                current_line = candidate
            else:
                lines.append(current_line)
                current_line = f"{indent_prefix}{opt_str}"

        if current_line:
            lines.append(current_line)

        return lines

    def render_line(self, width: int, is_focused: bool) -> str:
        return "\n".join(self.render_lines(width, is_focused))


def create_widget_for_arg(arg: CliArgument, value: Any) -> BaseWidget:
    """Factory creating appropriate widget for given CliArgument."""
    if arg.action_type in ("store_true", "store_false", "boolean_optional"):
        return BooleanWidget(arg, value)
    elif arg.action_type == "count":
        return CountWidget(arg, value)
    elif arg.choices is not None:
        if arg.nargs in ("+", "*") or arg.action_type == "append":
            return MultiChoiceWidget(arg, options=arg.choices, value=value)
        return ChoiceWidget(arg, value)
    else:
        return TextWidget(arg, value)
