import pytest
from agt.client import WebAIClient
from agt.tui import TUI

class _Dummy(WebAIClient):
    def __init__(self): pass
    def health_detail(self): return True, "ok"
    def chat_stream_events(self, messages, *, model):
        yield {"event": "content", "text": "pong"}
        yield {"event": "done"}

@pytest.mark.parametrize("extra_kwargs", [
    {}, {"provider": None, "stream": True, "thinking": True, "verbose": False},
])
def test_tui_constructs(extra_kwargs):
    TUI(_Dummy(), model="gemini-2.0-flash", log_file=None, **extra_kwargs)
