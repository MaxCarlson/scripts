import json
from pathlib import Path

from llm_monitor.opencode import OpenCodeClient, summarize_session


def test_summarize_session_matches_poll_fields_and_deduplicates_compaction_parts():
    messages = [
        {"info": {"id": "u1", "role": "user"}, "parts": [{"type": "text", "text": "private prompt"}]},
        {
            "info": {
                "id": "a1",
                "role": "assistant",
                "agent": "local-worker",
                "modelID": "qwen38_23GB",
                "finish": "stop",
                "time": {"completed": 1730000000},
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
    assert summary["last_assistant_tokens"]["reasoning"] == 5
    assert "private prompt" not in str(summary)


def test_client_reports_unavailable_endpoint_without_raising():
    client = OpenCodeClient("http://127.0.0.1:1", timeout=0.01)

    result = client.get_json("/global/health")

    assert result.data is None
    assert result.error


def test_client_bounds_message_fetch_and_retains_observed_counts(monkeypatch):
    client = OpenCodeClient("http://opencode", message_limit=2)
    payloads = {
        "/session/status": {"ses-1": {"type": "busy"}},
        "/permission": [],
        "/question": [],
    }
    message_pages = [
        [{"info": {"id": "a1", "role": "assistant"}}],
        [{"info": {"id": "a1", "role": "assistant", "finish": "stop"}},
         {"info": {"id": "a2", "role": "assistant"}}],
    ]

    def get_json(path, directory=None):
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
        messages = [{"info": {"id": f"u-{index}", "role": "user"}, "parts": []}
                    for index in range(expected["total_messages"] - expected["assistant_messages"])]
        messages.extend(
            {
                "info": {"id": f"a-{index}", "role": "assistant"},
                "parts": [{"type": "compaction", "id": f"compact-{index}"}]
                if index < expected["compaction_count"] else [],
            }
            for index in range(expected["assistant_messages"])
        )
        messages[-1]["info"].update(
            {
                "id": expected["last_assistant_id"],
                "finish": expected["last_assistant_finish"],
                "time": {"completed": expected["last_assistant_completed"]},
                "tokens": expected["last_assistant_tokens"],
            }
        )

        actual = summarize_session("fixture", messages, {}, [], [])

        for key in (
            "total_messages", "assistant_messages", "compaction_count", "pending_permissions",
            "pending_questions", "last_assistant_id", "last_assistant_finish", "last_assistant_completed",
            "last_assistant_tokens",
        ):
            assert actual[key] == expected[key], f"{filename}: {key}"
        assert fixture["run_cumulative_tokens"]["input"] != actual["last_assistant_tokens"]["input"]

