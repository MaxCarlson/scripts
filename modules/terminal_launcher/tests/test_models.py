import pytest
from terminal_launcher.models import PaneSpec, TabSpec, TerminalLaunchPlan


def test_pane_spec_preserves_arguments_as_an_immutable_tuple():
    pane = PaneSpec("Worker 🧪", (r"C:\Program Files\tool.exe", "two words", ";", "λ"), r"C:\Work Here")

    assert pane.title == "Worker 🧪"
    assert pane.argv == (r"C:\Program Files\tool.exe", "two words", ";", "λ")
    assert pane.cwd == r"C:\Work Here"


def test_pane_spec_rejects_empty_or_invalid_executable_arguments():
    with pytest.raises(ValueError, match="at least one"):
        PaneSpec("empty", ())
    with pytest.raises(ValueError, match="executable"):
        PaneSpec("empty executable", ("", "arg"))
    with pytest.raises(ValueError, match="cwd"):
        PaneSpec("empty cwd", ("worker",), "")


def test_tab_spec_rejects_invalid_pane_counts_and_layouts():
    pane = PaneSpec("one", ("python",))

    with pytest.raises(ValueError, match="between 1 and 4"):
        TabSpec("empty", ())
    with pytest.raises(ValueError, match="between 1 and 4"):
        TabSpec("too many", (pane,) * 5)
    with pytest.raises(ValueError, match="layout"):
        TabSpec("bad layout", (pane,), "diagonal")


def test_plan_is_immutable_and_allows_an_explicit_empty_plan():
    plan = TerminalLaunchPlan(())

    assert plan.tabs == ()
    with pytest.raises((AttributeError, TypeError)):
        plan.target_window = "other"
