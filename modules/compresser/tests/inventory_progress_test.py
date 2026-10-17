"""Logical gallery completion, not discovered-file prefixes, drives overall progress."""

import io
from pathlib import Path
import re
import threading

import pytest
from PIL import Image

from compresser.inventory_ui import InventoryProgress


def _progress(root: Path):
    return InventoryProgress(root, enabled=True, interactive=False, stream=io.StringIO())


def test_completed_gallery_count_and_eta_ignore_newly_started_gallery(tmp_path, monkeypatch):
    import compresser.inventory_ui as module

    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    progress = _progress(tmp_path)
    progress.set_folder_total(1107)
    for index in range(43):
        gallery = tmp_path / str(index)
        progress.start_gallery(gallery, total_files=1)
        progress.advance_file(gallery / "chapter" / "01.png", gallery_key=gallery)
        clock[0] = 24 * (index + 1) / 43
        progress.finish_gallery(gallery)
    progress.start_gallery(tmp_path / "44", total_files=30)
    state = progress.snapshot()
    assert state["completed_galleries"] == 43
    assert state["overall_percent"] == pytest.approx(3.88437, rel=1e-5)
    assert state["eta_seconds"] == pytest.approx(594, abs=1)
    lines = "\n".join(progress._lines())
    assert "43/1,107" in lines and "3.9%" in lines
    assert "estimated" in lines
    progress.close()


