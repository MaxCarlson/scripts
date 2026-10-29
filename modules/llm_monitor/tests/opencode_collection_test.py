from urllib.error import HTTPError

from llm_monitor.opencode import ApiResult, OpenCodeClient


def test_legacy_overlap_poll_deduplicates_updates_and_retains_no_raw_messages(monkeypatch):
    client = OpenCodeClient("http://opencode", message_limit=2)
    pages = [
        [
            {"info": {"id": "u1", "role": "user", "time": {"created": 1000}},
             "parts": [{"type": "text", "text": "private prompt"}]},
            {"info": {"id": "a1", "role": "assistant", "time": {"created": 1100}}, "parts": []},
        ],
        [
            {"info": {"id": "a1", "role": "assistant", "finish": "stop", "time": {"created": 1100,
                                                                                          "completed": 1200}},
             "parts": []},
            {"info": {"id": "a2", "role": "assistant", "time": {"created": 1300}}, "parts": []},
        ],
    ]

    def get_json(path, directory=None):
        if path.startswith("/api/session/"):
            return ApiResult(error="HTTP 404", status_code=404)
        if path.startswith("/session/ses-1/message"):
            return ApiResult(data=pages.pop(0))
        if path == "/session/status":
            return ApiResult(data={"ses-1": {"type": "busy"}})
        if path == "/session/ses-1":
            return ApiResult(data={"id": "ses-1", "title": "fixture"})
        return ApiResult(data=[])

    monkeypatch.setattr(client, "get_json", get_json)
    first = client.poll("ses-1")
    second = client.poll("ses-1")

    assert first["total_messages"] == 2
    assert second["total_messages"] == 3
    assert second["last_assistant_id"] == "a2"
    assert second["history_coverage"]["status"] == "partial"
    assert "private prompt" not in repr(client.events_for_session("ses-1"))
    assert not hasattr(client, "_message_cache")


def test_cursor_pages_can_be_collected_without_repeating_full_history(monkeypatch):
    client = OpenCodeClient("http://opencode", message_limit=2)
    requests = []

    def get_json(path, directory=None):
        requests.append(path)
        if "cursor=" not in path:
            return ApiResult(
                data={"data": [{"info": {"id": "a1", "role": "assistant"}, "parts": []}],
                      "cursor": {"next": "page-2", "previous": None}}
            )
        return ApiResult(
            data={"data": [{"info": {"id": "a2", "role": "assistant"}, "parts": []}],
                  "cursor": {"next": None, "previous": "page-1"}}
        )

    monkeypatch.setattr(client, "get_json", get_json)

    result = client.collect_history("ses-1")

    assert [event.provider_id for event in result.events if event.category == "message"] == ["a1", "a2"]
    assert result.coverage.status == "complete"
    assert len(requests) == 2


def test_empty_cursor_page_falls_back_to_legacy_messages(monkeypatch):
    client = OpenCodeClient("http://opencode", message_limit=100)
    assistant = {
        "info": {
            "id": "assistant-1",
            "role": "assistant",
            "finish": "stop",
            "time": {"created": 1000, "completed": 2000},
            "tokens": {"input": 20, "output": 5, "reasoning": 1},
        },
        "parts": [{
            "id": "tool-1",
            "type": "tool",
            "callID": "call-1",
            "tool": "write",
            "state": {"status": "completed", "input": {"filePath": "tiny_answer.py"}},
        }],
    }
    requests = []

    def get_json(path, _directory=None):
        requests.append(path)
        if path.startswith("/api/session/"):
            return ApiResult(data={"data": [], "cursor": {"next": None, "previous": None}})
        if path.startswith("/session/ses-1/message?"):
            return ApiResult(data=[assistant])
        return ApiResult(data=[])

    monkeypatch.setattr(client, "get_json", get_json)

    result = client.collect_history("ses-1")

    assert result.coverage.status == "complete"
    assert result.coverage.source == "legacy"
    assert any(path.startswith("/session/ses-1/message?") for path in requests)
    assert [(event.category, event.tool_name) for event in result.events if event.category in {"inference", "tool"}] == [
        ("inference", None), ("tool", "write")
    ]


def test_full_cursor_page_without_next_cursor_is_complete(monkeypatch):
    client = OpenCodeClient("http://opencode", message_limit=1)
    monkeypatch.setattr(
        client,
        "get_json",
        lambda path, directory=None: ApiResult(
            data={"data": [{"info": {"id": "a1", "role": "assistant"}, "parts": []}],
                  "cursor": {"next": None, "previous": None}}
        ),
    )

    result = client.collect_history("ses-1")

    assert result.coverage.status == "complete"


def test_get_json_retries_transient_status_then_returns_decoded_data(monkeypatch):
    client = OpenCodeClient("http://opencode", retries=1)
    attempts = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"healthy":true}'

    def urlopen(_request, timeout):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise HTTPError("http://opencode", 503, "busy", {}, None)
        return Response()

    monkeypatch.setattr("llm_monitor.opencode.urlopen", urlopen)
    monkeypatch.setattr("llm_monitor.opencode.time.sleep", lambda _delay: None)

    result = client.get_json("/global/health")

    assert result.data == {"healthy": True}
    assert result.error is None
    assert len(attempts) == 2
