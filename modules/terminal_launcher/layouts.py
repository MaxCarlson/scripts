"""Terminal-independent, deterministic pane grouping and layout selection."""

from collections.abc import Sequence

from .models import PaneSpec, TabSpec, TerminalLaunchPlan


def _layout_for_pane_count(count: int) -> str:
    return {1: "single", 2: "two-column", 3: "three-left", 4: "grid"}[count]


def group_panes(
    panes: Sequence[PaneSpec],
    *,
    panes_per_tab: int = 2,
    target_window: str | None = None,
) -> TerminalLaunchPlan:
    """Group panes in caller order, selecting the canonical layout for each tab."""
    if isinstance(panes_per_tab, bool) or not 1 <= panes_per_tab <= 4:
        raise ValueError("panes_per_tab must be between 1 and 4")
    pane_list = tuple(panes)
    if not all(isinstance(pane, PaneSpec) for pane in pane_list):
        raise ValueError("panes must contain PaneSpec values")

    tabs = []
    for offset in range(0, len(pane_list), panes_per_tab):
        group = pane_list[offset : offset + panes_per_tab]
        tabs.append(
            TabSpec(
                title=" | ".join(pane.title for pane in group),
                panes=group,
                layout=_layout_for_pane_count(len(group)),
            )
        )
    return TerminalLaunchPlan(tuple(tabs), target_window)
