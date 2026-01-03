import time

from termdash.rotating_text import RotatingText


class DummyBoard:
    def __init__(self):
        self.updates = []

    def update(self, line, stat, value):
        self.updates.append((line, stat, value))


def test_rotates_through_paragraphs_time_based():
    board = DummyBoard()
    paragraphs = ["short text", "second longer text"]
    rot = RotatingText(
        board,
        "line",
        "stat",
        paragraphs,
        min_interval_s=0.05,
        max_interval_s=0.1,
        words_per_second=100.0,  # keep dwell tiny for test speed
    )
    rot.start()
    time.sleep(0.05)
    rot.advance()  # force next paragraph quickly
    time.sleep(0.1)
    rot.stop()

    # Should have advanced to at least the second paragraph
    assert any(p[2] == paragraphs[0] for p in board.updates)
    assert any(p[2] == paragraphs[1] for p in board.updates)


def test_advance_skips_waiting():
    board = DummyBoard()
    paragraphs = ["first", "second", "third"]
    rot = RotatingText(
        board,
        "line",
        "stat",
        paragraphs,
        min_interval_s=1.0,
        max_interval_s=1.0,
        words_per_second=1.0,
    )
    rot.start()
    time.sleep(0.1)
    rot.advance()  # jump to next paragraph without waiting the full interval
    for _ in range(10):
        if any(p[2] == "second" for p in board.updates):
            break
        time.sleep(0.05)
    rot.stop()

    # We should have progressed beyond the first paragraph thanks to advance()
    seen = [p[2] for p in board.updates]
    assert "first" in seen
    assert "second" in seen
