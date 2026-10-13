from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from mangadl.cli import build_parser, main
from mangadl.library_guard import library_write_guard


def test_repair_manager_reentrancy_and_competing_thread(tmp_path):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    with library_write_guard(tmp_path):
        with library_write_guard(gallery):
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(_acquire, gallery)
                with pytest.raises(RuntimeError, match="locked"):
                    future.result()
    _acquire(gallery)


def _acquire(destination):
    with library_write_guard(destination):
        pass


def test_other_process_blocks_download_and_compression_then_releases(tmp_path, monkeypatch):
    from mangadl import cli_core

    child = subprocess.Popen(
        [sys.executable, "-u", "-c",
         "import sys; from pathlib import Path; from mangadl.library_guard import library_write_guard; "
         "\nwith library_write_guard(Path(sys.argv[1])):\n print('owned', flush=True); sys.stdin.read()",
         str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert child.stdout.readline().strip() == "owned"
        args = build_parser().parse_args(["run", "-d", str(tmp_path), "-u", "https://nhentai.net/g/1/", "-N"])
        monkeypatch.setattr(cli_core, "_run_owned", lambda args: 42)
        with pytest.raises(RuntimeError, match="locked"):
            cli_core._run(args)
        assert main(["compress", "-d", str(tmp_path), "-w", "-N"]) == 2
        # Dry-run bypasses ownership, and cannot launch a writer here.
        args.dry_run = True
        assert cli_core._run(args) == 42
    finally:
        child.kill()
        child.communicate(timeout=10)
    # Persistent inode survives; OS ownership does not survive process death.
    assert (tmp_path / ".mangadl" / "operation.lock").exists()
    _acquire(tmp_path)


def test_analysis_does_not_create_library_controls(tmp_path, capsys):
    from PIL import Image

    Image.new("RGB", (40, 40)).save(tmp_path / "001.png")
    assert main(["compress", "-d", str(tmp_path), "-J", "-N"]) == 0
    assert not (tmp_path / ".mangadl").exists()


def test_invalid_write_destination_is_not_created(tmp_path):
    destination = tmp_path / "missing"
    assert main(["compress", "-d", str(destination), "-w", "-N"]) == 2
    assert not destination.exists()
