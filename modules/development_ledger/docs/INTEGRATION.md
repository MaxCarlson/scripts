# Validation Dispatcher Integration

## Current repository constraint

This module was initially added without modifying files outside `modules/development_ledger/`. Root-dispatcher, manifest, registry, and instruction changes described here are intentionally deferred.

## Intended execution order

The repository dispatcher should eventually perform each target in this order:

```text
1. Resolve target and active plan.
2. Bootstrap declared dependencies.
3. Run compile, lint, tests, and platform scripts.
4. Preserve complete raw stdout/stderr and exact exit codes.
5. Emit JUnit XML for pytest or other compatible frameworks.
6. Emit generic script-result JSON for PowerShell/shell/custom checks.
7. Invoke development-ledger record as the final summarization step.
8. Display the compact ledger summary and pending manual checks.
9. Return the original validation failure status, even if ledger generation succeeds.
```

The ledger must not hide or overwrite the actual validation exit code.

## Recommended target-manifest additions

Each validation target should eventually declare:

```json
{
    "project_root": "modules/rrbackup",
    "active_plan": "docs/plans/<plan>/00_implementation-plan.md",
    "ledger_output": "docs/plans/<plan>/ledger",
    "junit_outputs": [
        ".pytest_tmp_root/results/pytest.xml"
    ],
    "script_result_outputs": [
        ".pytest_tmp_root/results/powershell.json"
    ]
}
```

Paths should be relative to the target working directory unless the dispatcher explicitly documents another base.

## Pytest invocation

Add a JUnit output path to the existing pytest command:

```text
--junitxml=<isolated-temp-root>/results/pytest.xml
```

Tests may attach item IDs directly with the included plugin. Load it with `-p development_ledger.pytest_plugin` and mark tests as:

```python
@pytest.mark.ledger_item("AC-S2-001", "AC-S2-002")
def test_compatible_entry_points():
    ...
```

The plugin copies those IDs into JUnit properties. The first integration may also rely on plan-declared test patterns.

## PowerShell and custom scripts

Custom checks should emit the generic JSON format documented by `schemas/script-result.schema.json`.

Example:

```json
{
    "schema_version": 1,
    "source": "powershell",
    "suite": "entrypoint-smoke",
    "tests": [
        {
            "id": "powershell:entrypoint-smoke::rrb-help",
            "name": "rrb --help",
            "status": "passed",
            "duration_seconds": 0.42,
            "item_ids": ["AC-S2-002"],
            "message": ""
        }
    ]
}
```

The raw transcript should still be preserved for diagnosis.

## Final ledger command

Conceptually:

```powershell
python -m development_ledger record `
    -p ${ActivePlanPath} `
    -o ${LedgerOutputPath} `
    -r ${RepoRoot} `
    -j ${PytestJunitPath} `
    -s ${PowerShellResultPath} `
    -t ${RawTranscriptPath} `
    -w
```

The `-w/--write` requirement preserves dry-run safety when the CLI is used manually.

## Raw-artifact retention

Recommended policy:

- Always retain the current complete raw report.
- Retain recent failed runs and explicit milestone runs.
- Allow successful verbose reports to expire after their facts are recorded in `RUNS.jsonl`.
- Never delete the permanent run ledger merely because raw logs are pruned.
- Store raw logs outside the plan ledger directory when they are large.

The permanent ledger should remain small because it stores normalized facts and compact messages rather than full stdout.

## Failure behavior

Ledger generation should be best-effort but visible:

- Validation failure + ledger success: return validation failure.
- Validation success + ledger failure: return failure because evidence was not recorded.
- Validation failure + ledger failure: report both failures.
- Missing active-plan state: fail the ledger phase and tell the agent exactly which block is missing.
- Duplicate run ID: fail rather than silently rewriting history.

## Manual validation

After `record` completes, the dispatcher or user-facing wrapper should show the path to `MANUAL_CHECKS.md` and clearly state whether pending checks exist.

A manual result is recorded separately:

```powershell
python -m development_ledger manual -p ${ActivePlanPath} -o ${LedgerOutputPath} -r ${RepoRoot} -i MC-S2-001 -s passed -n "Verified wrappers" -w
```

## Migration from current `LATEST.*`

A low-risk transition is:

1. Keep `LATEST.txt`, `LATEST_CONTEXT.md`, and `LATEST_PROGRESS.diff` temporarily.
2. Feed `LATEST.txt` to `--transcript` while JUnit/script JSON generation is added.
3. Treat the new ledger and projections as experimental parallel output.
4. Validate at least two real plan cycles.
5. Stop using context Markdown diffs as the primary history.
6. Retain one current raw transcript and the permanent structured ledger.
