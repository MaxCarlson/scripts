from __future__ import annotations

import io

from termdash.live import LiveBlock
from termdash.table import _visible_len


class Terminal(io.StringIO):
    def isatty(self):
        return True


def test_three_rows_are_updated_relatively_without_screen_clear(monkeypatch):
    monkeypatch.delenv("TERM", raising=False)
    stream = Terminal()
    block = LiveBlock(stream=stream, interval=10)
    block.update(lambda: ["URL", "Item:1/3", "Overall:1/10"])
    first = stream.getvalue()
    block.update(lambda: ["URL2", "Item:2/3", "Overall:2/10"])
    appended = stream.getvalue()[len(first) :]
    assert "\033[2A" in appended
    assert "\033[2J" not in stream.getvalue() and "\033[1;1H" not in stream.getvalue()
    assert block._height == 3
    block.close()
    assert block._height == 0


def test_provider_clipped_and_no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    stream = Terminal()
    block = LiveBlock(stream=stream, interval=10)
    monkeypatch.setattr(block, "_width", lambda: 10)
    block.update(lambda: ["\033[32m日本語" * 10 + "\033[0m"])
    content = stream.getvalue().replace("\r", "").replace("\033[2K", "")
    assert "\033[32m" not in content and _visible_len(content) <= 10
    block.close()


def test_redirect_and_quiet_do_not_emit_escape_sequences():
    stream = io.StringIO()
    block = LiveBlock(stream=stream)
    block.update(lambda: ["status"])
    block.log("plain progress")
    block.close()
    assert stream.getvalue() == "plain progress\n"
    quiet = LiveBlock(stream=stream, enabled=False)
    quiet.log("hidden")
    quiet.close()
    assert "hidden" not in stream.getvalue()
