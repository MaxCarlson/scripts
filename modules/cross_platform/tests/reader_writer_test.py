"""Readers and writers must coordinate on overlapping paths, not just advertise metadata."""

import os
import subprocess
import sys

import pytest

from cross_platform.locks import folder_read_lock, inspect_folder_locks


@pytest.fixture(autouse=True)
def isolated_lock_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("CROSS_PLATFORM_LOCK_DIR", str(tmp_path / "lock-state"))


@pytest.mark.parametrize("held_mode,new_mode", [("read", "write"), ("write", "read"), ("write", "write")])
@pytest.mark.parametrize("relationship", ["same", "parent", "child"])
def test_cross_process_conflicts_on_overlapping_targets(tmp_path, held_mode, new_mode, relationship):
    from cross_platform.locks import folder_write_lock

    root = tmp_path / "library"
    child = root / "gallery"
    child.mkdir(parents=True)
    held = root if relationship != "parent" else child
    target = root if relationship != "child" else child
    code = (
        "from pathlib import Path\n"
        "from cross_platform.locks import folder_read_lock,folder_write_lock\n"
        f"guard = {'folder_read_lock' if held_mode == 'read' else 'folder_write_lock'}(Path({str(held)!r}))\n"
        "with guard:\n print('READY',flush=True)\n input()\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(os.environ),
    )
    try:
        assert proc.stdout.readline().strip() == "READY"
        guard = folder_read_lock if new_mode == "read" else folder_write_lock
        with pytest.raises(RuntimeError, match="locked"):
            with guard(target):
                pytest.fail("Conflicting operation was admitted")
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    # Kernel ownership is released on death even when metadata/slot remains.
    with folder_write_lock(target):
        pass


def test_readers_coexist_and_siblings_are_independent(tmp_path):
    from cross_platform.locks import folder_write_lock

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    with folder_read_lock(a):
        with folder_read_lock(a):
            with folder_write_lock(b):
                assert inspect_folder_locks(a, discover_processes=False).read_locked
                assert inspect_folder_locks(b, discover_processes=False).write_locked
    assert list(a.iterdir()) == [] and list(b.iterdir()) == []


def test_reader_exception_releases_and_cleans_its_slot(tmp_path):
    from cross_platform.locks import folder_write_lock

    with pytest.raises(ValueError, match="fixture"):
        with folder_read_lock(tmp_path / "gallery") as slot:
            raise ValueError("fixture")
    assert not slot.exists()
    with folder_write_lock(tmp_path / "gallery"):
        pass


def test_nested_write_on_same_thread_inherits_covering_owner(tmp_path):
    from cross_platform.locks import folder_write_lock

    with folder_write_lock(tmp_path / "library") as owner:
        with folder_write_lock(tmp_path / "library" / "gallery") as child:
            assert child == owner
        with pytest.raises(RuntimeError, match="locked"):
            with folder_read_lock(tmp_path / "library"):
                pytest.fail("Nested write release accidentally released outer ownership")


def test_simultaneous_reader_writer_acquisition_admits_only_one(tmp_path):
    target = tmp_path / "gallery"
    target.mkdir()
    signal = tmp_path / "start"
    children = []
    try:
        for mode in ("read", "write"):
            code = (
                "from pathlib import Path\nimport time\n"
                "from cross_platform.locks import folder_read_lock,folder_write_lock\n"
                "print('READY',flush=True)\n"
                f"while not Path({str(signal)!r}).exists(): time.sleep(.005)\n"
                "try:\n"
                f" guard = folder_{mode}_lock(Path({str(target)!r})); guard.__enter__()\n"
                "except RuntimeError:\n print('BLOCKED',flush=True); input()\n"
                "else:\n print('ENTERED',flush=True); input(); guard.__exit__(None,None,None)\n"
            )
            children.append(
                subprocess.Popen(
                    [sys.executable, "-c", code],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        assert all(proc.stdout.readline().strip() == "READY" for proc in children)
        signal.touch()
        assert sorted(proc.stdout.readline().strip() for proc in children) == ["BLOCKED", "ENTERED"]
    finally:
        for proc in children:
            proc.terminate()
            proc.wait(timeout=5)
