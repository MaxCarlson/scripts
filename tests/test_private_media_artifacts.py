from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_runtime_state_paths_are_ignored_even_if_recreated():
    paths = [
        "modules/video_dataset_tools/copy_state.json",
        "modules/ytaedl/urlscan-latest.json",
        "modules/ytaedl/logs/urlscan-latest.json",
    ]
    for path in paths:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-v", "--", path],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_private_media_sources_are_absent_but_generic_modules_remain():
    for relative in ("modules/mangadl", "modules/ytaedl", "modules/aebndl_module"):
        assert not (ROOT / relative).exists()
    for relative in ("modules/video_dataset_tools", "modules/kavita", "modules/compresser", "modules/procparsers", "modules/url_file_tools"):
        assert (ROOT / relative).is_dir()


def test_runtime_state_files_are_not_tracked():
    result = subprocess.run(
        ["git", "ls-files", "--", "modules/video_dataset_tools/copy_state.json", "modules/ytaedl/urlscan-latest.json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == ""
