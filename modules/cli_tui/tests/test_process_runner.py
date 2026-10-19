from __future__ import annotations

import sys
from cli_tui.process_runner import OutputViewport, ProcessRunner


def test_process_runner_lifecycle_and_output():
    # Run a simple python one-liner that prints lines with flush
    script = (
        "import sys, time\n"
        "for i in range(5):\n"
        "    print(f'Line {i}', flush=True)\n"
        "    time.sleep(0.01)\n"
    )
    runner = ProcessRunner([sys.executable, "-c", script])
    runner.start()

    assert runner.is_running is True

    runner.wait(timeout=5.0)

    assert runner.is_running is False
    assert runner.exit_code == 0
    assert any("Line 0" in line for line in runner.lines)
    assert any("Line 4" in line for line in runner.lines)
    assert runner.elapsed_seconds > 0


def test_process_runner_termination():
    # Long-running process
    script = "import time\ntime.sleep(60)\n"
    runner = ProcessRunner([sys.executable, "-c", script])
    runner.start()

    assert runner.is_running is True
    runner.terminate()
    runner.wait(timeout=5.0)

    assert runner.is_running is False
    assert runner.exit_code is not None


def test_output_viewport_scrolling():
    viewport = OutputViewport()
    lines = [f"Line {i:03d}" for i in range(100)]

    # Initial state auto-scrolls to bottom
    assert viewport.auto_scroll is True
    visible = viewport.get_visible_lines(lines, height=10, width=40)
    assert len(visible) == 10
    assert visible[-1].strip() == "Line 099"
    assert visible[0].strip() == "Line 090"

    # Scroll up 5 lines
    viewport.scroll_up(5)
    assert viewport.auto_scroll is False
    visible = viewport.get_visible_lines(lines, height=10, width=40)
    assert visible[-1].strip() == "Line 094"

    # Scroll to end resumes auto_scroll
    viewport.scroll_to_end()
    assert viewport.auto_scroll is True
    visible = viewport.get_visible_lines(lines, height=10, width=40)
    assert visible[-1].strip() == "Line 099"
