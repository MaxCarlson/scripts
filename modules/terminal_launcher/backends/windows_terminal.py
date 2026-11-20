"""Windows Terminal command-line backend."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from ..backend import LaunchPreview, LaunchResult, LaunchStatus, PlannedOperation, ProcessState
from ..errors import InvalidPlanError, TerminalNotFoundError, UnsupportedLayoutError, UnsupportedPlatformError
from ..models import PaneSpec, TabSpec, TerminalLaunchPlan

_LAYOUTS = frozenset(("single", "two-column", "three-left", "grid"))
_LAYOUT_COMMANDS: dict[str, tuple[tuple[str, str], ...]] = {
    "single": (),
    "two-column": (("split", "-V"),),
    "three-left": (("split", "-V"), ("split", "-H")),
    "grid": (("split", "-V"), ("focus", "left"), ("split", "-H"), ("focus", "right"), ("split", "-H")),
}

Runner = Callable[..., subprocess.CompletedProcess[str]]


class WindowsTerminalBackend:
    """Submit terminal-independent plans through the documented ``wt.exe`` CLI.

    With no explicit window target, Windows Terminal applies its
    ``windowingBehavior`` preference. Preview reports that policy instead of
    implying that a particular existing window will be selected.
    """

    name = "windows-terminal"

    def __init__(self, executable: str | os.PathLike[str] | None = None, runner: Runner | None = None):
        self._executable = os.fspath(executable) if executable is not None else None
        self._runner = runner or subprocess.run

    def _require_windows(self) -> None:
        if not sys.platform.startswith("win"):
            raise UnsupportedPlatformError("WindowsTerminalBackend is supported only on Windows")

    def _resolve_executable(self) -> str:
        if self._executable is not None:
            return self._executable
        executable = shutil.which("wt.exe") or shutil.which("wt")
        if executable is None:
            raise TerminalNotFoundError("Windows Terminal was not found; install it or provide its wt.exe path")
        return executable

    @staticmethod
    def _validated_tabs(plan: TerminalLaunchPlan) -> tuple[tuple[TabSpec, str], ...]:
        if not isinstance(plan, TerminalLaunchPlan):
            raise InvalidPlanError("plan must be a TerminalLaunchPlan")
        if plan.target_window is not None:
            WindowsTerminalBackend._validate_wt_value(plan.target_window, "target_window")
        resolved = []
        for tab in plan.tabs:
            if not isinstance(tab, TabSpec):
                raise InvalidPlanError("plan tabs must be TabSpec values")
            layout = tab.layout if tab.layout != "auto" else {
                1: "single",
                2: "two-column",
                3: "three-left",
                4: "grid",
            }.get(len(tab.panes))
            if layout not in _LAYOUTS:
                raise UnsupportedLayoutError(f"Windows Terminal cannot represent layout {tab.layout!r}")
            expected = {"single": 1, "two-column": 2, "three-left": 3, "grid": 4}[layout]
            if len(tab.panes) != expected:
                raise UnsupportedLayoutError(f"layout {layout!r} requires {expected} panes")
            WindowsTerminalBackend._validate_wt_value(tab.title, "tab title")
            for pane in tab.panes:
                WindowsTerminalBackend._relay_argv(pane)
            resolved.append((tab, layout))
        return tuple(resolved)

    @staticmethod
    def _relay_argv(pane: PaneSpec) -> tuple[str, ...]:
        payload = json.dumps((pane.argv, pane.cwd), ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        relay = (sys.executable, os.fspath(Path(__file__).with_name("_pane_runner.py")), encoded)
        if any(";" in item for item in relay[:2]):
            raise UnsupportedLayoutError("The Python executable or terminal_launcher path contains a WT command separator")
        return relay

    @staticmethod
    def _validate_wt_value(value: str, name: str) -> str:
        """Reject values that WT's command separator would corrupt."""
        if ";" in value:
            raise UnsupportedLayoutError(f"{name} cannot contain a semicolon with the documented Windows Terminal CLI")
        return value

    @classmethod
    def _pane_arguments(cls, pane: PaneSpec, tab_title: str) -> list[str]:
        arguments = ["--title", cls._validate_wt_value(tab_title, "tab title"), "--suppressApplicationTitle"]
        arguments.extend(cls._relay_argv(pane))
        return arguments

    def build_command(self, plan: TerminalLaunchPlan) -> tuple[str, ...]:
        """Return the exact argv vector submitted to the Windows Terminal CLI."""
        self._require_windows()
        tabs = self._validated_tabs(plan)
        executable = self._resolve_executable()
        command: list[str] = [executable]
        if plan.target_window is not None:
            command.extend(("--window", self._validate_wt_value(plan.target_window, "target_window")))

        for tab_index, (tab, layout) in enumerate(tabs):
            command.extend(("new-tab", *self._pane_arguments(tab.panes[0], tab.title)))
            pane_index = 1
            for action, value in _LAYOUT_COMMANDS[layout]:
                if action == "focus":
                    command.extend((";", "move-focus", value))
                    continue
                command.extend((";", "split-pane", value))
                command.extend(self._pane_arguments(tab.panes[pane_index], tab.title))
                pane_index += 1
            if tab_index + 1 < len(tabs):
                command.append(";")
        return tuple(command)

    def preview(self, plan: TerminalLaunchPlan) -> LaunchPreview:
        self._require_windows()
        tabs = self._validated_tabs(plan)
        if tabs:
            self._resolve_executable()
        operations = []
        for tab_index, (tab, layout) in enumerate(tabs):
            operations.append(
                PlannedOperation("create_tab", tab_index, 0, tab.title, tab.panes[0].title, layout, tab.panes[0].cwd)
            )
            for pane_index, pane in enumerate(tab.panes[1:], start=1):
                operations.append(
                    PlannedOperation("split_pane", tab_index, pane_index, tab.title, pane.title, layout, pane.cwd)
                )
        warnings = []
        if plan.tabs and plan.target_window is None:
            warnings.append(
                "No target_window supplied; Windows Terminal selects its destination according to the user's "
                "windowingBehavior setting."
            )
        if plan.tabs:
            warnings.append(
                "The installed wt.exe version is not probed during side-effect-free preview; CLI compatibility is "
                "assumed from the documented commands. Pane process state cannot be verified by submission."
            )
        return LaunchPreview(
            backend=self.name,
            operations=tuple(operations),
            warnings=tuple(warnings),
            capabilities=frozenset({"multi-tab", "per-pane-cwd", "persistent-title", "target-window", *(_LAYOUTS)}),
        )

    def launch(self, plan: TerminalLaunchPlan) -> LaunchResult:
        self._require_windows()
        tabs = self._validated_tabs(plan)
        if not tabs:
            return LaunchResult(LaunchStatus.NOOP, self.name, diagnostic="The plan contains no terminal operations.")
        try:
            preview = self.preview(plan)
            command = self.build_command(plan)
        except TerminalNotFoundError as exc:
            return LaunchResult(LaunchStatus.FAILED, self.name, diagnostic=str(exc))
        try:
            completed = self._runner(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return LaunchResult(
                LaunchStatus.FAILED,
                self.name,
                diagnostic=f"Could not submit the request to wt.exe ({type(exc).__name__}).",
                warnings=preview.warnings,
            )

        if completed.returncode:
            return LaunchResult(
                LaunchStatus.FAILED,
                self.name,
                returncode=completed.returncode,
                diagnostic="Windows Terminal rejected the launch request; pane execution was not verified.",
                warnings=preview.warnings,
            )
        return LaunchResult(
            LaunchStatus.SUBMITTED,
            self.name,
            process_state=ProcessState.UNKNOWN,
            returncode=0,
            warnings=preview.warnings,
        )
