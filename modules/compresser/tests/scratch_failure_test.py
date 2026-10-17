"""Bound scratch I/O and retain cleanup ownership under partial failures."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError, CancelledError
import threading

import pytest
from PIL import Image

from compresser.models import ImageMetadata
from compresser.scratch import ScratchWorkspace, SCRATCH_MANIFEST


@pytest.mark.parametrize("permanent", [False, True])
def test_manifest_replace_retries_only_bounded_windows_sharing_errors(tmp_path, monkeypatch, permanent):
    import compresser.scratch as scratch

    meta = _source(tmp_path)
    original = scratch.os.replace
    calls = []

    def replace(source, target):
        calls.append(source)
        if permanent or len(calls) == 1:
            error = PermissionError("fixture Windows sharing violation")
            error.winerror = 32
            raise error
        return original(source, target)

    monkeypatch.setattr(scratch.os, "replace", replace)
    if permanent:
        with pytest.raises(PermissionError, match="sharing"):
            ScratchWorkspace(tmp_path / "scratch", meta.path.parent)
        assert len(calls) == 4
        assert not list((tmp_path / "scratch").iterdir())
    else:
        with ScratchWorkspace(tmp_path / "scratch", meta.path.parent):
            assert len(calls) == 2


def _source(tmp_path):
    source = tmp_path / "library" / "01.png"
    source.parent.mkdir()
    Image.new("RGB", (40, 40)).save(source)
    info = source.stat()
    return ImageMetadata(source, "PNG", 40, 40, info.st_size, mtime_ns=info.st_mtime_ns)


def test_oversized_scratch_input_is_rejected_before_opening_content(tmp_path, monkeypatch):
    meta = _source(tmp_path)
    with meta.path.open("ab") as file:
        file.truncate(17 * 1024**2)
    info = meta.path.stat()
    meta = ImageMetadata(meta.path, "PNG", 40, 40, info.st_size, mtime_ns=info.st_mtime_ns)
    workspace = ScratchWorkspace(tmp_path / "scratch", meta.path.parent, max_staged_bytes=16 * 1024**2)
    original = Path.open

    def no_content(path, *a, **k):
        if path == meta.path:
            pytest.fail("Oversized scratch source opened before budget rejection")
        return original(path, *a, **k)

    monkeypatch.setattr(Path, "open", no_content)
    try:
        with pytest.raises(OSError, match="budget"):
            workspace.stage_image(meta)
    finally:
        workspace.close()
    assert workspace.cleaned_up


def test_partial_disk_write_does_not_orphan_untracked_source_bytes(tmp_path, monkeypatch):
    meta = _source(tmp_path)
    workspace = ScratchWorkspace(tmp_path / "scratch", meta.path.parent)
    original = Path.open

    class FullDisk:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            self.file.__enter__()
            return self

        def __exit__(self, *args):
            return self.file.__exit__(*args)

        def write(self, data):
            self.file.write(data[:4])
            raise OSError("fixture disk full")

        def __getattr__(self, name):
            return getattr(self.file, name)

    def partial(path, *a, **k):
        file = original(path, *a, **k)
        mode = a[0] if a else k.get("mode", "r")
        if path.parent == workspace.run_dir and path.suffix == ".png" and mode in ("wb", "xb"):
            return FullDisk(file)
        return file

    monkeypatch.setattr(Path, "open", partial)
    with pytest.raises(OSError, match="disk full"):
        workspace.stage_image(meta)
    workspace.close()
    assert workspace.cleaned_up
    assert not workspace.run_dir.exists()


def test_failed_deletion_keeps_manifest_and_allows_retry(tmp_path, monkeypatch):
    meta = _source(tmp_path)
    workspace = ScratchWorkspace(tmp_path / "scratch", meta.path.parent)
    staged = workspace.stage_image(meta)
    original = Path.unlink

    def denied(path, *a, **k):
        if path == staged:
            raise PermissionError("fixture deletion denied")
        return original(path, *a, **k)

    monkeypatch.setattr(Path, "unlink", denied)
    workspace.close()
    assert not workspace.cleaned_up
    assert staged.exists() and (workspace.run_dir / SCRATCH_MANIFEST).exists()
    assert workspace.diagnostics()["cleanup_errors"]
    monkeypatch.setattr(Path, "unlink", original)
    workspace.close()
    assert workspace.cleaned_up


def test_manifest_failure_before_copy_does_not_leave_unowned_data(tmp_path, monkeypatch):
    meta = _source(tmp_path)
    workspace = ScratchWorkspace(tmp_path / "scratch", meta.path.parent)

    def failed():
        raise OSError("fixture manifest failed")

    monkeypatch.setattr(workspace, "_write_manifest", failed)
    with pytest.raises(OSError, match="manifest failed"):
        workspace.stage_image(meta)
    workspace.close()
    assert workspace.cleaned_up
    assert not workspace.run_dir.exists()


def test_source_and_copy_verification_reads_are_bounded(tmp_path, monkeypatch):
    meta = _source(tmp_path)
    workspace = ScratchWorkspace(tmp_path / "scratch", meta.path.parent)
    original = Path.open

    class BoundedReader:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            self.file.__enter__()
            return self

        def __exit__(self, *args):
            return self.file.__exit__(*args)

        def read(self, size=-1):
            assert 0 < size <= 65536
            return self.file.read(size)

    def opened(path, *a, **k):
        file = original(path, *a, **k)
        if path.suffix == ".png" and (a[0] if a else k.get("mode", "r")) == "rb":
            return BoundedReader(file)
        return file

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", opened)
        staged = workspace.stage_image(meta)
    assert staged.read_bytes() == meta.path.read_bytes()
    workspace.release_image(staged)
    workspace.close()
    assert workspace.cleaned_up


def test_concurrent_staging_respects_exact_byte_budget(tmp_path):
    meta = _source(tmp_path)
    workspace = ScratchWorkspace(tmp_path / "scratch", meta.path.parent, max_staged_bytes=meta.size_bytes)
    first = workspace.stage_image(meta)
    with ThreadPoolExecutor(1) as pool:
        second = pool.submit(workspace.stage_image, meta)
        try:
            with pytest.raises(TimeoutError):
                second.result(timeout=0.1)
        finally:
            workspace.release_image(first)
        workspace.release_image(second.result(timeout=5))
    assert workspace.peak_staged_bytes == meta.size_bytes
    workspace.close()


def test_cleanup_failure_aborts_waiting_stagers_instead_of_hanging(tmp_path, monkeypatch):
    meta = _source(tmp_path)
    workspace = ScratchWorkspace(tmp_path / "scratch", meta.path.parent, max_staged_bytes=meta.size_bytes)
    first = workspace.stage_image(meta)
    original = Path.unlink

    def denied(path, *a, **k):
        if path == first:
            raise PermissionError("fixture cleanup failed")
        return original(path, *a, **k)

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(workspace.stage_image, meta)
        try:
            monkeypatch.setattr(Path, "unlink", denied)
            workspace.release_image(first)
            with pytest.raises(OSError, match="cleanup"):
                future.result(timeout=0.5)
        finally:
            monkeypatch.setattr(Path, "unlink", original)
            workspace.release_image(first)
            workspace.close()


@pytest.mark.parametrize("mode", ["engine", "context"])
def test_engine_reports_incomplete_scratch_cleanup_as_failure(tmp_path, monkeypatch, mode):
    from compresser import CompressionEngine, CompressionStrategy

    meta = _source(tmp_path)
    original = Path.unlink

    def denied(path, *a, **k):
        if path.parent.name.startswith("compresser-scratch-") and path.suffix == ".png":
            raise PermissionError("fixture cleanup failed")
        return original(path, *a, **k)

    monkeypatch.setattr(Path, "unlink", denied)
    with pytest.raises(RuntimeError, match="cleanup"):
        if mode == "context":
            with ScratchWorkspace(tmp_path / "scratch", meta.path.parent) as workspace:
                workspace.stage_image(meta)
        else:
            CompressionEngine().compress_batch(
                [meta], CompressionStrategy("png", format="png", method=0), scratch_dir=tmp_path / "scratch"
            )


@pytest.mark.parametrize("budget", [0, -1, float("nan"), True])
def test_scratch_requires_a_positive_integer_budget(tmp_path, budget):
    (tmp_path / "library").mkdir()
    with pytest.raises(ValueError, match="budget"):
        ScratchWorkspace(tmp_path / "scratch", tmp_path / "library", max_staged_bytes=budget)


def test_replaced_run_directory_is_not_cleaned_as_if_still_owned(tmp_path):
    meta = _source(tmp_path)
    workspace = ScratchWorkspace(tmp_path / "scratch", meta.path.parent)
    staged = workspace.stage_image(meta)
    retained = workspace.run_dir.with_name(workspace.run_dir.name + "-retained")
    workspace.run_dir.rename(retained)
    workspace.run_dir.mkdir()
    bystander = workspace.run_dir / staged.name
    bystander.write_bytes(b"unrelated fixture")
    workspace.close()
    assert bystander.read_bytes() == b"unrelated fixture"
    assert not workspace.cleaned_up
    bystander.unlink()
    workspace.run_dir.rmdir()
    retained.rename(workspace.run_dir)
    workspace.close()
    assert workspace.cleaned_up


@pytest.mark.parametrize("failure", ["growth", "checksum", "cancel"])
def test_copy_failure_paths_clean_owned_artifacts(tmp_path, monkeypatch, failure):
    from compresser.cancellation import cancellation_scope

    meta = _source(tmp_path)
    workspace = ScratchWorkspace(tmp_path / "scratch", meta.path.parent)
    original = Path.open
    event = threading.Event()

    class Reader:
        def __init__(self, file, path):
            self.file, self.path, self.changed = file, path, False

        def __enter__(self):
            self.file.__enter__()
            return self

        def __exit__(self, *args):
            return self.file.__exit__(*args)

        def read(self, size):
            chunk = self.file.read(size)
            if chunk and not self.changed:
                self.changed = True
                if self.path == meta.path and failure == "growth":
                    with original(meta.path, "ab") as source:
                        source.write(b"x")
                elif self.path == meta.path and failure == "cancel":
                    event.set()
                elif self.path.parent == workspace.run_dir and failure == "checksum":
                    chunk = bytes([chunk[0] ^ 1]) + chunk[1:]
            return chunk

    def opened(path, *a, **k):
        file = original(path, *a, **k)
        return Reader(file, path) if path.suffix == ".png" and a and a[0] == "rb" else file

    monkeypatch.setattr(Path, "open", opened)
    with cancellation_scope(event):
        message = {"growth": "grew", "checksum": "verification", "cancel": "cancelled"}[failure]
        with pytest.raises((RuntimeError, OSError, CancelledError), match=message):
            workspace.stage_image(meta)
    workspace.close()
    assert workspace.cleaned_up
    assert meta.path.exists()