def test_nested_chapters_and_out_of_order_workers_preserve_active_gallery(tmp_path):
    progress = _progress(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    progress.set_folder_total(2)
    progress.start_gallery(a, total_files=2)
    progress.start_gallery(b, total_files=1)
    progress.advance_file(a / "chapter1" / "01.png", gallery_key=a)
    progress.advance_file(b / "01.png", gallery_key=b)
    progress.finish_gallery(b)
    state = progress.snapshot()
    assert state["active_gallery"] == str(a)
    assert state["current_files_done"] == 1 and state["current_files_total"] == 2
    assert state["current_percent"] == 50
    assert state["completed_galleries"] == 1
    progress.advance_file(a / "chapter2" / "02.png", gallery_key=a)
    assert progress.snapshot()["completed_galleries"] == 1
    progress.finish_gallery(a)
    progress.finish_gallery(a)
    assert progress.snapshot()["completed_galleries"] == 2
    assert progress.snapshot()["overall_percent"] == 100
    assert progress.snapshot()["eta_seconds"] == 0
    progress.close()


def test_unknown_population_and_errors_do_not_fabricate_completion(tmp_path):
    progress = _progress(tmp_path)
    a = tmp_path / "a"
    progress.start_gallery(a)
    progress.advance_file(a / "01.png", gallery_key=a, unreadable=True)
    assert progress.snapshot()["overall_percent"] is None
    assert progress.snapshot()["eta_seconds"] is None
    progress.finish_gallery(a, status="complete_with_errors")
    progress.set_folder_total(2)
    assert progress.snapshot()["overall_percent"] == 50
    assert progress.snapshot()["error_galleries"] == 1
    assert progress.snapshot()["eta_seconds"] is None
    assert "unknown" in "\n".join(progress._lines()).lower()
    progress.start_gallery(tmp_path / "empty", total_files=0)
    progress.finish_gallery(tmp_path / "empty")
    assert progress.snapshot()["completed_galleries"] == 2
    progress.set_folder_total(3)  # Discovery found more work, not already completed.
    assert progress.snapshot()["overall_percent"] == pytest.approx(200 / 3)
    progress.close()


def test_parallel_events_and_render_snapshots_are_consistent(tmp_path):
    progress = _progress(tmp_path)
    progress.set_folder_total(4)
    failures = []

    def work(index):
        try:
            gallery = tmp_path / str(index)
            progress.start_gallery(gallery, total_files=30)
            for page in range(30):
                progress.advance_file(gallery / f"{page}.png", gallery_key=gallery)
                state = progress.snapshot()
                assert 0 <= state["current_files_done"] <= (state["current_files_total"] or 30)
                progress._lines()
            progress.finish_gallery(gallery)
        except Exception as error:
            failures.append(error)

    threads = [threading.Thread(target=work, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert failures == []
    state = progress.snapshot()
    assert state["files_done"] == 120 and state["completed_galleries"] == 4
    progress.close()


def test_header_scanner_groups_nested_chapters_and_counts_only_finished_galleries(tmp_path):
    from compresser.scanner import scan_directory

    for name in ("a/ch1", "a/ch2", "b/ch1"):
        folder = tmp_path / name
        folder.mkdir(parents=True)
        Image.new("RGB", (40, 40)).save(folder / "01.png")
    progress = _progress(tmp_path)
    try:
        scan_directory(tmp_path, progress=progress)
        state = progress.snapshot()
        assert state["completed_galleries"] == 2
        assert state["total_galleries"] == 2
        assert state["files_done"] == 3
        assert state["overall_percent"] == 100
    finally:
        progress.close()


def test_file_only_scan_preserves_logical_gallery_ownership(tmp_path):
    from compresser.file_inventory import scan_file_inventory

    root = tmp_path / "library"
    for name in ("a/ch1", "a/ch2", "b/ch1", "empty"):
        folder = root / name
        folder.mkdir(parents=True)
        if name != "empty":
            (folder / "01.jpg").write_bytes(b"candidate only")
    progress = _progress(root)
    try:
        scan_file_inventory(root, tmp_path / "inventory.sqlite3", progress=progress)
        state = progress.snapshot()
        assert state["completed_galleries"] == 3
        assert state["total_galleries"] == 3
        assert state["files_done"] == 3
        assert state["overall_percent"] == 100
    finally:
        progress.close()


def test_unknown_work_does_not_render_zero_percent(tmp_path):
    progress = _progress(tmp_path)
    progress.start_gallery(tmp_path / "gallery")
    lines = progress._lines()
    assert "unknown" in lines[1] and "0%" not in lines[1]
    assert "unknown" in lines[2] and "0%" not in lines[2]
    progress.close()


def test_real_renderer_handles_narrow_cjk_gallery_and_redraw(tmp_path, monkeypatch):
    from termdash.table import _strip_ansi, _visible_len

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.delenv("TERM", raising=False)
    stream = Terminal()
    progress = InventoryProgress(tmp_path, stream=stream)
    monkeypatch.setattr(progress.block, "_width", lambda: 38)
    try:
        gallery = tmp_path / ("漫画" * 40)
        progress.set_folder_total(1)
        progress.start_gallery(gallery, total_files=2)
        progress.advance_file(gallery / "01.png", gallery_key=gallery)
        stream.seek(0)
        stream.truncate()
        progress._maybe_render(force=True)
        assert "50%" in _strip_ansi(stream.getvalue())
        assert "\x1b[" in stream.getvalue()
        plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stream.getvalue())
        assert all(_visible_len(line) <= 38 for line in plain.splitlines())
        progress.finish_gallery(gallery, status="failed")
        assert progress.snapshot()["error_galleries"] == 1
    finally:
        progress.close()
        progress.close()
    assert not progress.block._thread.is_alive()


def test_live_extension_stats_tracked_and_rendered(tmp_path):
    progress = _progress(tmp_path)
    try:
        gallery = tmp_path / "gallery"
        progress.start_gallery(gallery, total_files=3)
        progress.advance_file(gallery / "01.jpg", size_bytes=1000, gallery_key=gallery)
        progress.advance_file(gallery / "02.webp", size_bytes=500, gallery_key=gallery)
        progress.advance_file(gallery / "03.jpg", size_bytes=2000, gallery_key=gallery)
        state = progress.snapshot()
        assert "formats" in state
        assert state["formats"][".jpg"]["files"] == 2
        assert state["formats"][".jpg"]["bytes"] == 3000
        assert state["formats"][".webp"]["files"] == 1
        assert state["formats"][".webp"]["bytes"] == 500
        lines = "\n".join(progress._lines())
        assert "DISCOVERED ASSETS (LIVE)" in lines
        assert ".jpg" in lines
        assert ".webp" in lines
        assert "PHASE 1/2: INVENTORY DISCOVERY" in lines
    finally:
        progress.close()

