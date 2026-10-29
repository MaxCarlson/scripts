import json
from pathlib import Path

from llm_monitor.opencode import OpenCodeClient, _normalized_state, _safe_session_info, summarize_session
from llm_monitor.events import events_from_messages


def test_summarize_session_matches_poll_fields_and_deduplicates_compaction_parts():
    messages = [
        {"info": {"id": "u1", "role": "user"}, "parts": [{"type": "text", "text": "private prompt"}]},
        {
            "info": {
                "id": "a1",
                "role": "assistant",
                "agent": "local-worker",
                "modelID": "qwen38_23GB",
                "variant": "medium",
                "finish": "stop",
                "time": {"created": 1729999990, "completed": 1730000000},
                "tokens": {"input": 100, "output": 20, "reasoning": 5, "total": 120},
            },
            "parts": [
                {"type": "compaction", "id": "c1"},
                {"type": "compaction", "id": "c1"},
                {"type": "tool", "tool": "read", "state": {"status": "completed"}},
            ],
        },
    ]
    summary = summarize_session(
        "ses-1", messages, {"ses-1": {"type": "busy"}}, [], [], polled_at="2026-01-01T00:00:00Z"
    )

    assert summary["session_id"] == "ses-1"
    assert summary["session_state"] == {"type": "busy"}
    assert summary["total_messages"] == 2
    assert summary["assistant_messages"] == 1
    assert summary["compaction_count"] == 1
    assert summary["pending_permissions"] == summary["pending_questions"] == 0
    assert summary["last_assistant_finish"] == "stop"
    assert summary["last_assistant_variant"] == "medium"
    assert summary["last_assistant_created"] is not None
    assert summary["last_assistant_tokens"]["reasoning"] == 5
    assert "private prompt" not in str(summary)


def test_client_reports_unavailable_endpoint_without_raising():
    client = OpenCodeClient("http://127.0.0.1:1", timeout=0.01)

    result = client.get_json("/global/health")

    assert result.data is None
    assert result.error


def test_client_supports_optional_basic_auth_and_project_directory(monkeypatch):
    import base64
    import llm_monitor.opencode as opencode_module

    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"version":"1.19.3"}'

    def fake_urlopen(request, timeout):
        captured["auth"] = request.get_header("Authorization")
        captured["directory"] = request.get_header("X-opencode-directory")
        return Response()

    monkeypatch.setattr(opencode_module, "urlopen", fake_urlopen)
    client = OpenCodeClient("http://opencode", username="opencode", password="secret")

    result = client.get_json("/global/health", r"C:\pilot")

    assert result.data == {"version": "1.19.3"}
    assert captured["auth"] == "Basic " + base64.b64encode(b"opencode:secret").decode()
    assert captured["directory"] == r"C:\pilot"


def test_client_bounds_message_fetch_and_retains_observed_counts(monkeypatch):
    client = OpenCodeClient("http://opencode", message_limit=2)
    payloads = {
        "/session/status": {"ses-1": {"type": "busy"}},
        "/permission": [],
        "/question": [],
        "/session/ses-1": {"id": "ses-1"},
    }
    message_pages = [
        [{"info": {"id": "a1", "role": "assistant"}}],
        [{"info": {"id": "a1", "role": "assistant", "finish": "stop"}},
         {"info": {"id": "a2", "role": "assistant"}}],
    ]

    def get_json(path, directory=None):
        if path.startswith("/api/session/"):
            return type("Result", (), {"data": None, "error": "HTTP 404", "status_code": 404})()
        if "/message?" in path:
            assert "limit=2" in path
            return type("Result", (), {"data": message_pages.pop(0), "error": None})()
        return type("Result", (), {"data": payloads[path], "error": None})()

    monkeypatch.setattr(client, "get_json", get_json)
    first = client.poll("ses-1")
    second = client.poll("ses-1")

    assert first["total_messages"] == 1
    assert second["total_messages"] == 2
    assert second["last_assistant_id"] == "a2"
    assert second["message_counts_scope"] == "limited_history"


def test_phase2a_and_phase2b_acceptance_fixtures_match_poll_adapter():
    fixture_dir = Path(__file__).parent / "fixtures"
    for filename in ("phase2a_32k_acceptance.json", "phase2b_64k_acceptance.json"):
        fixture = json.loads((fixture_dir / filename).read_text(encoding="utf-8"))
        expected = fixture["expected_poll"]
        assert expected["total_messages"] >= expected["assistant_messages"]
        assert expected["compaction_count"] >= 0
        assert expected["last_assistant_finish"] == "stop"
        assert fixture["run_cumulative_tokens"]["input"] > expected["last_assistant_tokens"]["input"]


def test_normalized_state_detects_compaction_and_keeps_permission_blocker_explicit():
    events = events_from_messages("ses-1", [{"info": {"id": "a1", "role": "assistant"},
        "parts": [{"id": "c1", "type": "compaction", "time": {"started": 1000}}]}])
    compactions = [event for event in events if event.category == "compaction"]

    assert _normalized_state({"type": "busy"}, None, [], compactions, [], []) == "compacting"
    assert _normalized_state({"type": "idle"}, None, [], [], [{"sessionID": "ses-1"}], []) == "waiting_permission"


def test_safe_session_info_preserves_variant_and_allowlisted_model_options():
    info = _safe_session_info({"id": "ses-1", "variant": "medium", "model": {
        "id": "qwen38_23GB", "providerID": "lmstudio", "options": {
            "maxTokens": 8192, "reasoning_effort": "medium", "apiKey": "secret-value"}}})

    assert info["variant"] == "medium"
    assert info["model_options"] == {"maxTokens": 8192, "reasoning_effort": "medium"}
    assert "secret-value" not in str(info)


def test_completed_message_reconciliation_sets_completed_activity_when_status_is_absent():
    from llm_monitor.live import LiveSessionState

    state = LiveSessionState("ses-1", r"C:\pilot")
    state.reconcile({"session_state": None, "last_assistant_finish": "length",
                     "last_assistant_is_complete": True, "last_assistant_tokens": {"reasoning": 8192}}, now=1.0)

    assert state.snapshot(now=1.0)["activity"] == "completed"
