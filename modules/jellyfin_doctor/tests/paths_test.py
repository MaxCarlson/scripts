from __future__ import annotations

import time
from pathlib import Path

from jellyfin_doctor.paths import DEFAULT_SERVER_DIR, JellyfinPaths, latest_log, resolve_log_file


def test_default_windows_paths_are_native_jellyfin_defaults() -> None:
    paths = JellyfinPaths()
    assert paths.server_dir == DEFAULT_SERVER_DIR
    assert str(paths.data_dir).endswith("Jellyfin\\Server\\data")
    assert str(paths.tray_exe).endswith("Jellyfin.Windows.Tray.exe")


def test_server_override_derives_child_paths(work_tmp: Path) -> None:
    paths = JellyfinPaths.from_overrides(server_dir=work_tmp)
    assert paths.data_dir == work_tmp / "data"
    assert paths.config_dir == work_tmp / "config"
    assert paths.log_dir == work_tmp / "log"


def test_latest_log_selects_newest_log_file(work_tmp: Path) -> None:
    older = work_tmp / "log_20260509_001.log"
    newer = work_tmp / "log_20260509_002.log"
    older.write_text("old", encoding="utf-8")
    time.sleep(0.01)
    newer.write_text("new", encoding="utf-8")
    assert latest_log(work_tmp) == newer
    assert resolve_log_file(log_dir=work_tmp) == newer


