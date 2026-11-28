from __future__ import annotations

import io
import sys
from unittest.mock import patch

import pytest

from pyscripts import flatten


def test_flattens_lines_as_csv_with_minimal_quoting(capsys):
    with patch.object(sys, "stdin", io.StringIO('a.txt\nb,part.txt\n"quoted"\n')):
        assert flatten.main([]) == 0
    assert capsys.readouterr().out == 'a.txt,"b,part.txt","""quoted"""\n'


def test_custom_delimiter_and_quote_modes(capsys):
    with patch.object(sys, "stdin", io.StringIO("a|b\nc\n")):
        assert flatten.main(["-d", "|"]) == 0
    assert capsys.readouterr().out == '"a|b"|c\n'

    with patch.object(sys, "stdin", io.StringIO("a\nb\n")):
        assert flatten.main(["-q", "all"]) == 0
    assert capsys.readouterr().out == '"a","b"\n'


def test_no_quote_mode_escapes_delimiter_and_quote(capsys):
    with patch.object(sys, "stdin", io.StringIO('a,b\n"c"\n')):
        assert flatten.main(["-q", "none"]) == 0
    assert capsys.readouterr().out == 'a\\,b,\\"c\\"\n'


def test_null_input_and_no_trailing_newline(capsys):
    with patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"one\0two\0"), encoding="utf-8")):
        assert flatten.main(["-0", "-n"]) == 0
    assert capsys.readouterr().out == "one,two"


def test_blank_lines_are_omitted_and_nul_records_keep_embedded_newlines(capsys):
    with patch.object(sys, "stdin", io.StringIO("\na\n\n")):
        assert flatten.main([]) == 0
    assert capsys.readouterr().out == "a\n"

    with patch.object(sys, "stdin", io.StringIO("first\nline\0second\0")):
        assert flatten.main(["-0"]) == 0
    assert capsys.readouterr().out == '"first\nline",second\n'


def test_command_wrapper_flattens_stdout_and_preserves_status(capsys):
    completed = type("Completed", (), {"stdout": "a\nb\n", "returncode": 7, "stderr": "problem"})()
    with patch.object(flatten.subprocess, "run", return_value=completed) as run:
        assert flatten.main(["--", "fake-command", "arg"]) == 7
    run.assert_called_once()
    assert capsys.readouterr().out == "a,b\n"


@pytest.mark.parametrize("args", [["-d", "::"], ["-d", ""]])
def test_delimiter_must_be_one_character(args, capsys):
    with patch.object(sys, "stdin", io.StringIO("a\n")):
        with pytest.raises(SystemExit) as exc:
            flatten.main(args)
    assert exc.value.code == 2
    assert capsys.readouterr().err
