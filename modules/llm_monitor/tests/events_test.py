from llm_monitor.events import events_from_messages


def test_events_project_only_safe_inference_tool_and_compaction_metadata():
    events = events_from_messages(
        "ses-1",
        [
            {
                "info": {
                    "id": "msg-1",
                    "role": "assistant",
                    "agent": "worker",
                    "modelID": "model-a",
                    "finish": "stop",
                    "time": {"created": 1000, "completed": 2000},
                    "tokens": {"input": 400, "output": 30, "reasoning": 12, "cache": {"read": 8, "write": 2}},
                },
                "parts": [
                    {"type": "compaction", "id": "compact-1", "time": {"started": 1200, "completed": 1500}},
                    {
                        "type": "tool", "id": "part-1", "callID": "call-1", "tool": "read",
                        "state": {"status": "completed", "input": {"filePath": "src/app.py"}, "output": "secret source"},
                    },
                ],
            }
        ],
    )

    assert [event.category for event in events] == ["message", "inference", "compaction", "tool"]
    assert events[1].finish_reason == "stop"
    assert events[1].tokens == {"input": 400, "output": 30, "reasoning": 12, "cache_read": 8, "cache_write": 2}
    assert events[2].duration_seconds == 0.3
    assert events[3].tool_name == "read"
    assert events[3].tool_target == "src/app.py"
    assert "secret source" not in repr(events)


def test_event_identity_uses_provider_ids_and_missing_time_stays_unavailable():
    messages = [{"info": {"id": "same-id", "role": "assistant", "tokens": {"input": 1}}, "parts": []}]

    first = events_from_messages("ses-1", messages)
    duplicate = events_from_messages("ses-1", messages)

    assert first[1].event_id == duplicate[1].event_id
    assert first[1].timestamp is None
    assert first[1].duration_seconds is None
    assert first[1].provider_id == "same-id"


def test_shell_read_target_is_extracted_only_for_known_read_commands():
    events = events_from_messages(
        "ses-1",
        [{"info": {"id": "a1", "role": "assistant"}, "parts": [
            {"type": "tool", "callID": "s1", "tool": "bash",
             "state": {"status": "completed", "input": {"command": "cat 'src/app.py'"}, "output": "secret"}},
            {"type": "tool", "callID": "s2", "tool": "bash",
             "state": {"status": "completed", "input": {"command": "python build.py"}, "output": "output"}},
        ]}],
    )

    tools = [event for event in events if event.category == "tool"]
    assert [event.tool_target for event in tools] == ["src/app.py", None]
    assert "secret" not in repr(tools)
