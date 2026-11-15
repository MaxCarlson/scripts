from __future__ import annotations

import argparse
import curses
from pathlib import Path

from cli_tui import CliTuiApp
from cli_tui.completion import complete_path_prefix, extract_token_at_cursor
from cli_tui.schema import CliArgument
from cli_tui.widgets import TextWidget


def _setup_sample_tree(root: Path) -> Path:
    (root / "hent1imageperpage").mkdir()
    (root / "hent1imageperpage" / "urls37.txt").write_text("https://example.com\n", encoding="utf-8")
    (root / "hent1imageperpage" / "urls38.txt").write_text("https://example.com\n", encoding="utf-8")
    (root / "hent2").mkdir()
    (root / "combined_urls.txt").write_text("", encoding="utf-8")
    (root / ".hidden_dir").mkdir()
    return root


def test_complete_path_prefix_relative_dot_slash(tmp_path: Path) -> None:
    _setup_sample_tree(tmp_path)

    matches = complete_path_prefix("./", working_dir=tmp_path)
    assert matches == ["./combined_urls.txt", "./hent1imageperpage/", "./hent2/"]

    h_matches = complete_path_prefix("./h", working_dir=tmp_path)
    assert h_matches == ["./hent1imageperpage/", "./hent2/"]

    nested = complete_path_prefix("./hent1imageperpage/u", working_dir=tmp_path)
    assert nested == ["./hent1imageperpage/urls37.txt", "./hent1imageperpage/urls38.txt"]


def test_complete_path_prefix_bare_parent_and_backslash(tmp_path: Path) -> None:
    _setup_sample_tree(tmp_path)

    assert complete_path_prefix("h", working_dir=tmp_path) == [
        "hent1imageperpage/",
        "hent2/",
    ]
    assert complete_path_prefix(".\\h", working_dir=tmp_path) == [
        ".\\hent1imageperpage\\",
        ".\\hent2\\",
    ]

    sub = tmp_path / "hent1imageperpage"
    assert complete_path_prefix("../c", working_dir=sub) == ["../combined_urls.txt"]


def test_complete_path_prefix_hidden_home_and_missing(tmp_path: Path, monkeypatch) -> None:
    _setup_sample_tree(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert complete_path_prefix("./.", working_dir=tmp_path) == ["./.hidden_dir/"]
    assert complete_path_prefix("~", working_dir=tmp_path) == ["~/"]
    assert complete_path_prefix("~/h", working_dir=tmp_path) == [
        "~/hent1imageperpage/",
        "~/hent2/",
    ]
    assert complete_path_prefix("./does_not_exist/", working_dir=tmp_path) == []


def test_extract_token_at_cursor_single_vs_multi_token() -> None:
    assert extract_token_at_cursor("./my folder/u", 13, is_multi_token=False) == (
        0,
        13,
        "./my folder/u",
        None,
    )
    assert extract_token_at_cursor("./a.txt ./h", 11, is_multi_token=True) == (
        8,
        11,
        "./h",
        None,
    )
    assert extract_token_at_cursor('./a.txt "./my ', 14, is_multi_token=True) == (
        8,
        14,
        "./my ",
        '"',
    )


def test_text_widget_tab_cycles_forward_backward_and_resets(tmp_path: Path) -> None:
    _setup_sample_tree(tmp_path)
    arg = CliArgument(dest="input_file", flags=("--input-file", "-i"))
    widget = TextWidget(arg, "", working_dir=tmp_path)

    assert widget.handle_key(ord("e"))
    for ch in "./h":
        assert widget.handle_key(ord(ch))

    # Tab cycles forward through matches
    assert widget.handle_key(9)
    assert widget.value == "./hent1imageperpage/"
    assert widget.completion_status == "1/2"
    assert widget.cursor_pos == len("./hent1imageperpage/")

    assert widget.handle_key(9)
    assert widget.value == "./hent2/"
    assert widget.completion_status == "2/2"

    # Shift+Tab cycles backward
    btab = getattr(curses, "KEY_BTAB", 353)
    assert widget.handle_key(btab)
    assert widget.value == "./hent1imageperpage/"
    assert widget.completion_status == "1/2"

    # Typing resets completion session and allows completing inside the folder
    assert widget.handle_key(ord("u"))
    assert widget.completion_status == ""
    assert widget.handle_key(9)
    assert widget.value == "./hent1imageperpage/urls37.txt"
    assert widget.completion_status == "1/2"


def test_text_widget_multi_token_quotes_spaces(tmp_path: Path) -> None:
    (tmp_path / "my folder").mkdir()
    arg = CliArgument(dest="input_file", flags=("--input-file", "-i"), action_type="append")
    widget = TextWidget(arg, "./first.txt ./m", working_dir=tmp_path)
    widget.is_editing = True
    widget.cursor_pos = len(widget.value)

    assert widget.handle_key(9)
    assert widget.value == './first.txt "./my folder/"'


def test_text_widget_no_matches_status(tmp_path: Path) -> None:
    _setup_sample_tree(tmp_path)
    arg = CliArgument(dest="directory", flags=("--directory", "-d"))
    widget = TextWidget(arg, "./zzz", working_dir=tmp_path)
    widget.is_editing = True
    widget.cursor_pos = len(widget.value)

    assert widget.handle_key(9)
    assert widget.value == "./zzz"
    assert widget.completion_status == "No matches"


def test_cli_tui_app_form_tab_completion_integration(tmp_path: Path, monkeypatch) -> None:
    _setup_sample_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    parser = argparse.ArgumentParser(prog="mangadl")
    sub = parser.add_subparsers(dest="command")
    urls = sub.add_parser("urls", help="Merge URLs")
    urls.add_argument("-d", "--directory", default=".", help="Folder")
    urls.add_argument("-i", "--input-file", action="append", help="Input file")

    app = CliTuiApp(parser, layout_dir=tmp_path / "layouts")
    # Enter 'urls' form
    assert app.process_key(10)
    # Focus is on --directory (index 0); enter editing mode, clear default '.', type './h'
    assert app.process_key(10)
    assert app.process_key(21)  # Ctrl+U clears line
    for ch in "./h":
        assert app.process_key(ord(ch))

    assert app.process_key(9)  # Tab
    assert app.current_form is not None
    assert app.current_form.get_value("directory") == "./hent1imageperpage/"
    screen = "\n".join(app.render_virtual_screen(height=30, width=120))
    assert "[Tab] Complete (1/2)" in screen

    # Finish editing and move to --input-file
    assert app.process_key(10)  # Enter done
    assert app.process_key(curses.KEY_DOWN)
    assert app.process_key(10)  # Enter editing mode
    for ch in "./hent1imageperpage/u":
        assert app.process_key(ord(ch))
    assert app.process_key(9)  # Tab
    assert app.process_key(9)  # Second match
    assert app.current_form.get_value("input_file") == "./hent1imageperpage/urls38.txt"
    assert app.process_key(10)  # Enter done

    argv = app.current_form.build_argv(executable=["mangadl"])
    assert argv == [
        "mangadl",
        "urls",
        "-d",
        "./hent1imageperpage/",
        "-i",
        "./hent1imageperpage/urls38.txt",
    ]
