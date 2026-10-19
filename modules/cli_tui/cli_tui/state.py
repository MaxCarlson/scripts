from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
import uuid

from .process_runner import OutputViewport
from .schema import CliArgument, CliCommand


class TuiScreenMode(Enum):
    MENU = auto()
    FORM = auto()
    RUNNING = auto()
    CONFIRM_QUIT = auto()
    IMAGE_VIEWER = auto()


class PaneType(Enum):
    COMMAND = "command"
    CONSOLE = "console"


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
            elif arg.action_type == "count":
                try:
                    count_val = int(val)
                except (ValueError, TypeError):
                    count_val = 0
                base_default = arg.default if isinstance(arg.default, int) else 0
                if count_val > base_default:
                    diff = count_val - base_default
                    argv.extend([short_flag] * diff)
            elif arg.action_type == "append":
                if isinstance(val, (list, tuple)):
                    for item in val:
                        if item is not None and str(item) != "":
                            argv.extend([short_flag, str(item)])
                elif isinstance(val, str) and val.strip():
                    argv.extend([short_flag, val.strip()])
            elif arg.nargs in ("+", "*"):
                if isinstance(val, (list, tuple)):
                    items = [str(x) for x in val if x is not None and str(x) != ""]
                elif isinstance(val, str) and val.strip():
                    items = [val.strip()]
                else:
                    items = []
                if items:
                    argv.append(short_flag)
                    argv.extend(items)
            else:
                # Regular option with value
                if val is not None and str(val) != "":
                    argv.extend([short_flag, str(val)])

        return argv


@dataclass
class PaneSession:
    """Represents an isolated pane session within the workspace."""

    id: str
    title: str = "Main"
    pane_type: PaneType = PaneType.COMMAND
    screen_mode: TuiScreenMode = TuiScreenMode.MENU
    navigation: NavigationStack = field(default_factory=NavigationStack)
    current_form: Optional[FormState] = None
    runner: Optional[Any] = None
    viewport: OutputViewport = field(default_factory=OutputViewport)
    created_at: float = field(default_factory=time.time)
    extra_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def status_badge(self) -> str:
        if self.pane_type == PaneType.CONSOLE:
            return "CONSOLE"
        if self.screen_mode == TuiScreenMode.RUNNING:
            if self.runner and getattr(self.runner, "is_running", False):
                return "RUNNING"
            if self.runner and getattr(self.runner, "exit_code", None) is not None:
                return "FINISHED" if self.runner.exit_code == 0 else "ERROR"
            return "RUNNING"
        if self.screen_mode == TuiScreenMode.FORM:
            return "CONFIG"
        if self.screen_mode == TuiScreenMode.MENU:
            return "MENU"
        return "IDLE"


class PaneWorkspace:
    """Manages the collection of open panes, cycling, and active pane selection."""

    def __init__(self) -> None:
        self.panes: List[PaneSession] = [
            PaneSession(
                id=uuid.uuid4().hex[:8],
                title="Main",
                pane_type=PaneType.COMMAND,
                screen_mode=TuiScreenMode.MENU,
            )
        ]
        self.active_index: int = 0

    @property
    def active_pane(self) -> PaneSession:
        if not self.panes:
            default_pane = PaneSession(
                id=uuid.uuid4().hex[:8],
                title="Main",
                pane_type=PaneType.COMMAND,
                screen_mode=TuiScreenMode.MENU,
            )
            self.panes.append(default_pane)
            self.active_index = 0
        self.active_index = max(0, min(self.active_index, len(self.panes) - 1))
        return self.panes[self.active_index]

    def create_pane(
        self,
        title: str = "New Pane",
        pane_type: PaneType = PaneType.COMMAND,
        screen_mode: TuiScreenMode = TuiScreenMode.MENU,
    ) -> PaneSession:
        new_pane = PaneSession(
            id=uuid.uuid4().hex[:8],
            title=title,
            pane_type=pane_type,
            screen_mode=screen_mode,
        )
        self.panes.append(new_pane)
        self.active_index = len(self.panes) - 1
        return new_pane

    def cycle_next(self) -> None:
        if self.panes:
            self.active_index = (self.active_index + 1) % len(self.panes)

    def cycle_prev(self) -> None:
        if self.panes:
            self.active_index = (self.active_index - 1) % len(self.panes)

    def switch_to(self, index: int) -> bool:
        if 0 <= index < len(self.panes):
            self.active_index = index
            return True
        return False

    def delete_pane(self, index: int) -> bool:
        if index < 0 or index >= len(self.panes):
            return False
        if len(self.panes) <= 1:
            return False

        target = self.panes[index]
        if target.runner:
            if hasattr(target.runner, "stop"):
                target.runner.stop()
            elif hasattr(target.runner, "terminate"):
                target.runner.terminate()

        self.panes.pop(index)
        if self.active_index >= len(self.panes):
            self.active_index = len(self.panes) - 1
        elif self.active_index > index:
            self.active_index -= 1
        return True

    def delete_all(self) -> PaneSession:
        for pane in self.panes:
            if pane.runner:
                if hasattr(pane.runner, "stop"):
                    pane.runner.stop()
                elif hasattr(pane.runner, "terminate"):
                    pane.runner.terminate()
        fresh = PaneSession(
            id=uuid.uuid4().hex[:8],
            title="Main",
            pane_type=PaneType.COMMAND,
            screen_mode=TuiScreenMode.MENU,
        )
        self.panes = [fresh]
        self.active_index = 0
        return fresh


def copy_matching_form_values(
    source: Optional[FormState],
    target: Optional[FormState],
) -> int:
    """Copy matching argument values from source FormState to target FormState."""
    if source is None or target is None:
        return 0

    target_dests = {arg.dest for arg in target.command.arguments}
    copied = 0
    for dest, val in source.values.items():
        if dest in target_dests:
            if val is not None and val != "":
                target.set_value(dest, val)
                copied += 1
    return copied

