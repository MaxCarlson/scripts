from __future__ import annotations

import argparse
from pathlib import Path

from cli_tui.schema import introspect_parser
from cli_tui.state import FormState, NavigationStack, TuiScreenMode


def test_navigation_stack_push_pop():
    nav = NavigationStack()
    assert nav.current_screen == TuiScreenMode.MENU
    assert len(nav.path) == 0

    nav.push("compress", TuiScreenMode.MENU)
    assert nav.current_screen == TuiScreenMode.MENU
    assert nav.path == ["compress"]

    nav.push("estimate", TuiScreenMode.FORM)
    assert nav.current_screen == TuiScreenMode.FORM
    assert nav.path == ["compress", "estimate"]

    # Pop returns to compress menu
    popped = nav.pop()
    assert popped == ("estimate", TuiScreenMode.FORM)
    assert nav.current_screen == TuiScreenMode.MENU
    assert nav.path == ["compress"]


def test_form_state_initialization_and_argv_generation():
    parser = argparse.ArgumentParser(prog="mangadl")
    parser.add_argument("-d", "--destination", type=Path, required=True)
    parser.add_argument("-f", "--format", choices=("webp", "jpeg"), default="webp")
    parser.add_argument("-q", "--quality", type=int, nargs="+", default=[85, 70])
    parser.add_argument(
        "-S", "--sort", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-t", "--threads", type=int, default=4)

    cmd = introspect_parser(parser)
    form = FormState(cmd, subcommands_path=["compress", "estimate"])

    # Initial values should match defaults
    assert form.get_value("format") == "webp"
    assert form.get_value("quality") == [85, 70]
    assert form.get_value("sort") is True
    assert form.get_value("verbose") is False
    assert form.get_value("threads") == 4
    assert form.get_value("destination") is None

    # Setting value
    form.set_value("destination", "B:/Hent/hent1imageperpage")
    form.set_value("sort", False)
    form.set_value("threads", 8)
    form.set_value("verbose", True)

    argv = form.build_argv(executable=["python", "-m", "mangadl"])
    assert argv == [
        "python",
        "-m",
        "mangadl",
        "compress",
        "estimate",
        "-d",
        "B:/Hent/hent1imageperpage",
        "-f",
        "webp",
        "-q",
        "85",
        "70",
        "--no-sort",
        "-v",
        "-t",
        "8",
    ]


def test_form_state_positionals_and_append():
    parser = argparse.ArgumentParser(prog="tool")
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("-i", "--include", action="append", default=[])

    cmd = introspect_parser(parser)
    form = FormState(cmd)

    form.set_value("source", "input.txt")
    form.set_value("target", "output.txt")
    form.set_value("include", ["*.jpg", "*.png"])

    argv = form.build_argv(executable=["tool"])
    assert argv == [
        "tool",
        "input.txt",
        "output.txt",
        "-i",
        "*.jpg",
        "-i",
        "*.png",
    ]


def test_form_state_count_action():
    parser = argparse.ArgumentParser(prog="mangadl")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    cmd = introspect_parser(parser)
    form = FormState(cmd)

    # 1. Default count 0: should NOT emit -v or 0
    assert form.get_value("verbose") == 0
    argv = form.build_argv(executable=["mangadl"])
    assert argv == ["mangadl"]

    # 2. Count 1: should emit ["-v"] (and definitely NOT ["-v", "0"] or ["-v", "1"])
    form.set_value("verbose", 1)
    argv = form.build_argv(executable=["mangadl"])
    assert argv == ["mangadl", "-v"]

    # 3. Count 2: should emit ["-v", "-v"]
    form.set_value("verbose", 2)
    argv = form.build_argv(executable=["mangadl"])
    assert argv == ["mangadl", "-v", "-v"]

    # 4. Count as string "1" (from text input or form)
    form.set_value("verbose", "1")
    argv = form.build_argv(executable=["mangadl"])
    assert argv == ["mangadl", "-v"]


def test_form_state_append_string_and_empty_list():
    parser = argparse.ArgumentParser(prog="mangadl")
    parser.add_argument("-u", "--url", action="append", default=[])
    cmd = introspect_parser(parser)
    form = FormState(cmd)

    # 1. Default empty list should emit no flags
    assert form.get_value("url") == []
    argv = form.build_argv(executable=["mangadl"])
    assert argv == ["mangadl"]

    # 2. Empty string should emit no flags
    form.set_value("url", "")
    argv = form.build_argv(executable=["mangadl"])
    assert argv == ["mangadl"]

    # 3. Non-empty string should emit flag with that string
    form.set_value("url", "https://example.com/ch1")
    argv = form.build_argv(executable=["mangadl"])
    assert argv == ["mangadl", "-u", "https://example.com/ch1"]
