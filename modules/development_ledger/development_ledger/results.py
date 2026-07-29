"""Adapters that normalize JUnit XML, generic JSON, and legacy transcript results."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from development_ledger.models import NormalizedTest, VALID_TEST_STATES

_PROPERTY_NAMES = {"requirement", "requirements", "criterion", "criteria", "feature", "features", "item", "items"}
_PYTEST_SUMMARY_RE = re.compile(
    r"(?P<passed>\d+)\s+passed|(?P<failed>\d+)\s+failed|(?P<skipped>\d+)\s+skipped|"
    r"(?P<errors>\d+)\s+errors?",
    re.IGNORECASE,
)
_RESULT_RE = re.compile(r"^RESULT:\s*(?P<status>PASS|FAIL)\s*-\s*(?P<name>.+?)\s*$", re.MULTILINE)
_COVERAGE_RE = re.compile(r"^TOTAL\s+\d+\s+\d+\s+(?P<percent>\d+(?:\.\d+)?)%", re.MULTILINE)


class ResultParseError(ValueError):
    """Raised when a result file is malformed or unsupported."""


def parse_junit_xml(path: Path, *, source: str = "pytest") -> list[NormalizedTest]:
    """Parse JUnit XML into normalized tests."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ResultParseError(f"Unable to parse JUnit XML {path}: {exc}") from exc

    tests: list[NormalizedTest] = []
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        suites = [root]

    seen_elements: set[int] = set()
    for suite in suites:
        suite_name = suite.attrib.get("name", path.stem)
        for case in suite.findall("testcase"):
            if id(case) in seen_elements:
                continue
            seen_elements.add(id(case))
            tests.append(_parse_junit_case(case, suite_name=suite_name, source=source))

    return tests


def parse_script_results(path: Path) -> list[NormalizedTest]:
    """Parse the repository-owned generic JSON script-result format."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ResultParseError(f"Unable to parse script results {path}: {exc}") from exc

    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ResultParseError(f"Script result {path} must be an object with schema_version 1.")
    suite = str(data.get("suite", path.stem))
    source = str(data.get("source", "script"))
    raw_tests = data.get("tests")
    if not isinstance(raw_tests, list):
        raise ResultParseError(f"Script result {path} must contain a tests list.")

    tests: list[NormalizedTest] = []
    for index, raw in enumerate(raw_tests):
        if not isinstance(raw, dict):
            raise ResultParseError(f"Script result test {index} in {path} must be an object.")
        status = str(raw.get("status", ""))
        if status not in VALID_TEST_STATES:
            raise ResultParseError(f"Invalid status {status!r} for script result test {index} in {path}.")
        raw_id = str(raw.get("id") or raw.get("name") or f"test-{index}")
        test_id = raw_id if ":" in raw_id else f"{source}:{suite}::{raw_id}"
        tests.append(
            NormalizedTest(
                id=test_id,
                name=str(raw.get("name", raw_id)),
                status=status,
                suite=suite,
                source=source,
                file=str(raw.get("file", "")),
                classname=str(raw.get("classname", "")),
                duration_seconds=float(raw.get("duration_seconds", 0.0) or 0.0),
                message=str(raw.get("message", "")),
                item_ids=_string_values(raw.get("item_ids", [])),
                metadata=dict(raw.get("metadata", {})),
            )
        )
    return tests


def parse_transcript(path: Path) -> tuple[list[NormalizedTest], dict[str, float | int]]:
    """Extract coarse command results and metrics from the current text-report format."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ResultParseError(f"Unable to read transcript {path}: {exc}") from exc

    tests = [
        NormalizedTest(
            id=f"command:{_slug(match.group('name'))}",
            name=match.group("name").strip(),
            status="passed" if match.group("status") == "PASS" else "failed",
            suite="validation-transcript",
            source="transcript",
            message="",
        )
        for match in _RESULT_RE.finditer(text)
    ]

    metrics: dict[str, float | int] = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for match in _PYTEST_SUMMARY_RE.finditer(text):
        for key in ("passed", "failed", "skipped", "errors"):
            value = match.group(key)
            if value is not None:
                metrics[key] = int(value)
    coverage_match = _COVERAGE_RE.search(text)
    if coverage_match:
        metrics["coverage_percent"] = float(coverage_match.group("percent"))
    return tests, metrics


def aggregate_tests(tests: Iterable[NormalizedTest]) -> dict[str, int | float]:
    """Return aggregate counts and duration for normalized tests."""
    summary: dict[str, int | float] = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 0.0,
    }
    for test in tests:
        summary["total"] += 1
        summary[test.status if test.status != "error" else "errors"] += 1
        summary["duration_seconds"] += test.duration_seconds
    summary["duration_seconds"] = round(float(summary["duration_seconds"]), 6)
    return summary


def failure_fingerprint(test: NormalizedTest) -> str:
    """Create a stable compact fingerprint for one failing/error test."""
    first_line = test.message.strip().splitlines()[0] if test.message.strip() else ""
    normalized = re.sub(r"\b0x[0-9a-fA-F]+\b", "<address>", first_line)
    normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ][^\s]+", "<timestamp>", normalized)
    normalized = re.sub(r"[A-Za-z]:\\[^\s]+|/(?:[^\s/]+/)+[^\s]+", "<path>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return f"{test.id}|{test.status}|{normalized[:240]}"


def _parse_junit_case(case: ET.Element, *, suite_name: str, source: str) -> NormalizedTest:
    name = case.attrib.get("name", "unnamed")
    classname = case.attrib.get("classname", "")
    file_name = case.attrib.get("file", "").replace("\\", "/")
    if not file_name and source == "pytest":
        file_name = _pytest_classname_to_file(classname)
    stable_part = f"{file_name}::{name}" if file_name else f"{classname}::{name}" if classname else name
    test_id = f"{source}:{stable_part}"

    status = "passed"
    message = ""
    for child_name, child_status in (("failure", "failed"), ("error", "error"), ("skipped", "skipped")):
        child = case.find(child_name)
        if child is not None:
            status = child_status
            message = child.attrib.get("message", "") or (child.text or "")
            break

    item_ids: list[str] = []
    properties = case.find("properties")
    if properties is not None:
        for prop in properties.findall("property"):
            if prop.attrib.get("name", "").lower() in _PROPERTY_NAMES:
                item_ids.extend(_split_ids(prop.attrib.get("value", "")))

    return NormalizedTest(
        id=test_id,
        name=name,
        status=status,
        suite=suite_name,
        source=source,
        file=file_name,
        classname=classname,
        duration_seconds=float(case.attrib.get("time", "0") or 0.0),
        message=message.strip()[:4000],
        item_ids=sorted(set(item_ids)),
        metadata={"junit_classname": classname},
    )


def _pytest_classname_to_file(classname: str) -> str:
    """Convert pytest's dotted JUnit classname to the documented file-path form."""
    parts = [part for part in classname.split(".") if part]
    while parts and (parts[-1].startswith("Test") or parts[-1][:1].isupper()):
        parts.pop()
    if not parts or not all(part.isidentifier() for part in parts):
        return ""
    return "/".join(parts) + ".py"


def _split_ids(value: str) -> list[str]:
    return [part for part in re.split(r"[,;\s]+", value.strip()) if part]


def _string_values(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return _split_ids(value)
    return []


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "unnamed"
