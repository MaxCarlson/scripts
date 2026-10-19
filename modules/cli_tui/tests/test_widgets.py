from __future__ import annotations

import curses

from cli_tui.schema import CliArgument
from cli_tui.widgets import (
    BooleanWidget,
    ChoiceWidget,
    MultiChoiceWidget,
    TextWidget,
    create_widget_for_arg,
)


def test_boolean_widget_toggle():
    arg = CliArgument(dest="sort", flags=("-S", "--sort"), action_type="boolean_optional", default=True)
    widget = BooleanWidget(arg, value=True)

    assert widget.value is True
    assert "[X]" in widget.render_line(width=60, is_focused=False)

    # Space or Enter toggles
    consumed = widget.handle_key(ord(" "))
    assert consumed is True
    assert widget.value is False
    assert "[ ]" in widget.render_line(width=60, is_focused=True)

    # Toggle back
    widget.handle_key(10)  # Enter
    assert widget.value is True


def test_choice_widget_cycling():
    arg = CliArgument(dest="format", flags=("-f", "--format"), choices=("webp", "jpeg", "avif"), default="webp")
    widget = ChoiceWidget(arg, value="webp")

    assert widget.value == "webp"
    assert "webp" in widget.render_line(width=60, is_focused=False)

    # Right arrow cycles forward
    widget.handle_key(curses.KEY_RIGHT)
    assert widget.value == "jpeg"

    widget.handle_key(curses.KEY_RIGHT)
    assert widget.value == "avif"

    # Wraps around
    widget.handle_key(curses.KEY_RIGHT)
    assert widget.value == "webp"

    # Left arrow cycles backward
    widget.handle_key(curses.KEY_LEFT)
    assert widget.value == "avif"


def test_text_widget_editing():
    arg = CliArgument(dest="destination", flags=("-d", "--destination"), default="B:/library")
    widget = TextWidget(arg, value="B:/library")

    assert widget.value == "B:/library"
    assert widget.is_editing is False

    # Enter enters editing mode
    widget.handle_key(10)
    assert widget.is_editing is True

    # Type characters
    widget.handle_key(ord("/"))
    widget.handle_key(ord("m"))
    assert widget.value == "B:/library/m"

    # Backspace
    widget.handle_key(curses.KEY_BACKSPACE)
    assert widget.value == "B:/library/"

    # Enter exits editing mode
    widget.handle_key(10)
    assert widget.is_editing is False


def test_multichoice_widget_toggling():
    arg = CliArgument(dest="quality", flags=("-q", "--quality"), choices=(85, 70, 50), default=[85])
    widget = MultiChoiceWidget(arg, options=(85, 70, 50), value=[85])

    assert widget.value == [85]
    line = widget.render_line(width=60, is_focused=True)
    assert "[X] 85" in line
    assert "[ ] 70" in line

    # Move right to 70 and toggle
    widget.handle_key(curses.KEY_RIGHT)
    widget.handle_key(ord(" "))
    assert 70 in widget.value
    assert 85 in widget.value


def test_create_widget_for_arg_factory():
    arg_bool = CliArgument(dest="verbose", flags=("-v",), action_type="store_true")
    arg_choice = CliArgument(dest="format", flags=("-f",), choices=("webp", "jpeg"))
    arg_text = CliArgument(dest="target", flags=("-t",))

    w1 = create_widget_for_arg(arg_bool, value=False)
    w2 = create_widget_for_arg(arg_choice, value="webp")
    w3 = create_widget_for_arg(arg_text, value="")

    assert isinstance(w1, BooleanWidget)
    assert isinstance(w2, ChoiceWidget)
    assert isinstance(w3, TextWidget)
