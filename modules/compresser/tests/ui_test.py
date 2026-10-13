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
    assert "2/8 image-strategy trials" in lines[-1]
    assert "00:00:05" in lines[4]
    clock[0] = 110
    dash.update(1, result)
    lines = dash._lines()
    bars = [line for line in lines if line.startswith(("Gallery  ", "Stage    ", "Overall  "))]
    assert len(bars) == 3
    assert len({line.index("[") for line in bars}) == 1
    assert "Kept original" in lines[2]
    dash.begin_stage(3)
    dash.update(2, result)
    assert "Stages 4/4 complete" in dash._lines()[0]
    assert "8/8 image-strategy trials" in dash._lines()[-1]
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

        def close(self):
            events.append("closed")

    class Engine:
        def compress_batch(self, *args, **kwargs):
            raise RuntimeError("test failure")

    monkeypatch.setattr(cli, "CompresserDashboard", Dashboard)
    with pytest.raises(RuntimeError, match="test failure"):
        cli.run_comparison([], Engine())
    assert events == ["created", 0, "closed"]
