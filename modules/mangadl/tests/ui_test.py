from pathlib import Path

from mangadl.models import WorkerSnapshot
from mangadl.ui import ConsoleDashboard, human_bytes, plain_identity, read_log_lines, render_dashboard, visible_len


def test_dashboard_contains_compact_identity_rates_and_colors() -> None:
    worker = WorkerSnapshot(
        1,
        state="run",
        url="https://nhentai.net/g/123/",
        site="nhentai",
        images_done=2,
        images_total=10,
        bytes_done=2048,
        current_bps=1024,
        average_bps=512,
        current_ips=1.5,
    )
    output = render_dashboard("run", {"running": 1}, {1: worker}, width=120)
    assert "NH" in output and ":123" in output
    assert "https://nhentai.net" not in output
    assert "\x1b[31mNH\x1b[0m" in output
    assert "\x1b[32mRUN\x1b[0m" in output
    assert "1.0 KiB/s" in output
    assert "2/10" in output
    assert all(visible_len(line) <= 120 for line in output.splitlines())


def test_human_bytes_identity_and_tail(tmp_path: Path) -> None:
    assert human_bytes(1024) == "1.0 KiB"
    assert plain_identity("https://nhentai.net/g/419136/") == "NH:419136"
    log = tmp_path / "worker.log"
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")
    assert read_log_lines(log, 2) == ["two", "three"]


def test_narrow_dashboard_uses_intentional_two_row_workers() -> None:
    worker = WorkerSnapshot(1, state="run", url="https://nhentai.net/g/123/", images_done=4, bytes_done=2048)
    output = render_dashboard("run", {"running": 1}, {1: worker}, width=60)
    worker_lines = output.splitlines()[3:5]
    assert len(worker_lines) == 2
    assert all(visible_len(line) <= 60 for line in output.splitlines())


def test_log_hotkeys_toggle_inline_fullscreen_and_raw(tmp_path: Path) -> None:
    dashboard = ConsoleDashboard(True, "run", tmp_path)
    dashboard.handle_key("l", 2)
    assert dashboard.inline_log and not dashboard.fullscreen_log
    dashboard.handle_key("r", 2)
    assert dashboard.raw_view
    dashboard.handle_key("f", 2)
    assert dashboard.fullscreen_log
