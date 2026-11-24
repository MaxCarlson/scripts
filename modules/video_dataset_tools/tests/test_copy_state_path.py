from __future__ import annotations

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("video_dataset_file_copier", Path(__file__).parents[1] / "file_copier.py")
assert SPEC and SPEC.loader
file_copier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(file_copier)


def test_default_state_path_uses_per_user_state_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(file_copier.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

    state_path = file_copier.default_state_path()

    assert state_path == tmp_path / "Local" / "video_dataset_tools" / "copy_state.json"


def test_resume_reads_legacy_cwd_file_but_writes_to_new_default(tmp_path, monkeypatch):
    monkeypatch.setattr(file_copier.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    legacy = tmp_path / "copy_state.json"
    legacy.write_text('{"copied_files": {}}', encoding="utf-8")

    read_path, write_path = file_copier.resolve_state_paths(None, cwd=tmp_path, resume=True)

    assert read_path == legacy
    assert write_path == tmp_path / "Local" / "video_dataset_tools" / "copy_state.json"
    assert not write_path.exists()


def test_explicit_state_path_is_preserved(tmp_path):
    explicit = tmp_path / "custom" / "state.json"

    assert file_copier.resolve_state_paths(explicit, cwd=tmp_path, resume=True) == (explicit, explicit)


def test_fresh_run_does_not_reuse_legacy_cwd_file(tmp_path, monkeypatch):
    monkeypatch.setattr(file_copier.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    legacy = tmp_path / "copy_state.json"
    legacy.write_text("fixture", encoding="utf-8")

    read_path, write_path = file_copier.resolve_state_paths(None, cwd=tmp_path, resume=False)

    assert read_path is None
    assert write_path == tmp_path / "Local" / "video_dataset_tools" / "copy_state.json"
