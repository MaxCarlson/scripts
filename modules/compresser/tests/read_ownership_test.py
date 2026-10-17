import pytest
from PIL import Image

from cli_test_support import main
from compresser.engine import CompressionEngine
from compresser.transactions import library_write_guard


def test_reader_blocks_library_write_before_creating_controls(tmp_path, monkeypatch):
    from cross_platform.locks import folder_read_lock

    monkeypatch.setenv("CROSS_PLATFORM_LOCK_DIR", str(tmp_path / "lock-state"))
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    with folder_read_lock(gallery):
        with pytest.raises(RuntimeError, match="locked"):
            with library_write_guard(gallery):
                pytest.fail("Writer entered while reader held target")
    assert list(gallery.iterdir()) == []


def test_standalone_holds_read_ownership_during_encoder_trials(tmp_path, monkeypatch):
    monkeypatch.setenv("CROSS_PLATFORM_LOCK_DIR", str(tmp_path / "lock-state"))
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    Image.new("RGB", (40, 40)).save(gallery / "01.png")
    actual = CompressionEngine.compress_batch

    def checked(self, *a, **k):
        with pytest.raises(RuntimeError, match="locked"):
            with library_write_guard(gallery):
                pytest.fail("Standalone released read ownership before encoding")
        return actual(self, *a, **k)

    monkeypatch.setattr(CompressionEngine, "compress_batch", checked)
    assert main(["-i", str(gallery), "-f", "png", "-e", "0", "-J"]) == 0


def test_standalone_write_owns_root_before_discovery(tmp_path, monkeypatch):
    import compresser.cli as cli
    from cross_platform.locks import folder_read_lock

    monkeypatch.setenv("CROSS_PLATFORM_LOCK_DIR", str(tmp_path / "lock-state"))
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    Image.new("RGB", (40, 40)).save(gallery / "01.png")
    scan = cli.scan_directory

    def checked(*a, **k):
        with pytest.raises(RuntimeError, match="locked"):
            with folder_read_lock(gallery):
                pytest.fail("Writer did not own the root during discovery")
        return scan(*a, **k)

    monkeypatch.setattr(cli, "scan_directory", checked)
    assert main(["-i", str(gallery), "-f", "png", "-e", "0", "-w", "-J"]) == 0
