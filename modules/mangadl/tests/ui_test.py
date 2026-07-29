from pathlib import Path

import pytest

from mangadl.models import WorkerSnapshot
from mangadl.ui import (
    ANSI_RE,
    ConsoleDashboard,
    DashboardRuntime,
    human_bytes,
    plain_identity,
    read_log_lines,
    render_dashboard,
    visible_len,
)


def test_dashboard_contains_compact_identity_rates_and_colors() -> None:
    worker = WorkerSnapshot(
        1,
        state="run",
        url="https://nhentai.net/g/123/",
        backend="gallery-dl",
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
    assert "\x1b[32mGD\x1b[0m" in output
    assert "20.0%" in output
    assert all(visible_len(line) <= 120 for line in output.splitlines())


def test_human_bytes_identity_and_tail(tmp_path: Path) -> None:
    assert human_bytes(1024) == "1.0 KiB"
    assert plain_identity("https://nhentai.net/g/419136/") == "NH:419136"
    log = tmp_path / "worker.log"
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")
    assert read_log_lines(log, 2) == ["two", "three"]


def test_narrow_dashboard_uses_two_rows_per_worker() -> None:
    worker = WorkerSnapshot(1, state="run", url="https://nhentai.net/g/123/", images_done=4, bytes_done=2048)
    output = render_dashboard("run", {"running": 1}, {1: worker}, width=60)
    plain_lines = [ANSI_RE.sub("", line) for line in output.splitlines()]
    worker_index = next(index for index, line in enumerate(plain_lines) if line.startswith(">01"))

    assert "[" in plain_lines[worker_index + 1]
    assert "activity" in plain_lines[worker_index + 1]
    assert all(visible_len(line) <= 60 for line in output.splitlines())


def test_wide_dashboard_worker_columns_align_and_show_progress_rows() -> None:
    workers = {
        1: WorkerSnapshot(
            1,
            state="run",
            url="https://manga18fx.com/manga/a-wonderful-new-world-02/",
            backend="manga18fx",
            images_done=2,
            images_total=120,
            bytes_done=2048,
            current_bps=1024,
            average_bps=512,
            current_ips=1.5,
            elapsed=9,
        ),
        2: WorkerSnapshot(
            2,
            state="retry_wait",
            url="https://manga18fx.com/manga/short/",
            backend="manga18fx",
            images_done=100,
            images_total=100,
            bytes_done=10 * 1024 * 1024,
            current_bps=2 * 1024 * 1024,
            average_bps=1536,
            current_ips=12.25,
            elapsed=3723,
        ),
    }
    runtime = DashboardRuntime(2, 4, 5, 10, 23, 24, "Worker target increased to 4.")

    output = render_dashboard("run", {"running": 2}, workers, width=180, runtime=runtime)
    plain_lines = [ANSI_RE.sub("", line) for line in output.splitlines()]
    first_rows = [line for line in plain_lines if line.startswith(">01") or line.startswith(" 02")]
    separator_positions = [
        [index for index in range(len(line)) if line.startswith(" | ", index)]
        for line in first_rows
    ]

    assert len(first_rows) == 2
    assert separator_positions[0] == separator_positions[1]
    assert all(len(line) == 180 for line in first_rows)
    assert sum("[" in line and "]" in line for line in plain_lines) >= 2
    assert "Workers 2/4" in output
    assert "Images/worker 5" in output
    assert "Active concurrency 10/23" in output
    assert "Logical CPUs 24" in output
    assert "M18" in first_rows[0]


def test_log_hotkeys_and_runtime_actions(tmp_path: Path) -> None:
    dashboard = ConsoleDashboard(True, "run", tmp_path)
    dashboard.handle_key("l", 2)
    assert dashboard.inline_log and not dashboard.fullscreen_log
    dashboard.handle_key("r", 2)
    assert dashboard.raw_view
    dashboard.handle_key("f", 2)
    assert dashboard.fullscreen_log
    assert dashboard.handle_key("+", 2) == "workers_up"
    assert dashboard.handle_key("-", 2) == "workers_down"
    assert dashboard.handle_key("]", 2) == "images_up"
    assert dashboard.handle_key("[", 2) == "images_down"


def test_quit_hotkey_uses_immediate_interrupt_path(tmp_path: Path) -> None:
    dashboard = ConsoleDashboard(True, "run", tmp_path)

    with pytest.raises(KeyboardInterrupt):
        dashboard.handle_key("q", 2)
