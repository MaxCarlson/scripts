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


def test_print_comparison_matrix_executive_summary_and_hero_banner(monkeypatch, capsys):
    import shutil
    from compresser.models import ComparisonRow
    from compresser.ui import print_comparison_matrix

    monkeypatch.setattr(shutil, "get_terminal_size", lambda *args, **kwargs: __import__("os").terminal_size((120, 24)))
    row = ComparisonRow(
        strategy_name="webp-lossy-q80",
        output_format="webp",
        mode="lossy",
        quality_display="q=80",
        compressed_bytes=700,
        original_bytes=1000,
        savings_percent=30.0,
        average_ssim=0.985,
        throughput_images_per_s=4.5,
        measured_images=10,
        saved_bytes=300,
        retained_formats=("WEBP",),
        estimate={"projected_total_saved_bytes": 30000, "approximate_95_percent_interval_bytes": [28000, 32000], "uncertainty": "Design-weighted estimate"},
    )
    print_comparison_matrix([row], target_path=Path("B:/Hent/308191"), workers=8, runner="mangadl")
    output = capsys.readouterr().out
    assert "COMPRESSION BENCHMARK RESULTS" in output
    assert "RECOMMENDED STRATEGY" in output
    assert "webp-lossy-q80" in output
    assert "Quality Badges:" in output
    assert "READY TO COMPRESS?" in output
    assert "mangadl compress -d 'B:\\Hent\\308191' -f webp -m lossy -q 80 -B auto -t 8 -w" in output or "mangadl compress -d 'B:/Hent/308191' -f webp -m lossy -q 80 -B auto -t 8 -w" in output


def test_print_comparison_matrix_sample_fallback_hero_and_responsive_table(monkeypatch, capsys):
    import shutil
    from compresser.models import ComparisonRow
    from compresser.ui import print_comparison_matrix

    monkeypatch.setattr(shutil, "get_terminal_size", lambda *args, **kwargs: __import__("os").terminal_size((80, 24)))
    # Row has positive sample savings, but estimate projection is unavailable (e.g. singleton galleries or preflight rejects)
    row = ComparisonRow(
        strategy_name="auto-lossy-q70",
        output_format="auto",
        mode="lossy",
        quality_display="q=70",
        compressed_bytes=41820000,
        original_bytes=50430000,
        savings_percent=17.1,
        average_ssim=0.971,
        throughput_images_per_s=4.7,
        measured_images=50,
        saved_bytes=8610000,
        retained_formats=("WEBP",),
        failed_count=4,
        estimate={"projected_total_saved_bytes": None, "unestimated_images": 4},
        worker_diagnostics={"requested_workers": 12, "effective_workers": 12, "limiter": "requested", "phase_seconds": {"encoding": 1.5}},
    )
    print_comparison_matrix([row], target_path=Path("B:/Hent/hent1imageperpage"), workers=12, runner="mangadl")
    output = capsys.readouterr().out
    assert "COMPRESSION BENCHMARK RESULTS" in output
    assert "RECOMMENDED STRATEGY (Sample Winner)" in output
    assert "auto-lossy-q70" in output
    assert "Whole-target projections: unavailable" in output
    assert "READY TO COMPRESS?" in output
    assert "HARDWARE & WORKER PERFORMANCE" in output
    assert "mangadl compress -d 'B:\\Hent\\hent1imageperpage' -f auto -m lossy -q 70 -B auto -t 12 -w" in output or "mangadl compress -d 'B:/Hent/hent1imageperpage' -f auto -m lossy -q 70 -B auto -t 12 -w" in output

