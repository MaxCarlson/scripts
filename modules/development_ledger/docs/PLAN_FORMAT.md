# Plan Document Format

## Goal

The working LLM updates one small machine-readable block inside the active Markdown plan. The surrounding plan remains normal technical prose for architecture, tradeoffs, and implementation detail.

This block is the only recurring structured progress input the LLM maintains. Validation outcomes, history, progress classifications, and handoff projections are generated automatically.

## Required markers

~~~markdown
<!-- development-ledger:state:start -->
```json
{
    "schema_version": 1
}
```
<!-- development-ledger:state:end -->
~~~

The markers and JSON fence are exact. An active plan contains one state block.

## Complete example

```json
{
    "schema_version": 1,
    "plan_id": "backup-consolidation",
    "title": "Backup Consolidation",
    "project_root": "modules/backup",
    "stage": {
        "id": "S2",
        "title": "Compatibility and CLI",
        "status": "in_progress"
    },
    "session": {
        "actor": "remote_llm",
        "mode": "hybrid",
        "objective": "Add the canonical entry point while preserving legacy CLIs.",
        "hypothesis": "A shared parser can preserve aliases without duplicate command implementations.",
        "target_ids": [
            "AC-S2-001",
            "AC-S2-002"
        ],
        "environment_dependencies": [],
        "diagnostic_complexity": "normal",
        "relevant_files": [
            "backup/cli.py",
            "tests/cli_test.py"
        ]
    },
    "items": [
        {
            "id": "AC-S2-001",
            "kind": "criterion",
            "title": "The canonical entry point exposes the required command hierarchy.",
            "implementation": "implemented",
            "tests": [
                "pytest:tests/cli_test.py::test_root_help",
                "glob:pytest:tests/cli_test.py::test_command_*"
            ],
            "manual_checks": [],
            "blocked_by": [],
            "relevant_files": [
                "backup/cli.py",
                "pyproject.toml"
            ]
        },
        {
            "id": "AC-S2-002",
            "kind": "criterion",
            "title": "Legacy entry points retain compatible behavior.",
            "implementation": "in_progress",
            "tests": [
                "glob:pytest:tests/compatibility_test.py::test_legacy_*",
                "suite:entrypoint-smoke"
            ],
            "manual_checks": [
                "MC-S2-001"
            ],
            "blocked_by": [],
            "relevant_files": [
                "backup/compatibility.py"
            ]
        }
    ],
    "manual_checks": [
        {
            "id": "MC-S2-001",
            "title": "Verify installed Windows entry-point wrappers",
            "item_ids": [
                "AC-S2-002"
            ],
            "platform": "windows",
            "instructions": [
                "Activate the repository virtual environment.",
                "Run each legacy command with --help.",
                "Confirm every command resolves to the current editable installation."
            ],
            "expected": "All wrappers execute successfully and expose compatible commands.",
            "status": "pending",
            "safety": "non_destructive",
            "notes": "This verifies generated wrappers and PATH behavior that pytest cannot fully prove."
        }
    ],
    "relevant_docs": [
        "docs/HANDOFF.md",
        "docs/CLI_ARCHITECTURE.md"
    ]
}
```

## Stable IDs

Use stable IDs that survive wording and file changes:

- `F-...`: feature
- `R-...`: requirement
- `AC-...`: acceptance criterion
- `T-...`: implementation task when task-level tracking is useful
- `MC-...`: manual check

Do not renumber existing IDs merely to make a list contiguous.

## Implementation states

Allowed values:

- `planned`
- `in_progress`
- `implemented`
- `blocked`
- `deferred`

`implemented` means source work is present. It does not mean automated or manual verification passed.

## Session fields

The source-editing agent updates:

- `actor`: `remote_llm`, `local_llm`, `user`, or another repository-defined actor
- `mode`: normally `hybrid`, `local`, `remote`, or `manual`
- `objective`: the bounded work completed or attempted in this pass
- `hypothesis`: the distinct diagnostic theory tested, when applicable
- `target_ids`: only the plan items addressed by this pass
- `environment_dependencies`: local facts needed to diagnose or verify the work
- `diagnostic_complexity`: `mechanical`, `normal`, `complex`, `deep`, or `critical`
- `relevant_files`: the narrow source/test area associated with the pass

## Test mappings

An item may identify expected tests in three ways.

### Exact normalized test ID

```text
pytest:tests/engine_test.py::test_preview
```

### Glob pattern

```text
glob:pytest:tests/engine_test.py::test_preview_*
```

### Whole validation suite

```text
suite:entrypoint-smoke
```

Tests may also declare item IDs directly through JUnit properties or generic script-result JSON. Using both plan-to-test and test-to-plan links enables bidirectional traceability checks.

## Manual checks

A manual check requires:

- stable ID,
- linked plan-item IDs,
- platform or environment,
- exact instructions,
- expected result,
- safety classification,
- state: `pending`, `passed`, `failed`, `blocked`, or `waived`.

Do not mark a check passed in the plan merely because an LLM believes it should work. Record the result through an immutable manual-check event after execution.

## Required LLM update procedure

Before finishing a source-editing pass, update:

1. Stage state when it changed.
2. Session actor and mode.
3. Bounded objective.
4. Diagnostic hypothesis when applicable.
5. Target item IDs.
6. Affected implementation states.
7. Test mappings for new or renamed tests.
8. Environment dependencies.
9. Manual checks for behavior automation cannot establish.
10. Relevant files and documents for the next agent.

Do not manually add:

- test outcomes,
- progress scores,
- failure fingerprints,
- run-history entries,
- routing decisions,
- complete logs,
- source diffs.

Those are generated or retained as supporting artifacts.
