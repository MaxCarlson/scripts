"""Immutable, terminal-independent descriptions of process layouts."""

from dataclasses import dataclass
from typing import Literal


Layout = Literal["auto", "single", "two-column", "three-left", "grid"]
LAYOUT_PANE_COUNTS: dict[str, int] = {
    "single": 1,
    "two-column": 2,
    "three-left": 3,
    "grid": 4,
}
VALID_LAYOUTS = frozenset(("auto", *LAYOUT_PANE_COUNTS))


def _require_text(value: str, field: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"{field} must be a non-empty string")
    if "\0" in value:
        raise ValueError(f"{field} cannot contain a NUL character")


@dataclass(frozen=True, slots=True)
class PaneSpec:
    """A process to run in one pane, represented without shell interpretation."""

    title: str
    argv: tuple[str, ...]
    cwd: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.title, "title")
        try:
            argv = tuple(self.argv)
        except TypeError as exc:
            raise ValueError("argv must be a non-empty sequence of strings") from exc
        if not argv:
            raise ValueError("argv must contain at least one executable argument")
        if not isinstance(argv[0], str) or not argv[0]:
            raise ValueError("argv must start with a non-empty executable")
        for arg in argv:
            _require_text(arg, "argv item", allow_empty=True)
        object.__setattr__(self, "argv", argv)
        if self.cwd is not None:
            _require_text(self.cwd, "cwd", allow_empty=True)


@dataclass(frozen=True, slots=True)
class TabSpec:
    """A named tab containing one to four process panes."""

    title: str
    panes: tuple[PaneSpec, ...]
    layout: Layout = "auto"

    def __post_init__(self) -> None:
        _require_text(self.title, "title")
        try:
            panes = tuple(self.panes)
        except TypeError as exc:
            raise ValueError("panes must be a sequence containing between 1 and 4 panes") from exc
        if not 1 <= len(panes) <= 4:
            raise ValueError("a tab must contain between 1 and 4 panes")
        if not all(isinstance(pane, PaneSpec) for pane in panes):
            raise ValueError("panes must contain PaneSpec values")
        if self.layout not in VALID_LAYOUTS:
            raise ValueError(f"unsupported layout {self.layout!r}; expected one of {sorted(VALID_LAYOUTS)}")
        if self.layout != "auto" and LAYOUT_PANE_COUNTS[self.layout] != len(panes):
            raise ValueError(f"layout {self.layout!r} requires {LAYOUT_PANE_COUNTS[self.layout]} panes")
        object.__setattr__(self, "panes", panes)


@dataclass(frozen=True, slots=True)
class TerminalLaunchPlan:
    """A backend-independent ordered collection of tabs."""

    tabs: tuple[TabSpec, ...]
    target_window: str | None = None

    def __post_init__(self) -> None:
        try:
            tabs = tuple(self.tabs)
        except TypeError as exc:
            raise ValueError("tabs must be a sequence of TabSpec values") from exc
        if not all(isinstance(tab, TabSpec) for tab in tabs):
            raise ValueError("tabs must contain TabSpec values")
        object.__setattr__(self, "tabs", tabs)
        if self.target_window is not None:
            _require_text(self.target_window, "target_window")
