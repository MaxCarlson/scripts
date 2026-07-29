from __future__ import annotations

import json
from pathlib import Path

import pytest

from development_ledger.plan import END_MARKER, START_MARKER


@pytest.fixture
def plan_data() -> dict:
    return {
        "schema_version": 1,
        "plan_id": "demo-plan",
        "title": "Demo Plan",
        "project_root": "modules/demo",
        "plan_revision": 1,
        "stage": {"id": "S1", "title": "Foundation", "status": "in_progress"},
        "session": {
            "actor": "remote_llm",
            "mode": "hybrid",
            "request": {
                "status": "incorporated",
                "summary": "Implement preview safety and error handling.",
                "resolution": "compatible",
                "affected_ids": ["AC-001", "AC-002"],
                "supersedes": [],
                "conflicts": [],
            },
            "objective": "Implement preview safety.",
            "hypothesis": "Preview reaches the subprocess boundary.",
            "target_ids": ["AC-001"],
            "selection_rationale": "AC-001 is the foundational safety behavior for later commands.",
            "stop_conditions": ["Preview behavior and expected tests are ready for validation."],
            "batch": {
                "profile": "standard",
                "target_minutes": 15,
                "max_minutes": 20,
                "max_items": 4,
            },
            "environment_dependencies": [],
            "diagnostic_complexity": "normal",
            "architecture_impact": "local",
            "architecture_review": {
                "requested": False,
                "performed": False,
                "summary": "",
                "findings": [],
                "actions": [],
            },
            "relevant_files": ["demo/engine.py"],
        },
        "items": [
            {
                "id": "AC-001",
                "kind": "criterion",
                "title": "Preview never executes the external command.",
                "implementation": "implemented",
                "tests": ["pytest:tests/engine_test.py::test_preview"],
                "manual_checks": ["MC-001"],
                "depends_on": [],
                "blocked_by": [],
                "relevant_files": ["demo/engine.py"],
                "priority": 10,
                "architecture_role": "foundation",
            },
            {
                "id": "AC-002",
                "kind": "criterion",
                "title": "Errors return nonzero.",
                "implementation": "implemented",
                "tests": ["glob:pytest:*::test_error*"],
                "manual_checks": [],
                "depends_on": ["AC-001"],
                "blocked_by": [],
                "relevant_files": ["demo/cli.py"],
                "priority": 5,
                "architecture_role": "feature",
            },
        ],
        "manual_checks": [
            {
                "id": "MC-001",
                "title": "Inspect preview output",
                "item_ids": ["AC-001"],
                "platform": "windows",
                "instructions": ["Run the preview command.", "Confirm no process starts."],
                "expected": "The command is printed but not executed.",
                "status": "pending",
                "safety": "non_destructive",
            }
        ],
        "policy": {
            "session": {"target_minutes": 15, "max_minutes": 20, "max_items": 4},
            "architecture_review": {"max_validation_runs": 5, "max_plan_revisions": 3},
        },
        "relevant_docs": ["docs/HANDOFF.md"],
    }


@pytest.fixture
def plan_path(tmp_path: Path, plan_data: dict) -> Path:
    path = tmp_path / "plan.md"
    payload = json.dumps(plan_data, indent=4)
    path.write_text(
        f"# Demo\n\n{START_MARKER}\n```json\n{payload}\n```\n{END_MARKER}\n",
        encoding="utf-8",
    )
    return path
