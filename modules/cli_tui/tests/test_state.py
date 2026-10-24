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


def test_count_action_cannot_request_a_value_below_its_parser_default():
    parser = argparse.ArgumentParser(prog="tool")
    parser.add_argument("-v", action="count", default=2)
    form = FormState(introspect_parser(parser))
    form.set_value("v", 1)

    import pytest

    with pytest.raises(ValueError, match=r"below its default \(2\)"):
        form.build_argv(executable=["tool"])


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


def test_form_state_nargs_string_tokens_splitting():
    parser = argparse.ArgumentParser(prog="mangadl")
    parser.add_argument("-q", "--quality", nargs="+", type=int)
    parser.add_argument("-u", "--url", action="append")
    parser.add_argument("files", nargs="*")

    cmd = introspect_parser(parser)
    form = FormState(cmd)

    # Multi-value nargs option given space-separated string "80 70"
    form.set_value("quality", "80 70")
    # Multi-value append option given space-separated string "u1 u2"
    form.set_value("url", "https://site/1 https://site/2")
    # Positional nargs given space-separated string "a.txt b.txt"
    form.set_value("files", "a.txt b.txt")

    argv = form.build_argv(executable=["mangadl"])
    assert argv == [
        "mangadl",
        "a.txt",
        "b.txt",
        "-q",
        "80",
        "70",
        "-u",
        "https://site/1",
        "-u",
        "https://site/2",
    ]
    parsed = parser.parse_args(argv[1:])
    assert parsed.quality == [80, 70]
    assert parsed.url == ["https://site/1", "https://site/2"]
    assert parsed.files == ["a.txt", "b.txt"]


def test_form_state_common_actions_round_trip_through_argparse():
    parser = argparse.ArgumentParser(prog="tool")
    parser.add_argument("source", type=Path)
    parser.add_argument("--mode", choices=("fast", "safe"), required=True)
    parser.add_argument("--pair", nargs=2)
    parser.add_argument("-I", "--include", action="append", default=[])
    parser.add_argument("--sorted", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("-v", "--verbose", action="count", default=1)
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--color", action="store_false", default=True)
    command = introspect_parser(parser)
    form = FormState(command)
    form.set_value("source", "folder with space/input.txt")
    form.set_value("mode", "safe")
    form.set_value("pair", ["left", "right"])
    form.set_value("include", ["one", "two"])
    form.set_value("sorted", False)
    form.set_value("verbose", 3)
    form.set_value("quiet", True)
    form.set_value("color", False)

    argv = form.build_argv(executable=["tool"])[1:]
    parsed = parser.parse_args(argv)

    assert parsed.source == Path("folder with space/input.txt")
    assert parsed.mode == "safe"
    assert parsed.pair == ["left", "right"]
    assert parsed.include == ["one", "two"]
    assert parsed.sorted is False
    assert parsed.verbose == 3
    assert parsed.quiet is True
    assert parsed.color is False


def test_optional_nargs_round_trips_without_shell_tokenization():
    parser = argparse.ArgumentParser(prog="tool")
    parser.add_argument("--mode", nargs="?", const="automatic", default=None)
    parser.add_argument("source", nargs="?")
    command = introspect_parser(parser)
    form = FormState(command)
    form.set_value("mode", "manual mode")
    form.set_value("source", "folder with space/source.txt")

    argv = form.build_argv(executable=["tool"])[1:]

    assert argv == ["folder with space/source.txt", "--mode", "manual mode"]
    parsed = parser.parse_args(argv)
    assert parsed.mode == "manual mode"
    assert parsed.source == "folder with space/source.txt"


def test_append_with_nargs_plus_preserves_argparse_occurrence_grouping():
    parser = argparse.ArgumentParser(prog="tool")
    parser.add_argument("--tag", action="append", nargs="+")
    form = FormState(introspect_parser(parser))
    form.set_value("tag", ["one", "two"])

    argv = form.build_argv(executable=["tool"])[1:]

    assert argv == ["--tag", "one", "two"]
    assert parser.parse_args(argv).tag == [["one", "two"]]


def test_form_state_fixed_nargs_round_trips_through_argparse():
    parser = argparse.ArgumentParser(prog="tool")
    parser.add_argument("--pair", nargs=2)
    parser.add_argument("--batch", action="append", nargs=2)
    command = introspect_parser(parser)
    form = FormState(command)
    form.set_value("pair", ["left side", "right"])
    form.set_value("batch", [["one", "two"], ["three", "four"]])

    argv = form.build_argv(executable=["tool"])[1:]

    assert argv == [
        "--pair",
        "left side",
        "right",
        "--batch",
        "one",
        "two",
        "--batch",
        "three",
        "four",
    ]
    assert vars(parser.parse_args(argv)) == {
        "pair": ["left side", "right"],
        "batch": [["one", "two"], ["three", "four"]],
    }


def test_append_nargs_default_is_not_emitted_twice():
    parser = argparse.ArgumentParser(prog="tool")
    parser.add_argument("--tag", action="append", default=["base"])
    command = introspect_parser(parser)
    form = FormState(command)
    form.set_value("tag", ["base", "extra"])

    argv = form.build_argv(executable=["tool"])[1:]

    assert argv == ["--tag", "extra"]
    assert parser.parse_args(argv).tag == ["base", "extra"]


def test_copy_matching_form_values_filters_choices():
    from cli_tui.state import copy_matching_form_values

    # Source parser accepts 'all'
    src_parser = argparse.ArgumentParser(prog="src")
    src_parser.add_argument("-f", "--format", nargs="+", choices=("auto", "webp", "all"))
    src_parser.add_argument("-m", "--mode", choices=("lossless", "lossy", "both"))

    # Target parser does NOT accept 'all' or 'both'
    tgt_parser = argparse.ArgumentParser(prog="tgt")
    tgt_parser.add_argument("-f", "--format", nargs="+", choices=("auto", "webp"))
    tgt_parser.add_argument("-m", "--mode", choices=("lossless", "lossy"))

    src_form = FormState(introspect_parser(src_parser))
    src_form.set_value("format", ["all", "auto"])
    src_form.set_value("mode", "both")

    tgt_form = FormState(introspect_parser(tgt_parser))
    copied = copy_matching_form_values(src_form, tgt_form)

    # 'all' was stripped, 'auto' was kept
    assert tgt_form.get_value("format") == ["auto"]
    # 'both' is not in target choices, so mode was not copied
    assert tgt_form.get_value("mode") is None
    assert copied == 1

