"""Offline, conservative review of test activity in ATIF evidence."""

from __future__ import annotations

import re
from typing import Any

_TEST_COMMAND = re.compile(r"(?:^|[\s;&|])(?:pytest|py\.test|unittest|npm\s+test|cargo\s+test|go\s+test)(?:\s|$)")


def _walk(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def analyze_test_activity(trajectory: dict[str, Any], *, trial_id: str,
                          hidden_passed: bool | None, metrics_by_trial: dict[str, dict]) -> dict[str, Any]:
    """Extract only explicit command and exit-code evidence; leave quality to review."""
    if not trial_id:
        raise ValueError("trial_id is required")
    calls: list[dict] = []
    observations: dict[str, int] = {}
    for node in _walk(trajectory):
        if isinstance(node.get("tool_calls"), list):
            calls.extend(call for call in node["tool_calls"] if isinstance(call, dict))
        call_id = node.get("source_call_id")
        exit_code = node.get("exit_code")
        if isinstance(call_id, str) and isinstance(exit_code, int) and not isinstance(exit_code, bool):
            observations[call_id] = exit_code
    statuses: list[int | None] = []
    for call in calls:
        args = call.get("arguments", {})
        if isinstance(args, dict):
            command = args.get("command") or args.get("cmd")
            if isinstance(command, str) and _TEST_COMMAND.search(command):
                statuses.append(observations.get(call.get("tool_call_id")))
    local_pass = any(status == 0 for status in statuses)
    return {
        "schema": "test-quality-observation-v1", "trial_id": trial_id,
        "tool_invocations": len(calls), "test_commands_detected": len(statuses),
        "test_commands_failed": sum(status is not None and status != 0 for status in statuses),
        "test_commands_unknown_exit": sum(status is None for status in statuses),
        "tests_executed": None,
        "local_pass_observed": local_pass,
        "false_green": True if local_pass and hidden_passed is False else None,
        "metrics": metrics_by_trial.get(trial_id),
        "manual_review": {"requirement_coverage": None, "oracle_correctness": None,
                          "expectations_weakened": None, "source_corrected_after_failure": None},
    }
