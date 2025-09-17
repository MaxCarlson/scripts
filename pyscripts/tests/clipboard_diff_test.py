# tests/clipboard_diff_test.py
from __future__ import annotations

import os
import re
import sys
import types
import importlib.util
import json
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPT_PATH = ROOT / "clipboard_diff.py"

ANSI_ESCAPE_REGEX = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi(s: str) -> str:
    return ANSI_ESCAPE_REGEX.sub('', s)

def normalize_for_assertion(raw_text: str) -> str:
    s = strip_ansi(raw_text).replace('\n', ' ')
    return " ".join(s.split()).strip()

@pytest.fixture
def tmp_state_dir(tmp_path, monkeypatch):
    d = tmp_path / "state"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLIPBOARD_TOOLS_STATE_DIR", str(d))
    return d

@pytest.fixture
def load_clipboard_diff(monkeypatch):
    """
    Inject a fake cross_platform.clipboard_utils with set/get.
    Return (module, set_clip func).
    """
    # Minimal package skeleton
    if 'cross_platform' not in sys.modules:
        sys.modules['cross_platform'] = types.ModuleType('cross_platform')
        sys.modules['cross_platform'].__path__ = [str(ROOT / 'cross_platform')]

    # Fake clipboard module
    last_clip = {'text': ""}

    cl_name = 'cross_platform.clipboard_utils'
    cl_mod = types.ModuleType(cl_name)
    def _get(): return last_clip['text']
    def _set(t: str): last_clip['text'] = t
    cl_mod.set_clipboard = _set
    cl_mod.get_clipboard = _get
    sys.modules[cl_name] = cl_mod

    # Load target module fresh
    spec = importlib.util.spec_from_file_location("clipboard_diff", str(SCRIPT_PATH))
    assert spec and spec.loader, f"Cannot load module from {SCRIPT_PATH}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clipboard_diff"] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod, _set

def _has_marker(norm_out: str, marker: str, text: str) -> bool:
    # Allow either "-B" or "- B" etc.
    return (f"{marker}{text}" in norm_out) or (f"{marker} {text}" in norm_out)

def test_diff_no_changes_shows_no_differences_and_stats(load_clipboard_diff, tmp_path, tmp_state_dir, capsys):
    clipboard_diff, set_clip = load_clipboard_diff
    content = "L1\nL2\n"
    f = tmp_path / "same.txt"
    f.write_text(content, encoding="utf-8")
    set_clip(content)

    with pytest.raises(SystemExit) as e:
        clipboard_diff.diff_clipboard_with_file(str(f), context_lines=3, similarity_threshold=0.75, loc_diff_warning_threshold=50, no_stats=False)
    assert e.value.code == 0

    out = capsys.readouterr().out
    norm = normalize_for_assertion(out)
    assert "No differences found between file and clipboard." in out
    assert "Differences Found" in norm and "No" in norm
    # Snapshot files exist
    meta = tmp_state_dir / "last_cld.json"
    data = tmp_state_dir / "last_cld_clipboard.txt"
    assert meta.is_file() and data.is_file()

def test_diff_detects_changes_and_similarity_and_loc_warn(load_clipboard_diff, tmp_path, tmp_state_dir, capsys):
    clipboard_diff, set_clip = load_clipboard_diff
    f = tmp_path / "file.txt"
    f.write_text("A\nB\nC\n", encoding="utf-8")
    set_clip("A\nX\nC\nEXTRA\n")

    with pytest.raises(SystemExit) as e:
        clipboard_diff.diff_clipboard_with_file(
            str(f),
            context_lines=2,
            similarity_threshold=0.99,
            loc_diff_warning_threshold=0,
            no_stats=False
        )
    assert e.value.code == 0

    out = capsys.readouterr().out
    norm_out = normalize_for_assertion(out)

    # Unified diff shows removed B and added X and EXTRA (accept either with or without space)
    assert _has_marker(norm_out, "-", "B")
    assert _has_marker(norm_out, "+", "X")
    assert _has_marker(norm_out, "+", "EXTRA")

    # Stats lines
    assert "LOC Difference" in norm_out
    assert "Dissimilarity Note" in norm_out

    # Snapshot files exist and meta points to clipboard file
    meta_path = tmp_state_dir / "last_cld.json"
    data_path = tmp_state_dir / "last_cld_clipboard.txt"
    assert meta_path.is_file() and data_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert Path(meta["clipboard_file"]).name == "last_cld_clipboard.txt"

def test_missing_file_is_error(load_clipboard_diff, tmp_state_dir, capsys):
    clipboard_diff, set_clip = load_clipboard_diff
    set_clip("something")

    with pytest.raises(SystemExit) as e:
        clipboard_diff.diff_clipboard_with_file("not_there.txt", 3, 0.75, 50, False)
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "Could not read file" in err

def test_empty_clipboard_is_error(load_clipboard_diff, tmp_path, tmp_state_dir, capsys):
    clipboard_diff, set_clip = load_clipboard_diff
    f = tmp_path / "f.txt"
    f.write_text("hello\n", encoding="utf-8")
    set_clip("  \n\t ")

    with pytest.raises(SystemExit) as e:
        clipboard_diff.diff_clipboard_with_file(str(f), 3, 0.75, 50, False)
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "Clipboard is empty" in err

def test_no_stats_suppresses_table(load_clipboard_diff, tmp_path, tmp_state_dir, capsys):
    clipboard_diff, set_clip = load_clipboard_diff
    f = tmp_path / "f2.txt"
    f.write_text("X\n", encoding="utf-8")
    set_clip("Y\n")

    with pytest.raises(SystemExit) as e:
        clipboard_diff.diff_clipboard_with_file(str(f), 3, 0.75, 50, True)
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "clipboard_diff.py Statistics" not in out
