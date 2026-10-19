from __future__ import annotations

from enum import Enum, auto
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .schema import CliArgument, CliCommand


class TuiScreenMode(Enum):
    MENU = auto()
    FORM = auto()
    RUNNING = auto()
    CONFIRM_QUIT = auto()
    IMAGE_VIEWER = auto()


class NavigationStack:
    """Tracks breadcrumb hierarchy and active screen mode."""

    def __init__(self) -> None:
        self._stack: List[Tuple[str, TuiScreenMode]] = []
        self._current_screen: TuiScreenMode = TuiScreenMode.MENU

    @property
    def current_screen(self) -> TuiScreenMode:
        return self._current_screen

    @current_screen.setter
    def current_screen(self, mode: TuiScreenMode) -> None:
        self._current_screen = mode

    @property
    def path(self) -> List[str]:
        return [crumb for crumb, _ in self._stack]

    def push(self, crumb: str, screen: TuiScreenMode) -> None:
        self._stack.append((crumb, screen))
        self._current_screen = screen

    def pop(self) -> Optional[Tuple[str, TuiScreenMode]]:
        if not self._stack:
            return None
        popped = self._stack.pop()
        self._current_screen = self._stack[-1][1] if self._stack else TuiScreenMode.MENU
        return popped


class FormState:
    """Holds active argument form state and builds command invocation."""

    def __init__(
        self,
        command: CliCommand,
        *,
        subcommands_path: Sequence[str] = (),
    ) -> None:
        self.command = command
        self.subcommands_path = list(subcommands_path)
        self.values: Dict[str, Any] = {}
        self.focused_index: int = 0
        self.is_editing: bool = False

        # Initialize defaults
        for arg in command.arguments:
            if arg.default is not None:
                # Deepcopy mutable defaults like list
                if isinstance(arg.default, list):
                    self.values[arg.dest] = list(arg.default)
                else:
                    self.values[arg.dest] = arg.default
            elif arg.action_type == "store_true":
                self.values[arg.dest] = False
            elif arg.action_type == "store_false":
                self.values[arg.dest] = True
            elif arg.action_type == "append":
                self.values[arg.dest] = []
            else:
                self.values[arg.dest] = None

    def get_value(self, dest: str) -> Any:
        return self.values.get(dest)

    def set_value(self, dest: str, value: Any) -> None:
        self.values[dest] = value

    def build_argv(self, executable: Optional[Sequence[str]] = None) -> List[str]:
        """Convert current form values into exact executable command line tokens."""
        argv: List[str] = list(executable or [self.command.prog or "python"])
        argv.extend(self.subcommands_path)

        positionals: List[CliArgument] = [
            a for a in self.command.arguments if a.is_positional
        ]
        optionals: List[CliArgument] = [
            a for a in self.command.arguments if not a.is_positional
        ]

        # 1. Add positionals in declaration order
        for arg in positionals:
            val = self.values.get(arg.dest)
            if val is not None and val != "":
                if isinstance(val, (list, tuple)):
                    argv.extend(str(item) for item in val)
                else:
                    argv.append(str(val))

        # 2. Add options
        for arg in optionals:
            val = self.values.get(arg.dest)
            if val is None:
                continue

            # Pick canonical long or short flag
            flag = next(
                (f for f in arg.flags if f.startswith("--")),
                arg.flags[0] if arg.flags else None,
            )
            if not flag:
                continue

            # Prefer short flag if available
            short_flag = next((f for f in arg.flags if not f.startswith("--")), flag)

            if arg.action_type == "store_true":
                if val is True:
                    argv.append(short_flag)
            elif arg.action_type == "store_false":
                if val is False:
                    argv.append(short_flag)
            elif arg.action_type == "boolean_optional":
                long_flag = next((f for f in arg.flags if f.startswith("--")), flag)
                clean_name = long_flag.lstrip("-")
                if val is True and arg.default is not True:
                    argv.append(f"--{clean_name}")
                elif val is False and arg.default is not False:
                    argv.append(f"--no-{clean_name}")
            elif arg.action_type == "append":
                if isinstance(val, (list, tuple)):
                    for item in val:
                        argv.extend([short_flag, str(item)])
            elif arg.nargs in ("+", "*"):
                items = (
                    [val]
                    if isinstance(val, str)
                    else list(val) if isinstance(val, (list, tuple)) else []
                )
                if items:
                    argv.append(short_flag)
                    argv.extend(str(item) for item in items)
            else:
                # Regular option with value
                if val is not None and str(val) != "":
                    argv.extend([short_flag, str(val)])

        return argv
