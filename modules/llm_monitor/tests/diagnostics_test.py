from llm_monitor.diagnostics import diagnose_events
from llm_monitor.events import events_from_messages
from llm_monitor.analysis import analyze_events
from llm_monitor.opencode import HistoryCoverage


def test_diagnostics_report_compaction_reads_and_failed_edits_with_evidence():
    messages = [
        {"info": {"id": "a1", "role": "assistant", "time": {"created": 1000}},
         "parts": [{"id": "c1", "type": "compaction", "time": {"started": 1000, "completed": 2000}}]},
        {"info": {"id": "a2", "role": "assistant", "time": {"created": 3000}},
         "parts": [{"type": "tool", "id": "t1", "callID": "r1", "tool": "read",
                    "state": {"status": "completed", "time": {"start": 3000, "end": 3100},
                              "input": {"filePath": "src/app.py"}}}]},
        {"info": {"id": "a3", "role": "assistant", "finish": "length", "time": {"created": 4000}},
         "parts": [
             {"type": "tool", "id": "t2", "callID": "r2", "tool": "read",
              "state": {"status": "completed", "input": {"filePath": "src/app.py"}}},
             {"type": "tool", "id": "t3", "callID": "e1", "tool": "edit",
              "state": {"status": "error", "input": {"filePath": "src/app.py"}}},
         ]},
    ]
    events = events_from_messages("ses-1", messages)
    coverage = HistoryCoverage("complete", "cursor", 1, 100)
    analysis = analyze_events("ses-1", events, coverage=coverage,
                              limits={"context": 4096, "output": 1024},
                              loaded_model={"id": "model-a", "context_length": 4096})

    findings = diagnose_events("ses-1", events, analysis, coverage=coverage)
    by_code = {finding["code"]: finding for finding in findings}

    assert by_code["context.length_finish"]["classification"] == "observed"
    assert by_code["reads.repeated_after_compaction"]["classification"] == "hypothesis"
    assert by_code["tools.failed_edit"]["evidence"][0]["tool_target"] == "src/app.py"
    assert by_code["reads.repeated_after_compaction"]["evidence"][0]["read_count"] == 2


def test_missing_timestamps_and_capacity_produce_unknown_not_fabricated_findings():
    events = events_from_messages(
        "ses-1", [{"info": {"id": "a1", "role": "assistant", "finish": "stop"}, "parts": []}]
    )
    coverage = HistoryCoverage("partial", "legacy", 1, 100, reason="bounded history")
    analysis = analyze_events("ses-1", events, coverage=coverage)

    findings = diagnose_events("ses-1", events, analysis, coverage=coverage)

    assert any(item["code"] == "coverage.partial_history" for item in findings)
    assert not any(item["code"] == "context.near_limit" for item in findings)
    assert analysis["context"]["utilization_percent"] is None


def test_context_error_is_reported_as_observed_overflow_evidence():
    events = events_from_messages(
        "ses-1", [{"info": {"id": "a1", "role": "assistant", "error": {"name": "ContextOverflowError"}},
                    "parts": []}]
    )
    coverage = HistoryCoverage("complete", "cursor", 1, 100)
    analysis = analyze_events("ses-1", events, coverage=coverage)

    findings = diagnose_events("ses-1", events, analysis, coverage=coverage)

    overflow = next(item for item in findings if item["code"] == "context.overflow")
    assert overflow["classification"] == "observed"
    assert overflow["evidence"][0]["error_name"] == "ContextOverflowError"
