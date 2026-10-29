from llm_monitor.analysis import analyze_events
from llm_monitor.events import events_from_messages
from llm_monitor.opencode import HistoryCoverage


def test_analysis_uses_per_inference_input_and_keeps_cache_and_run_totals_separate():
    messages = [
        {"info": {"id": "a1", "role": "assistant", "modelID": "model-a", "finish": "stop", "time": {"created": 1000,
                                                                                       "completed": 3000},
                   "tokens": {"input": 5000, "output": 100, "reasoning": 10,
                              "cache": {"read": 4000, "write": 100}}}, "parts": []},
    ]
    events = events_from_messages("ses-1", messages)

    result = analyze_events(
        "ses-1", events, coverage=HistoryCoverage("complete", "cursor", 1, 100),
        limits={"context": 8192, "output": 1024},
        loaded_model={"id": "model-a", "context_length": 8192, "state": "loaded"},
        cumulative_tokens={"input": 2_146_292, "reasoning": 44_374},
    )

    assert result["context"]["latest_input_tokens"] == 5000
    assert result["context"]["effective_capacity"] == 8192
    assert result["context"]["usable_input_capacity"] == 7168
    assert result["context"]["utilization_percent"] == 69.8
    assert result["inference"]["latest_completed"]["cache_read_tokens"] == 4000
    assert result["cumulative_tokens"]["input"] == 2_146_292
    assert result["context"]["latest_input_tokens"] != result["cumulative_tokens"]["input"]


def test_context_utilization_stays_unknown_when_effective_capacity_is_unavailable():
    events = events_from_messages(
        "ses-1", [{"info": {"id": "a1", "role": "assistant", "finish": "stop",
                              "tokens": {"input": 100}}, "parts": []}]
    )

    result = analyze_events("ses-1", events, coverage=HistoryCoverage("partial", "legacy", 1, 100))

    assert result["context"]["latest_input_tokens"] == 100
    assert result["context"]["effective_capacity"] is None
    assert result["context"]["utilization_percent"] is None
    assert result["context"]["status"] == "unknown"


def test_unavailable_history_does_not_become_zero_activity():
    result = analyze_events(
        "ses-1", [], coverage=HistoryCoverage("unavailable", "legacy", 0, 100)
    )

    assert result["inference"]["count"] is None
    assert result["inference"]["completed_count"] is None
    assert result["compactions"]["unique_count"] is None
    assert result["tools"]["count"] is None


def test_compaction_parts_sharing_operation_id_count_once_but_remain_visible():
    events = events_from_messages("ses-1", [{"info": {"id": "a1", "role": "assistant"},
        "parts": [{"id": "part-1", "type": "compaction", "compactionID": "cycle-1"},
                  {"id": "part-2", "type": "compaction", "compactionID": "cycle-1"}]}])

    result = analyze_events("ses-1", events, coverage=HistoryCoverage("complete", "cursor", 1, 100))

    assert result["compactions"]["unique_count"] == 1
    assert result["compactions"]["raw_parts"] == 2
