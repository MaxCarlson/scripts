from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from clipboard_tools import compare, entrypoints
from pyscripts import clipboard_diff as cld
from pyscripts import copy_to_clipboard as c2c


def test_compare_texts_strict_vs_normalized_eol_and_trailing_newline():
    file_text = "alpha\r\nbeta\r\n"
    clip_text = "alpha\nbeta"

    strict_res = compare.compare_texts(file_text, clip_text, strict=True)
    assert strict_res.equal is False
    assert strict_res.exit_code == compare.EXIT_DIFFERENT
    assert strict_res.line_ending_mismatch is True
    assert strict_res.trailing_newline_mismatch is True

    norm_res = compare.compare_texts(
        file_text,
        clip_text,
        strict=False,
        ignore_trailing_newline=True,
    )
    assert norm_res.equal is True
    assert norm_res.exit_code == compare.EXIT_EQUAL


def test_compare_clipboard_to_file_empty_and_encoding_diagnostics(tmp_path: Path):
    target = tmp_path / "sample.txt"
    target.write_text("hello\n", encoding="utf-8")

    empty_res = compare.compare_clipboard_to_file(target, lambda: "   ")
    assert empty_res.equal is False
    assert empty_res.exit_code == compare.EXIT_ERROR
    assert "empty" in (empty_res.error or "").lower()

    bad_bytes = tmp_path / "binary.bin"
    bad_bytes.write_bytes(b"\xff\xfe\xfd")
    enc_res = compare.compare_clipboard_to_file(bad_bytes, lambda: "hello", encoding="utf-8")
    assert enc_res.equal is False
    assert enc_res.exit_code == compare.EXIT_ERROR
    assert "encoding error" in (enc_res.error or "").lower()


def test_cld_main_check_exit_codes(tmp_path: Path, monkeypatch):
    target = tmp_path / "doc.txt"
    target.write_bytes(b"line1\nline2\n")
    monkeypatch.setenv("CLIPBOARD_TOOLS_STATE_DIR", str(tmp_path / "state"))

    monkeypatch.setattr(cld, "get_clipboard", lambda: "line1\r\nline2\r\n")
    assert cld.main([str(target), "--check", "--no-stats"]) == 0
    assert cld.main([str(target), "--check", "--strict", "--no-stats"]) == 1

    monkeypatch.setattr(cld, "get_clipboard", lambda: "")
    assert cld.main([str(target), "--check", "--no-stats"]) == 2


def test_clipboard_diff_entrypoint_calls_cld_main(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cld", "file.txt", "--no-stats"])
    with patch("pyscripts.clipboard_diff.main", return_value=0) as mock_main:
        with pytest.raises(SystemExit) as exc:
            entrypoints.clipboard_diff_main()
        assert exc.value.code == 0
        mock_main.assert_called_once_with(["file.txt", "--no-stats"])


def test_c2c_literal_text_and_file_compatibility(tmp_path: Path, monkeypatch):
    captured: list[str] = []
    monkeypatch.setenv("CLIPBOARD_STATE_DIR", str(tmp_path / "buf"))
    monkeypatch.setattr(c2c, "set_clipboard", lambda text: captured.append(text))
    monkeypatch.setattr(c2c, "get_clipboard", lambda: captured[-1] if captured else "")

    rc_lit = entrypoints._run_copy(["-t", "hello", "world", "--no-stats"])
    assert rc_lit == 0
    assert captured[-1] == "hello world"

    f = tmp_path / "note.txt"
    f.write_text("from file\n", encoding="utf-8")
    rc_file = entrypoints._run_copy([str(f), "--no-stats"])
    assert rc_file == 0
    assert captured[-1] == "from file\n"

    rc_lit_auto = entrypoints._run_copy(["hello single literal", "--no-stats"])
    assert rc_lit_auto == 0
    assert captured[-1] == "hello single literal"

    rc_missing = entrypoints._run_copy(["-r", str(tmp_path / "missing.txt"), "--no-stats"])
    assert rc_missing == 1


def test_gcb_scb_sfcb_entrypoints(tmp_path: Path, monkeypatch):
    from pyscripts import print_clipboard as pc
    from pyscripts import replace_with_clipboard as rwc
    from pyscripts import set_clipboard_text as sct

    monkeypatch.setattr(sys, "argv", ["gcb"])
    with patch.object(pc, "print_clipboard_main", return_value=0) as mock_pc:
        with pytest.raises(SystemExit) as exc:
            entrypoints.get_clipboard_short_main()
        assert exc.value.code == 0
        assert mock_pc.call_args[0][1] is True  # no_stats=True by default

    monkeypatch.setattr(sys, "argv", ["scb", "hello literal", "-n"])
    with patch.object(sct, "main", return_value=0) as mock_sct:
        with pytest.raises(SystemExit) as exc:
            entrypoints.set_clipboard_short_main()
        assert exc.value.code == 0
        mock_sct.assert_called_once_with(["-t", "hello literal", "-n"])

    f = tmp_path / "target.txt"
    f.write_text("file body\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["scb", str(f), "-n"])
    with patch.object(entrypoints, "_run_copy", return_value=0) as mock_copy:
        with pytest.raises(SystemExit) as exc:
            entrypoints.set_clipboard_short_main()
        assert exc.value.code == 0
        mock_copy.assert_called_once_with(["-r", "--no-stats", str(f)])

    monkeypatch.setattr(sys, "argv", ["sfcb", str(f)])
    with patch.object(rwc, "replace_or_print_clipboard", return_value=0) as mock_rwc:
        with pytest.raises(SystemExit) as exc:
            entrypoints.replace_with_clipboard_main()
        assert exc.value.code == 0
        assert mock_rwc.called
