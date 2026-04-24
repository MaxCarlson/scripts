from __future__ import annotations

from pathlib import Path
import re
import shutil

from ytaedl import mp4_sync
from ytaedl.mp4_watcher import MP4Watcher, WatcherConfig, filter_plan_for_destination_space

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _make_config(tmp_path: Path, *, operation: str = "move") -> WatcherConfig:
    staging_root = tmp_path / "staging"
    destination_root = tmp_path / "dest"
    staging_root.mkdir(parents=True, exist_ok=True)
    destination_root.mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / "watcher.log"
    return WatcherConfig(
        staging_root=staging_root,
        destination_root=destination_root,
        log_path=log_path,
        default_operation=operation,
        max_files=None,
        keep_source=(operation == "copy"),
        total_size_trigger_bytes=None,
        free_space_trigger_bytes=None,
    )


def _read_log_text(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    return ANSI_RE.sub("", log_path.read_text(encoding="utf-8"))


def test_toggle_operation_cycles_modes(tmp_path):
    cfg = _make_config(tmp_path, operation="move")
    watcher = MP4Watcher(config=cfg, enabled=True)

    watcher.toggle_operation()
    snapshot = watcher.config_snapshot()
    assert snapshot.default_operation == "copy"
    assert snapshot.keep_source is True

    watcher.toggle_operation()
    snapshot = watcher.config_snapshot()
    assert snapshot.default_operation == "move"
    assert snapshot.keep_source is False


def test_set_max_files_normalizes_values(tmp_path):
    cfg = _make_config(tmp_path)
    watcher = MP4Watcher(config=cfg, enabled=True)

    assert watcher.set_max_files(0) is None
    assert watcher.config_snapshot().max_files is None

    assert watcher.set_max_files(15) == 15
    assert watcher.config_snapshot().max_files == 15

    assert watcher.set_max_files(-5) is None
    assert watcher.config_snapshot().max_files is None


def test_set_free_space_trigger_handles_disable_and_positive_values(tmp_path):
    cfg = _make_config(tmp_path)
    watcher = MP4Watcher(config=cfg, enabled=True)

    expected_bytes = int(12.5 * (1024**3))
    assert watcher.set_free_space_trigger_gib(12.5) == expected_bytes
    assert watcher.config_snapshot().free_space_trigger_bytes == expected_bytes

    assert watcher.set_free_space_trigger_gib(0) is None
    assert watcher.config_snapshot().free_space_trigger_bytes is None


def test_configuration_changes_emit_log_entries(tmp_path):
    cfg = _make_config(tmp_path)
    watcher = MP4Watcher(config=cfg, enabled=True)

    watcher.toggle_operation()
    watcher.set_max_files(5)
    watcher.set_free_space_trigger_gib(7.5)

    log_text = _read_log_text(cfg.log_path)
    assert "Default operation set to copy" in log_text
    assert "Max files per run set to 5" in log_text
    assert "Free-space trigger set to 7.5 GiB" in log_text


def test_set_destination_space_remaining_handles_disable_and_positive_values(tmp_path):
    cfg = _make_config(tmp_path)
    watcher = MP4Watcher(config=cfg, enabled=True)

    assert watcher.set_destination_space_remaining_bytes(100 * 1024**3) == 100 * 1024**3
    assert watcher.config_snapshot().destination_space_remaining_bytes == 100 * 1024**3

    assert watcher.set_destination_space_remaining_bytes(0) is None
    assert watcher.config_snapshot().destination_space_remaining_bytes is None


def test_destination_space_filter_caps_plan_to_available_bytes(tmp_path):
    cfg = _make_config(tmp_path)
    src_dir = cfg.staging_root / "alpha"
    src_dir.mkdir()
    (src_dir / "one.mp4").write_bytes(b"1" * 10)
    (src_dir / "two.mp4").write_bytes(b"2" * 10)

    plan, _ = mp4_sync.build_plan(cfg.staging_root, cfg.destination_root, "move")
    filtered, selected_count, skipped_count = filter_plan_for_destination_space(plan, mp4_sync, 10)

    file_actions = [action for action in filtered.actions if action.action != mp4_sync.ACTION_CREATE_DIR]
    assert selected_count == 1
    assert skipped_count == 1
    assert len(file_actions) == 1
    assert sum(action.source_size or 0 for action in file_actions) == 10


def test_destination_space_block_sets_no_space_snapshot(monkeypatch, tmp_path):
    cfg = _make_config(tmp_path)
    cfg.destination_space_remaining_bytes = 1_000
    src_dir = cfg.staging_root / "alpha"
    src_dir.mkdir()
    (src_dir / "one.mp4").write_bytes(b"1" * 10)
    watcher = MP4Watcher(config=cfg, enabled=True)

    usage = shutil._ntuple_diskusage(total=2_000, used=1_900, free=100)
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: usage)

    watcher._run("move", False, "test", None)
    snapshot = watcher.snapshot()

    assert snapshot.destination_no_space is True
    assert snapshot.destination_space_message == "NO DISK SPACE LEFT AT FINAL DESTINATION"
    assert (cfg.destination_root / "alpha" / "one.mp4").exists() is False
