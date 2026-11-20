import pytest

from terminal_launcher.layouts import group_panes
from terminal_launcher.models import PaneSpec


def panes(count: int) -> list[PaneSpec]:
    return [PaneSpec(f"Pane {index}", ("python", str(index))) for index in range(1, count + 1)]


@pytest.mark.parametrize(
    ("count", "per_tab", "expected_groups", "expected_layouts"),
    [
        (1, 2, [1], ["single"]),
        (2, 2, [2], ["two-column"]),
        (3, 3, [3], ["three-left"]),
        (4, 4, [4], ["grid"]),
        (3, 2, [2, 1], ["two-column", "single"]),
        (4, 2, [2, 2], ["two-column", "two-column"]),
        (5, 2, [2, 2, 1], ["two-column", "two-column", "single"]),
        (8, 4, [4, 4], ["grid", "grid"]),
    ],
)
def test_group_panes_selects_deterministic_layouts_and_preserves_order(count, per_tab, expected_groups, expected_layouts):
    source = panes(count)
    plan = group_panes(source, panes_per_tab=per_tab)

    assert [len(tab.panes) for tab in plan.tabs] == expected_groups
    assert [tab.layout for tab in plan.tabs] == expected_layouts
    assert [pane for tab in plan.tabs for pane in tab.panes] == source
    assert [tab.title for tab in plan.tabs] == [
        " | ".join(pane.title for pane in source[offset : offset + size])
        for offset, size in _offset_groups(expected_groups)
    ]


def _offset_groups(groups: list[int]):
    offset = 0
    for size in groups:
        yield offset, size
        offset += size


def test_group_panes_returns_an_empty_plan_for_no_panes():
    assert group_panes([]).tabs == ()


@pytest.mark.parametrize("count", [0, 5, -1, True])
def test_group_panes_rejects_invalid_group_sizes(count):
    with pytest.raises(ValueError, match="between 1 and 4"):
        group_panes([], panes_per_tab=count)


def test_group_panes_carries_target_window_and_has_stable_output():
    source = panes(5)

    first = group_panes(source, panes_per_tab=2, target_window="build")
    second = group_panes(source, panes_per_tab=2, target_window="build")

    assert first == second
    assert first.target_window == "build"
