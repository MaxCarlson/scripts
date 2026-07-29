# Plan Document Format

## Goal

The working LLM should update one small machine-readable block inside the active Markdown plan. The rest of the plan remains normal technical prose.

The ledger block is the only recurring structured progress input the LLM must maintain. Generated history and validation documents must not be edited manually.

## Required markers

```markdown
<!-- development-ledger:state:start -->
```json
{
    "schema_version": 1
}
```
<!-- development-ledger:state:end -->
```

The markers and JSON fence are exact. Only one state block is allowed per active plan.

## Complete schema example

```json
{
    "schema_version": 1,
    "plan_id": "rrbackup-consolidation",
    "title": "RRBackup Consolidation",
    "project_root": "modules/rrbackup",
    "stage": {
        "id": "S2",
        "title": "Compatibility Merge and CLI",
        "status": "in_progress"
    },
    "session": {
        "actor": "remote_llm",
        "mode": "hybrid",
        "objective": "Add the canonical backup entry point while preserving legacy CLIs.",
        "hypothesis": "A shared parser can preserve aliases without duplicating command implementations.",
        "target_ids": [
            "AC-S2-001",
            "AC-S2-002"
        ],
        "environment_dependencies": [],
        "diagnostic_complexity": "normal",
        "relevant_files": [
            "rrbackup/cli.py",
            "tests/cli_test.py"
        ]
    },
    "items": [
        {
            "id": "AC-S2-001",
            "kind": "criterion",
            "title": "The backup entry point exposes the canonical command hierarchy.",
            "implementation": "implemented",
            "tests": [
                "pytest:tests/cli_test.py::test_backup_root_help",
                "glob:pytest:tests/cli_test.py::test_backup_*"
            ],
            "manual_checks": [],
            "blocked_by": [],
            "relevant_files": [
                "rrbackup/cli.py",
                "pyproject.toml"
            ]
        },
        {
            "id": "AC-S2-002",
            "kind": "criterion",
            "title": "Legacy rrb and rrbackup entry points retain compatible behavior.",
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
                "rrbackup/compatibility.py"
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
                "Run rrb --help and rrbackup --help.",
                "Confirm both commands resolve to the current editable installation."
            ],
            "expected": "Both wrappers execute successfully and expose the compatible hierarchy.",
            "status": "pending",
            "safety": "non_destructive",
            "notes": "This verifies generated wrappers and PATH behavior that pytest cannot fully prove."
        }
    ],
    "relevant_docs": [
        "docs/HANDOFF.md",
        "docs/CLI_ARCHITECTURE_AND_AUDIT_COVERAGE.md"
    ]
}
```

## Stable IDs

Use stable IDs that survive wording and file changes.

Recommended prefixes:

- `F-...`: feature
- `R-...`: requirement
- `AC-...`: acceptance criterion
- `T-...`: implementation task when it must be tracked
- `MC-...`: manual check

Do not renumber existing IDs merely to make a list visually contiguous.

## Implementation states

Allowed values:

- `planned`
- `in_progress`
- `implemented`
- `blocked`
- `deferred`

`implemented` means source work is present. It does not mean the item has passed automated or manual verification.

## Test pattern syntax

An item may be linked to tests in three ways:

1. Exact normalized ID:

```text
pytest:tests/engine_test.py::test_preview
```

2. Glob pattern:

```text
glob:pytest:tests/engine_test.py::test_preview_*
```

3. Whole suite:

```text
suite:entrypoint-smoke
```

Tests may also declare item IDs directly in JUnit properties or generic script-result JSON. Either direction is sufficient for matching; using both provides traceability validation.

## LLM update procedure

Before finishing a source-editing pass, the working LLM must update:

1. `stage.status` when stage state changes.
2. `session.actor` and `session.mode`.
3. `session.objective` with the bounded work just performed.
4. `session.hypothesis` when the pass is diagnostic.
5. `session.target_ids` with only the items addressed by the pass.
6. `session.environment_dependencies` when local evidence is required.
7. Each affected item’s `implementation` state.
8. Test patterns for newly added or renamed validation.
9. Manual checks for behavior automation cannot verify.
10. Relevant files and documents needed by the next agent.

The LLM must not manually add test results, progress scores, run-history entries, or routing decisions to this block.

## Keep the block small

Do not place the following in the state block:

- architectural essays,
- complete source diffs,
- full error logs,
- test stdout,
- repeated historical attempts,
- generated summaries,
- transient commentary.

Those belong in normal plan prose, raw artifacts, or generated ledger outputs.
