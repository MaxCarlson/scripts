from __future__ import annotations

from pathlib import Path

from clipboard_tools import terminal_capture


def test_tmux_capture_full_and_since_last_clear():
    sample = "old line\x1b[H\x1b[2Jnew line 1\nnew line 2\n"
    smart = terminal_capture.capture_tmux_buffer(lambda _sl: sample, full=False)
    assert smart.ok is True
    assert smart.backend == "tmux"
    assert smart.clear_found is True
    assert smart.text == "new line 1\nnew line 2"

    full = terminal_capture.capture_tmux_buffer(lambda _sl: sample, full=True)
    assert full.ok is True
    assert "old line" in full.text
    assert "new line 1" in full.text


def test_session_log_capture_and_clear_boundary(tmp_path: Path):
    log = tmp_path / "session.log"
    log.write_text("before\x1b[2J\x1b[Hafter clear\n", encoding="utf-8")

    res = terminal_capture.capture_session_log(log, full=False)
    assert res.ok is True
    assert res.backend == "session_log"
    assert res.clear_found is True
    assert res.text == "after clear"


def test_unsupported_native_terminal_fails_honestly():
    res = terminal_capture.unsupported_native_terminal_result()
    assert res.ok is False
    assert res.backend == "unsupported"
    assert "Windows Terminal" in (res.error or "")
    assert res.guidance is not None
