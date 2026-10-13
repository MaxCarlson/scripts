import io
import threading
from concurrent.futures import CancelledError

import pytest
from PIL import Image

from compresser import CompressionEngine, CompressionStrategy, scan_directory
from compresser.cancellation import cancellation_scope, check_cancelled
from compresser.perceptual import find_optimal_quality


def test_stop_between_perceptual_candidates():
    event = threading.Event()
    calls = []

    def encode(image, quality):
        calls.append(quality)
        event.set()
        return b"unused"

    with cancellation_scope(event), pytest.raises(CancelledError):
        find_optimal_quality(Image.new("RGB", (30, 30)), encode, lambda data: Image.open(io.BytesIO(data)), 0.990)
    assert calls == [60]


def test_ctrl_c_stops_new_jobs_and_publication(tmp_path, monkeypatch):
    import compresser.engine as module
    from compresser.transactions import managed_write_guard

    (tmp_path / ".mangadl").mkdir()
    for number in range(3):
        Image.new("RGB", (40, 40)).save(tmp_path / f"{number}.png")
    before = {path.name: path.read_bytes() for path in tmp_path.glob("*.png")}
    _, images = scan_directory(tmp_path)
    engine = CompressionEngine()
    started, release = threading.Event(), threading.Event()
    calls = []
    notices = []

    def encode(*args):
        calls.append("encode")
        started.set()
        assert release.wait(5)
        check_cancelled()
        pytest.fail("Cancelled worker reached encoding completion")

    def interrupted_wait(*args, **kwargs):
        assert started.wait(5)
        raise KeyboardInterrupt

    def notify(active):
        notices.append(active)
        release.set()

    monkeypatch.setattr(engine, "_encode_verified", encode)
    monkeypatch.setattr(module, "wait", interrupted_wait)
    with pytest.raises(KeyboardInterrupt):
        engine.compress_batch(
            images, CompressionStrategy("test", format="png"), write_mode=True, threads=1, cancellation_callback=notify
        )
    assert calls == ["encode"] and notices == [1]
    assert before == {path.name: path.read_bytes() for path in tmp_path.glob("*.png")}
    assert not (tmp_path / ".compress.lock").exists()
    # Ownership is released only after the active worker has stopped.
    with managed_write_guard([tmp_path]):
        pass


def test_cli_interrupt_returns_130(tmp_path, monkeypatch, capsys):
    from compresser.cli import main

    Image.new("RGB", (30, 30)).save(tmp_path / "001.png")

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(CompressionEngine, "compress_batch", interrupt)
    assert main(["-i", str(tmp_path), "-N", "-J"]) == 130
    output = capsys.readouterr()
    assert output.out == "" and "Cancelled" in output.err
