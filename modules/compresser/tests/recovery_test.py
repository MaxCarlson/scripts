"""Actual process-death acceptance at each durable publication boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from cli_test_support import main
from compresser.recovery import recovery_plan, run_recovery
from compresser.transactions import JOURNAL_FILENAME, LOCK_FILENAME, directory_lock


CHILD = r"""
import io, os, sys
from pathlib import Path
from PIL import Image
import compresser.transactions as tx
directory, phase = Path(sys.argv[1]), sys.argv[2]
original = directory / ('001.webp' if phase == 'replace' else '001.jpg')
output = directory / '001.webp'
buffer = io.BytesIO()
Image.new('RGB', (32, 32), (50, 100, 150)).save(buffer, 'WEBP', lossless=True)
original_save, original_link, original_replace, original_unlink = tx._save_record, os.link, os.replace, Path.unlink
def save(*args):
    original_save(*args)
    if phase == 'prepared': os._exit(41)
def link(*args):
    original_link(*args)
    if phase == 'published': os._exit(41)
def unlink(path, *args, **kwargs):
    original_unlink(path, *args, **kwargs)
    if path == original and phase == 'removed': os._exit(41)
def replace(src, dst):
    original_replace(src, dst)
    if Path(dst) == original and phase == 'replace': os._exit(41)
tx._save_record, os.link, os.replace, Path.unlink = save, link, replace, unlink
with tx.directory_lock(directory):
    tx.publish(original, output, buffer.getvalue(), tx.digest(original), lambda p: True)
"""


@pytest.mark.parametrize(
    "phase,action",
    [
        ("prepared", "discard_unpublished_temp"),
        ("published", "finish_conversion"),
        ("removed", "clear_completed_record"),
        ("replace", "clear_completed_record"),
    ],
)
def test_process_death_is_explicitly_recoverable(tmp_path: Path, phase: str, action: str, capsys):
    source = tmp_path / ("001.webp" if phase == "replace" else "001.jpg")
    Image.new("RGB", (32, 32), (50, 100, 150)).save(source)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    child = subprocess.run(
        [sys.executable, "-c", CHILD, str(tmp_path), phase], env=env, capture_output=True, text=True, timeout=20
    )
    assert child.returncode == 41, child.stderr
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    plan = recovery_plan(tmp_path)
    assert plan["candidate"]["action"] == action
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert run_recovery(tmp_path, as_json=True) == 0
    assert json.loads(capsys.readouterr().out)["recovered"] == 0
    with pytest.raises(ValueError, match="confirmation mismatch"):
        run_recovery(tmp_path, apply=True, confirmation="wrong")
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert run_recovery(tmp_path, apply=True, confirmation=plan["confirmation_token"], as_json=True) == 0
    assert json.loads(capsys.readouterr().out)["recovered"] == 1
    assert not (tmp_path / JOURNAL_FILENAME).exists()
    assert not list(tmp_path.glob(".compress-image-*"))
    with directory_lock(tmp_path):
        pass  # Process death released OS ownership without unlinking the inode.
    retained = "001.jpg" if phase == "prepared" else "001.webp"
    assert {p.name for p in tmp_path.iterdir()} == {retained, LOCK_FILENAME}


def test_no_pending_recovery_creates_nothing(tmp_path, capsys):
    assert main(["-i", str(tmp_path), "-R", "-J"]) == 0
    assert json.loads(capsys.readouterr().out)["candidate"] is None
    assert list(tmp_path.iterdir()) == []


def test_lock_is_held_across_processes(tmp_path):
    code = "from pathlib import Path; import sys; from compresser.transactions import directory_lock\nwith directory_lock(Path(sys.argv[1])):\n print('ready', flush=True)\n sys.stdin.read(1)"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        with pytest.raises(RuntimeError, match="locked"):
            with directory_lock(tmp_path):
                pytest.fail("Second process acquired active ownership")
        child.communicate("x", timeout=10)
        assert child.returncode == 0
        with directory_lock(tmp_path):
            pass
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)
