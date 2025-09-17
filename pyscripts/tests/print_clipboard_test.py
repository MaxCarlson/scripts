# File: tests/print_clipboard_test.py
"""
Pytest for print_clipboard.py.

We avoid importing the real cross_platform.clipboard_utils by inserting a fake
module into sys.modules BEFORE loading the script. This makes tests deterministic
and independent of platform clipboard availability.
"""
from __future__ import annotations

import types
import sys
from pathlib import Path
import importlib.util
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # script lives one level above tests
SCRIPT_PATH = ROOT / "print_clipboard.py"


def _load_script_with_fake_clipboard(clipboard_text: str | None):
    """
    Inject a fake cross_platform.clipboard_utils into sys.modules and then import the script.
    """
    fake_mod = types.ModuleType("cross_platform.clipboard_utils")

    def fake_get_clipboard():
        return clipboard_text

    setattr(fake_mod, "get_clipboard", fake_get_clipboard)

    sys.modules["cross_platform"] = types.ModuleType("cross_platform")  # package stub
    sys.modules["cross_platform.clipboard_utils"] = fake_mod

    spec = importlib.util.spec_from_file_location("print_clipboard", SCRIPT_PATH)
    assert spec and spec.loader, f"Cannot load module from {SCRIPT_PATH}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["print_clipboard"] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def test_prints_plain_text_and_stats_by_default(capsys):
    mod = _load_script_with_fake_clipboard("Hello\nWorld")
    exit_code = mod.print_clipboard_main(color_style="none", no_stats=False)
    captured = capsys.readouterr()
    assert exit_code == 0
    # Clipboard content should be present verbatim
    assert "Hello" in captured.out and "World" in captured.out
    # Stats table should appear
    assert "print_clipboard.py Statistics" in captured.out
    assert "Non-empty" in captured.out


def test_color_option_still_prints_content(capsys):
    mod = _load_script_with_fake_clipboard("Colored\nText")
    exit_code = mod.print_clipboard_main(color_style="green", no_stats=False)
    captured = capsys.readouterr()
    assert exit_code == 0
    # Content should be present; we don't assert ANSI codes, only presence of text
    assert "Colored" in captured.out and "Text" in captured.out
    # Stats present
    assert "print_clipboard.py Statistics" in captured.out


def test_no_stats_suppresses_table(capsys):
    mod = _load_script_with_fake_clipboard("Just text")
    exit_code = mod.print_clipboard_main(color_style="none", no_stats=True)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Just text" in captured.out
    assert "print_clipboard.py Statistics" not in captured.out


def test_empty_clipboard_is_error(capsys):
    mod = _load_script_with_fake_clipboard("")
    exit_code = mod.print_clipboard_main(color_style="none", no_stats=False)
    captured = capsys.readouterr()
    # Error goes to stderr (message), stats to stdout
    assert exit_code == 1
    assert "whitespace" in captured.err.lower() or "empty" in captured.err.lower()
    assert "print_clipboard.py Statistics" in captured.out
    assert "Empty/Whitespace" in captured.out


def test_whitespace_only_is_error(capsys):
    mod = _load_script_with_fake_clipboard("   \n\t  ")
    exit_code = mod.print_clipboard_main(color_style="none", no_stats=False)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "whitespace" in captured.err.lower()
    assert "Empty/Whitespace" in captured.out
