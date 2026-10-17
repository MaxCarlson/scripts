from PIL import Image
import pytest

from compresser import CompressionEngine, CompressionStrategy, scan_directory
from compresser.timing import phase, timing_scope


def test_nested_phases_do_not_double_count(monkeypatch):
    import compresser.timing as module

    clock = [0.0]
    monkeypatch.setattr(module.time, "perf_counter", lambda: clock[0])
    notices = []
    with timing_scope(notices.append) as trace:
        with phase("encoding"):
            clock[0] = 2
            with phase("similarity"):
                clock[0] = 5
            clock[0] = 7
    assert trace["seconds"] == {"encoding": 4, "similarity": 3}
    assert notices == ["encoding", "similarity", "encoding", "finishing"]


def test_failure_phase_and_context_cleanup(monkeypatch):
    import compresser.timing as module

    clock = [0.0]
    monkeypatch.setattr(module.time, "perf_counter", lambda: clock[0])
    with timing_scope() as trace:
        with pytest.raises(ValueError):
            with phase("verification"):
                clock[0] = 3
                raise ValueError("test failure")
    with phase("outside"):
        pass
    assert trace["seconds"] == {"verification": 3}
    assert trace["stack"] == []


def test_cached_trial_does_not_replay_old_encoder_timings(tmp_path):
    Image.new("RGB", (80, 80), (30, 50, 70)).save(tmp_path / "001.jpg")
    _, images = scan_directory(tmp_path)
    engine = CompressionEngine()
    strategy = CompressionStrategy("test", format="webp", mode="lossless")
    first = engine.compress_image(images[0], strategy)
    assert "encoding" in first.phase_seconds and "source_decode" in first.phase_seconds
    second = engine.compress_image(images[0], strategy)
    assert second.cache_hit
    assert set(second.phase_seconds) == {"cache"}


def test_narrow_reports_preserve_strategy_and_numbers(tmp_path, monkeypatch, capsys):
    import shutil
    from compresser.cli import run_comparison
    from compresser.ui import print_comparison_matrix

    Image.new("RGB", (80, 80)).save(tmp_path / "001.png")
    _, images = scan_directory(tmp_path)
    monkeypatch.setattr(shutil, "get_terminal_size", lambda *args, **kwargs: __import__("os").terminal_size((80, 24)))
    rows = run_comparison(images, CompressionEngine(), no_ui=True)
    print_comparison_matrix(rows)
    output = capsys.readouterr().out
    assert "webp-lossless" in output and "Retained:" in output
    assert "Failures:" in output and "Phase worker-seconds" in output
    assert "St…" not in output and "\x1b[" not in output
