# Example Feature Plan

## Objective

Implement a safe preview mode and verify the installed Windows entry point.

## Development Ledger State

<!-- development-ledger:state:start -->
```json
{
    "schema_version": 1,
    "plan_id": "example-preview",
    "title": "Example Preview Safety",
    "project_root": "modules/example",
    "stage": {
        "id": "S1",
        "title": "Preview Foundation",
        "status": "in_progress"
    },
    "session": {
        "actor": "remote_llm",
        "mode": "hybrid",
        "objective": "Implement preview without launching the external process.",
        "hypothesis": "Moving the preview branch before subprocess construction prevents execution.",
        "target_ids": ["AC-001"],
        "environment_dependencies": [],
        "diagnostic_complexity": "normal",
        "relevant_files": ["example/engine.py", "tests/engine_test.py"]
    },
    "items": [
        {
            "id": "AC-001",
            "kind": "criterion",
            "title": "Preview prints the command but never executes it.",
            "implementation": "implemented",
            "tests": ["pytest:tests/engine_test.py::test_preview"],
            "manual_checks": ["MC-001"],
            "blocked_by": [],
            "relevant_files": ["example/engine.py"]
        }
    ],
    "manual_checks": [
        {
            "id": "MC-001",
            "title": "Verify installed wrapper preview",
            "item_ids": ["AC-001"],
            "platform": "windows",
            "instructions": [
                "Activate the repository virtual environment.",
                "Run example --preview.",
                "Confirm the external process is not created."
            ],
            "expected": "The command is printed and no external process runs.",
            "status": "pending",
            "safety": "non_destructive",
            "notes": ""
        }
    ],
    "relevant_docs": ["docs/HANDOFF.md"]
}
```
<!-- development-ledger:state:end -->

## Design Notes

Normal Markdown remains available for architecture and implementation detail.
