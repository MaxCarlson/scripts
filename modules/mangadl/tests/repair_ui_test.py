import time

from mangadl.repair_ui import render_repair_progress
from mangadl.ui import visible_len


def test_repair_progress_is_colored_bounded_and_reports_counts() -> None:
    output = render_repair_progress(
        {
            "mode": "dry-run",
            "phase": "metadata",
            "started_at": time.monotonic() - 2,
            "gallery_done": 4,
            "gallery_total": 10,
            "file_total": 500,
            "expected_total": 220,
            "present_total": 218,
            "missing_total": 2,
            "conflict_total": 1,
            "current_id": "649832",
            "current_title": "A deliberately long title that must fit within the terminal",
            "message": "resolving gallery metadata",
        },
        width=80,
    )

    assert "Metadata 4/10" in output
    assert "\x1b[31mNH\x1b[0m:649832" in output
    assert "\x1b[" in output
    assert all(visible_len(line) <= 80 for line in output.splitlines())
