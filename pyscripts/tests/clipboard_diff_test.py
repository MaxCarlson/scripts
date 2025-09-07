import sys
import os
import json
import hashlib
import types
import pytest
from pathlib import Path

# ---------- Helpers to normalize Rich output ----------
import re
ANSI_ESCAPE_REGEX = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi_codes(s: str) -> str:
    return ANSI_ESCAPE_REGEX.sub('', s)

def normalize_for_assertion(raw_text: str) -> str:
    cleaned = strip_ansi_codes(raw_text).replace('\n', ' ')
    return " ".join(cleaned.split()).strip()

# ---------- Module import with patched clipboard ----------
@pytest.fixture
def load_clipboard_diff(monkeypatch):
    # Ensure a package stub exists
    sys.modules["cross_platform"] = types.ModuleType("cross_platform")
    # Provide a fake clipboard_utils module with a mutable get_clipboard
    fake_mod = types.ModuleType("cross_platform.clipboard_utils")
    clip_value = {"text": ""}

    def fake_get():
        return clip_value["text"]

    fake_mod.get_clipboard = fake_get
    sys.modules["cross_platform.clipboard_utils"] = fake_mod

    import importlib
    if "clipboard_diff" in sys.modules:
        del sys.modules["clipboard_diff"]
    clipboard_diff = importlib.import_module("clipboard_diff")

    # expose a setter for tests
    def set_clip(text):
        clip_value["text"] = text
    return clipboard_diff, set_clip

# ---------- Fixtures ----------
@pytest.fixture
def tmp_state_dir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLIPBOARD_STATE_DIR", str(state))
    return state

# ---------- Tests ----------
def test_no_diff_and_snapshot_saved(load_clipboard_diff, tmp_path, tmp_state_dir, capsys):
    clipboard_diff, set_clip = load_clipboard_diff
    f = tmp_path / "file.txt"
    f.write_text("A\nB\nC\n", encoding="utf-8")
    set_clip("A\nB\nC\n")

    with pytest.raises(SystemExit) as e:
        clipboard_diff.diff_clipboard_with_file(str(f), context_lines=3, similarity_threshold=0.75, loc_diff_warning_threshold=50, no_stats=False)
    assert e.value.code == 0

    out = capsys.readouterr().out
    norm_out = normalize_for_assertion(out)
    assert "No differences found between file and clipboard." in norm_out
    assert "clipboard_diff.py Statistics" in norm_out
    assert "CLD Snapshot" in norm_out
    # Snapshot files exist and are consistent
    meta = json.loads((tmp_state_dir / "last_cld.json").read_text(encoding="utf-8"))
    clip_text = (tmp_state_dir / "last_cld_clipboard.txt").read_text(encoding="utf-8")
    assert meta["file_path"].endswith("file.txt")
    assert clip_text == "A\nB\nC\n"
    assert "clipboard_sha256" in meta
    assert meta["clipboard_sha256"] == hashlib.sha256(clip_text.encode("utf-8")).hexdigest()

def test_diff_detects_changes_and_similarity_and_loc_warn(load_clipboard_diff, tmp_path, tmp_state_dir, capsys):
    clipboard_diff, set_clip = load_clipboard_diff
    f = tmp_path / "file.txt"
    f.write_text("A\nB\nC\n", encoding="utf-8")
    # Make clipboard different and longer
    set_clip("A\nX\nC\nEXTRA\n")

    # Use a very small LOC warn threshold to force a warning
    with pytest.raises(SystemExit) as e:
        clipboard_diff.diff_clipboard_with_file(str(f), context_lines=2, similarity_threshold=0.99, loc_diff_warning_threshold=0, no_stats=False)
    assert e.value.code == 0

    out = capsys.readouterr().out
    norm_out = normalize_for_assertion(out)
    # Unified diff should show -B and +X and +EXTRA
    assert "- B" in norm_out
    assert "+ X" in norm_out
    assert "+ EXTRA" in norm_out
    # Similarity note should appear because threshold is 0.99
    assert "very dissimilar" in norm_out
    # LOC warning present
    assert "Large LOC difference detected" in norm_out
    # Stats table present
    assert "clipboard_diff.py Statistics" in norm_out

def test_empty_clipboard_is_error(load_clipboard_diff, tmp_path, tmp_state_dir, capsys):
    clipboard_diff, set_clip = load_clipboard_diff
    f = tmp_path / "file.txt"
    f.write_text("X\n", encoding="utf-8")
    set_clip("")  # empty clipboard

    with pytest.raises(SystemExit) as e:
        clipboard_diff.diff_clipboard_with_file(str(f), context_lines=3, similarity_threshold=0.5, loc_diff_warning_threshold=50, no_stats=False)
    assert e.value.code == 1

    out = capsys.readouterr()
    # Error message to stderr
    assert "CRITICAL WARNING" in out.err
    # Stats on stdout mention empty
    assert "Empty or whitespace" in out.out
    # No snapshot should be created
    assert not (tmp_state_dir / "last_cld.json").exists()

def test_no_stats_suppresses_table(load_clipboard_diff, tmp_path, tmp_state_dir, capsys):
    clipboard_diff, set_clip = load_clipboard_diff
    f = tmp_path / "file.txt"
    f.write_text("Z\n", encoding="utf-8")
    set_clip("Q\n")

    with pytest.raises(SystemExit) as e:
        clipboard_diff.diff_clipboard_with_file(str(f), context_lines=1, similarity_threshold=0.0, loc_diff_warning_threshold=9999, no_stats=True)
    assert e.value.code in (0, 1)  # depending on content, but no table either way

    out = capsys.readouterr().out
    assert "clipboard_diff.py Statistics" not in out
