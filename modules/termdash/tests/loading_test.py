import io

import pytest

from termdash import LoadingIndicator, TermDash


def test_loading_indicator_renders_updates_and_clears_test():
    stream = io.StringIO()
    indicator = LoadingIndicator("Preparing", interval=10, frames=("*",), stream=stream)

    indicator.start()
    indicator.update("Indexing")
    indicator.stop()

    rendered = stream.getvalue()
    assert "* Preparing" in rendered
    assert "* Indexing" in rendered
    assert "\x1b[2K" in rendered


def test_loading_indicator_rejects_empty_frames_test():
    with pytest.raises(ValueError, match="frames"):
        LoadingIndicator(frames=())


def test_termdash_loading_transition_uses_dashboard_state_test():
    td = TermDash()
    td._running = True

    with td.transition("Changing state") as active_dashboard:
        assert active_dashboard is td
        assert td._loading_message == "Changing state"

    assert td._loading_message is None
