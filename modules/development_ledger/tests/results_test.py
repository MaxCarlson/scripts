from __future__ import annotations

import json
from pathlib import Path

from development_ledger.results import (
    aggregate_tests,
    failure_fingerprint,
    parse_junit_xml,
    parse_script_results,
    parse_transcript,
)


def test_parse_junit_xml_extracts_status_and_requirement(tmp_path: Path):
    path = tmp_path / "pytest.xml"
    path.write_text(
        """<?xml version="1.0"?>
<testsuite name="pytest" tests="2">
  <testcase classname="tests.engine_test" name="test_preview" file="tests/engine_test.py" time="0.1">
    <properties><property name="requirement" value="AC-001" /></properties>
  </testcase>
  <testcase classname="tests.engine_test" name="test_error" file="tests/engine_test.py" time="0.2">
    <failure message="AssertionError: expected 2">trace</failure>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    tests = parse_junit_xml(path)

    assert tests[0].id == "pytest:tests/engine_test.py::test_preview"
    assert tests[0].item_ids == ["AC-001"]
    assert tests[1].status == "failed"
    assert aggregate_tests(tests)["failed"] == 1


def test_parse_script_results_preserves_explicit_ids(tmp_path: Path):
    path = tmp_path / "results.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "powershell",
                "suite": "smoke",
                "tests": [
                    {
                        "id": "powershell:smoke::entrypoint",
                        "name": "entrypoint",
                        "status": "passed",
                        "item_ids": ["AC-001"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    tests = parse_script_results(path)

    assert tests[0].id == "powershell:smoke::entrypoint"
    assert tests[0].item_ids == ["AC-001"]


def test_parse_transcript_extracts_commands_pytest_counts_and_coverage(tmp_path: Path):
    path = tmp_path / "LATEST.txt"
    path.write_text(
        "RESULT: PASS - Compile package\nRESULT: FAIL - PowerShell smoke\n126 passed, 2 failed, 8 skipped in 3.2s\n"
        "TOTAL 200 20 90%\n",
        encoding="utf-8",
    )

    tests, metrics = parse_transcript(path)

    assert [test.status for test in tests] == ["passed", "failed"]
    assert metrics == {"passed": 126, "failed": 2, "skipped": 8, "errors": 0, "coverage_percent": 90.0}


def test_failure_fingerprint_normalizes_paths_and_addresses():
    from development_ledger.models import NormalizedTest

    test = NormalizedTest(
        id="pytest:x::y",
        name="y",
        status="failed",
        message="Failure at C:\\Users\\name\\tmp\\x.py address 0xABC123",
    )

    fingerprint = failure_fingerprint(test)
    assert "<path>" in fingerprint
    assert "<address>" in fingerprint


def test_parse_script_results_rejects_bad_status(tmp_path: Path):
    from development_ledger.results import ResultParseError

    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "shell",
                "suite": "bad",
                "tests": [{"id": "x", "name": "x", "status": "maybe"}],
            }
        ),
        encoding="utf-8",
    )

    import pytest

    with pytest.raises(ResultParseError, match="Invalid status"):
        parse_script_results(path)


def test_parse_transcript_without_summary_returns_zero_metrics(tmp_path: Path):
    path = tmp_path / "plain.txt"
    path.write_text("no recognized result lines", encoding="utf-8")

    tests, metrics = parse_transcript(path)

    assert tests == []
    assert metrics == {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
