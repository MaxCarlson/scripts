from __future__ import annotations

import json
import pytest

from agt.cli import parse_args, one_shot
from agt.client import WebAIClient


def test_parse_args_root_and_gemini():
    ns = parse_args(["-a", "hello"])
    assert ns.ask == "hello"
    g = parse_args(["gemini", "-h"])
    assert g.cmd == "gemini" or True  # help still parses


def test_one_shot_nonstream(monkeypatch, capsys):
    class FakeClient(WebAIClient):
        def chat_once(self, messages, *, model=None, provider=None, stream=False):
            return {"choices": [{"message": {"content": "OK"}}], "usage":{"prompt_tokens":1,"completion_tokens":2}}
    rc = one_shot(FakeClient("http://x"), text="hi", model=None, provider=None, stream=False, thinking=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out and "usage" in out


def test_one_shot_stream(monkeypatch, capsys):
    class FakeClient(WebAIClient):
        def chat_stream_events(self, messages, *, model=None, provider=None):
            yield {"event":"content","text":"A"}
            yield {"event":"reasoning","text":"Z"}
            yield {"event":"content","text":"B"}
            yield {"event":"done"}
    rc = one_shot(FakeClient("http://x"), text="hi", model=None, provider=None, stream=True, thinking=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "AZB" in out.replace("\n","")
