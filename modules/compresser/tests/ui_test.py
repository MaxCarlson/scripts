from pathlib import Path

from compresser.models import ImageMetadata, ImageResult
from compresser.ui import CompresserDashboard


def test_comparison_progress_never_resets_overall(monkeypatch):
    import compresser.ui as ui

    class Block:
        interactive = True

        def __init__(self, **kwargs):
            pass

        def update(self, provider):
            pass

        def close(self):
            pass

    monkeypatch.setattr(ui, "LiveBlock", Block)
    clock = [100.0]
    monkeypatch.setattr(ui.time, "monotonic", lambda: clock[0])
    image = ImageMetadata(Path("gallery/001.jpg"), "JPEG", 40, 40, 100)
    result = ImageResult(
        image.path, image.path, 100, 100, "JPEG", "JPEG", skipped=True, skip_reason="candidate is not smaller"
    )
    dash = CompresserDashboard("png", 2, images=[image, image], stages=["png", "webp", "jpeg", "auto"])
    dash.begin_stage(0)
    clock[0] = 105
    dash.update(1, result)
    dash.update(2, result)
    dash.begin_stage(1)
    assert dash.processed == 0
    assert dash.overall_processed == 2
    assert dash.start_time == 100
    lines = dash._lines()
    assert "Stages 1/4 complete" in lines[0]
    assert "png (done)" in lines[0] and "webp (running)" in lines[0] and "auto (pending)" in lines[0]
    assert any("2/8 image-strategy trials" in line for line in lines)
    assert "00:00:05" in lines[4]
    clock[0] = 110
    dash.update(1, result)
    lines = dash._lines()
    bars = [line for line in lines if line.startswith(("Gallery  ", "Stage    ", "Trial    ", "Overall  "))]
    assert len(bars) == 4
    assert len({line.index("[") for line in bars}) == 1
    assert "Kept original" in lines[2]
    dash.begin_stage(3)
    dash.update(2, result)
    assert "Stages 4/4 complete" in dash._lines()[0]
    assert any("8/8 image-strategy trials" in line for line in dash._lines())
    dash.close()


def test_comparison_uses_one_dashboard_and_closes_on_failure(monkeypatch):
    import pytest
    import compresser.cli as cli

    events = []

    class Dashboard:
        def __init__(self, *args, **kwargs):
            events.append("created")
            assert len(kwargs["stages"]) == 4

        def begin_stage(self, index):
            events.append(index)

        def update_activity(self, event):
            pass

        def close(self):
            events.append("closed")

    class Engine:
        def compress_batch(self, *args, **kwargs):
            raise RuntimeError("test failure")

    monkeypatch.setattr(cli, "CompresserDashboard", Dashboard)
    with pytest.raises(RuntimeError, match="test failure"):
        cli.run_comparison([], Engine())
    assert events == ["created", 0, "closed"]


def test_comparison_facade_has_no_write_banner_or_quality_promises(monkeypatch, capsys):
    import shutil
    from compresser.ui import print_comparison_matrix
    from reporting_test import sample_row

    monkeypatch.setattr(shutil, "get_terminal_size", lambda *a, **k: __import__("os").terminal_size((80, 24)))
    print_comparison_matrix([sample_row()], target_path=Path("library"), workers=8)
    output = capsys.readouterr().out
    assert "COMPRESSION COMPARISON" in output
    assert "auto-lossy-q85" in output and "512.00 MiB" in output
    assert "READY TO COMPRESS" not in output
    assert "imperceptible" not in output.lower()
