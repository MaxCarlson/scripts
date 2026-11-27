# Status

Selective-validation evidence-integrity corrections are complete on `feature/managed-selective-validation-20261128`, pushed at `c381241d`. The follow-up corrects evidence reuse, pytest-process provenance, redaction, temporary-root placement, and cross-platform PYTHONPATH handling. No Toolkit or retirement-candidate files are changed.

## Current findings

- Existing named/full `Invoke-Tests.ps1` mutates shared per-target `LATEST.*` and history, and target bootstrap includes installs/uninstalls/cleanup.
- `validation-targets.json` already identifies pytest-capable named targets and their working directories/pytest arguments.
- Toolkit `toolkit_cli/verify_imports.py` uses `importlib.util.find_spec` and verifies module origins against expected roots/environment paths.
- `development_ledger` consumes JUnit and records per-plan append-only events; selective evidence will not invoke it automatically.
- Shared-package build/release validation intentionally remains separate from source pytest execution.

## Verification

- `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest scripts_setup\tests\managed_validation_test.py -o addopts= -p no:cacheprovider -q --basetemp <unique %TEMP% root>` — 15 passed, including a real pytest subprocess with runtime provenance and external temp-root evidence.
- `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m ruff check --no-cache scripts_setup\selective_validation.py scripts_setup\tests\managed_validation_test.py` — passed.
- `validation-targets.json` parsed as JSON; PowerShell AST parsing of `Invoke-Tests.ps1` passed.
- `git diff --check` passed.

## Next

The branch is ready for review and Agent-Environment adoption. Toolkit-native adoption remains separable. Keep generated run receipts and temp directories outside source commits.
