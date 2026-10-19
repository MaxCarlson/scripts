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


def test_output_viewport_top_aligns_short_output():
    viewport = OutputViewport()
    lines = ["Error line 1", "Error line 2", "Error line 3"]

    # When output is shorter than screen height, it should NOT pad empty lines at the top
    visible = viewport.get_visible_lines(lines, height=10, width=40)
    # Line 0 must be Error line 1, not an empty padding line
    assert visible[0] == "Error line 1"
    assert visible[1] == "Error line 2"
    assert visible[2] == "Error line 3"


def test_output_viewport_wraps_long_lines():
    viewport = OutputViewport()
    # A 70-character line in a 30-char wide terminal
    long_line = (
        "usage: mangadl [-h] [-V] [-T] {run,inspect,status,retry,kavita,archive,audit}"
    )
    visible = viewport.get_visible_lines([long_line], height=10, width=30)
    # The line must be wrapped into multiple lines so no text is truncated horizontally
    combined = " ".join(line.strip() for line in visible if line.strip())
    assert "usage: mangadl" in combined
    assert "archive" in combined
    assert "audit}" in combined
    # It must take more than 1 line
    non_empty = [line for line in visible if line.strip()]
    assert len(non_empty) >= 2


def test_output_viewport_home_and_end():
    viewport = OutputViewport()
    lines = [f"Line {i:03d}" for i in range(50)]

    # Scroll to top (Home)
    viewport.scroll_to_top(len(lines), height=10)
    visible = viewport.get_visible_lines(lines, height=10, width=40)
    assert visible[0].strip() == "Line 000"

    # Scroll to end (End)
    viewport.scroll_to_end()
    visible = viewport.get_visible_lines(lines, height=10, width=40)
    assert visible[-1].strip() == "Line 049"


def test_virtual_terminal_buffer_inplace():
    from cli_tui.process_runner import VirtualTerminalBuffer

    buf = VirtualTerminalBuffer()

    # 1. Single line \r overwrite
    buf.feed("Scanning 10%\rScanning 50%\rScanning 100%\n")
    lines = buf.get_lines()
    assert lines == ["Scanning 100%"]

    # 2. Multiline cursor up and clear line (\033[2A\033[2K)
    buf.feed("Header\nRow A\nRow B\n")
    # Move up 2 lines and overwrite Row A and Row B
    buf.feed("\033[2A\033[2KRow A Updated\n\033[2KRow B Updated\n")
    lines = buf.get_lines()
    assert lines == ["Scanning 100%", "Header", "Row A Updated", "Row B Updated"]


def test_process_runner_unicode_box_drawing_and_colors():
    # Verify that box drawing characters are not converted to \u2502 and colors are preserved
    script = (
        "import sys\n"
        "sys.stdout.write('\033[36m┌─────┐\033[0m\\n\033[32m│ Hi  │\033[0m\\n└─────┘\\n')\n"
        "sys.stdout.flush()\n"
    )
    runner = ProcessRunner([sys.executable, "-c", script])
    runner.start()
    runner.wait(timeout=5.0)

    combined = "\n".join(runner.lines)
    # Must contain actual box characters
    assert "┌" in combined
    assert "│" in combined
    assert "└" in combined
    # Must NOT contain escaped backslash-u literal strings
    assert r"\u2502" not in combined
    assert r"\u2500" not in combined
    # Must preserve ANSI color codes for rendering
    assert "\033[36m" in combined


def test_output_viewport_wrap_ansi_and_box_drawing():
    viewport = OutputViewport()
    # A box border line with cyan color styling: 20 visible characters
    line = "\033[36m┌──────────────────┐\033[0m"
    # In a viewport of width 25, it should not wrap because visual width is 20
    wrapped = viewport.wrap_lines([line], width=25)
    assert len(wrapped) == 1
    assert wrapped[0] == line

    # A line with visual width 30 in a viewport of width 20 should wrap cleanly
    long_colored = "\033[36m" + ("A" * 30) + "\033[0m"
    wrapped = viewport.wrap_lines([long_colored], width=20)
    assert len(wrapped) == 2
    assert "\033[36m" in wrapped[0]
    assert "\033[36m" in wrapped[1]
