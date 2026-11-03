from agent_benchmark.test_quality_review import analyze_test_activity


def test_nested_calls_and_trial_id_metric_join():
    trajectory = {"steps": [{"nested": {"tool_calls": [
        {"tool_call_id": "one", "arguments": {"command": "pytest -q"}},
        {"tool_call_id": "two", "arguments": {"command": "go test ./..."}},
    ]}, "observation": {"results": [
        {"source_call_id": "one", "exit_code": 0}, {"source_call_id": "two", "exit_code": 2},
    ]}}]}
    result = analyze_test_activity(trajectory, trial_id="trial-1", hidden_passed=False,
                                   metrics_by_trial={"trial-1": {"input_tokens": 23}, "task-name": {"input_tokens": 999}})
    assert result["test_commands_detected"] == 2
    assert result["test_commands_failed"] == 1
    assert result["false_green"] is True
    assert result["metrics"]["input_tokens"] == 23
    assert result["manual_review"]["oracle_correctness"] is None


def test_unknown_exit_is_not_a_false_green():
    trajectory = {"steps": [{"tool_calls": [{"tool_call_id": "one", "arguments": {"command": "pytest"}}]}]}
    result = analyze_test_activity(trajectory, trial_id="trial-1", hidden_passed=False, metrics_by_trial={})
    assert result["false_green"] is None
    assert result["test_commands_unknown_exit"] == 1
    assert result["metrics"] is None
