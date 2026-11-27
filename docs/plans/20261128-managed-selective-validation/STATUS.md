# Status

Implementation is complete on isolated branch `feature/managed-selective-validation-20261128`, pushed at `9ce2847a`. Selective Python execution, manifest contracts for six pytest targets, the early PowerShell dispatch, and the consumer-facing guide are implemented. No named/full validation flow or primary checkout was changed.

## Current findings

- Existing named/full `Invoke-Tests.ps1` mutates shared per-target `LATEST.*` and history, and target bootstrap includes installs/uninstalls/cleanup.
- `validation-targets.json` already identifies pytest-capable named targets and their working directories/pytest arguments.
- Toolkit `toolkit_cli/verify_imports.py` uses `importlib.util.find_spec` and verifies module origins against expected roots/environment paths.
- `development_ledger` consumes JUnit and records per-plan append-only events; selective evidence will not invoke it automatically.
- Shared-package build/release validation intentionally remains separate from source pytest execution.

## Verification

- `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest scripts_setup\tests\managed_validation_test.py -o addopts= -p no:cacheprovider -q --basetemp <unique %TEMP% root>` — 8 passed.
- `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m ruff check --no-cache scripts_setup\selective_validation.py scripts_setup\tests\managed_validation_test.py` — passed.
- `validation-targets.json` parsed as JSON and all six declared import targets were enumerated successfully.
- PowerShell AST parsing of `Invoke-Tests.ps1` passed.
- A real `rrbackup` probe with the existing Scripts interpreter resolved `rrbackup` from this feature worktree; it reported the environment's older editable registration as a warning and passed runtime-origin checks.
- `compileall` and Ruff's normal cache mode could not write cache files under the read-only worktree (WinError 5); pytest imports/exercises the implementation and `ruff --no-cache` passes.
- `git diff --check` passed. PowerShell AST parsing was used instead of dispatching a real test run, which would create a persistent receipt and target temp tree in the read-only worktree.

## Next

The feature branch is ready for review and for Agent-Environment to adopt the documented `test-verify` interface. Keep generated run receipts and temp directories outside source commits.
