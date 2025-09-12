# tests/cli_test.py
from __future__ import annotations

import json
from pathlib import Path
import pytest

from agt.cli import build_parser, one_shot
from agt.client import WebAIClient


def test_build_parser():
    p = build_parser()
    ns = p.parse_args(["gemini", "hello"])
    assert ns.sub == "gemini"
    assert ns.message == ["hello"]
    assert ns.stream is False

    ns2 = p.parse_args(["gemini", "--stream", "--prompt", "what is up?"])
    assert ns2.stream is True
    assert ns2.prompt == "what is up?"


def test_one_shot_nonstream(monkeypatch, capsys, tmp_path):
    class FakeClient(WebAIClient):
        def chat_once(self, messages, *, model=None, stream=False):
            return {"choices": [{"message": {"content": "OK"}}]}

    rc = one_shot(
        client=FakeClient("http://x"),
        text="hi",
        model="test-model",
        session=None,
        stream=False,
        verbose=False,
        cwd=tmp_path,
        attach_root_hint=None,
        log_events=False
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out


def test_one_shot_stream(monkeypatch, capsys, tmp_path):
    class FakeClient(WebAIClient):
        def chat_stream_events(self, messages, *, model=None):
            yield {"event":"content","text":"A"}
            yield {"event":"content","text":"B"}
            yield {"event":"done"}

    rc = one_shot(
        client=FakeClient("http://x"),
        text="hi",
        model="test-model",
        session=None,
        stream=True,
        verbose=False,
        cwd=tmp_path,
        attach_root_hint=None,
        log_events=False
    )
    assert rc == 0
    out, err = capsys.readouterr()
    # The spinner writes to stderr, so we check stdout for the content
    assert "AB" in out.replace("\n", "")