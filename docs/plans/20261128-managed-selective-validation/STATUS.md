# Status

Selective validation is integrated directly into Scripts `main` at `278978a3e439731a6b2aeace45751e56826a30b0` and pushed. The follow-up corrects evidence reuse, pytest-process provenance, redaction, temporary-root placement, and cross-platform PYTHONPATH handling. Toolkit adoption remains independent; no retirement-candidate files were changed.

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
- Candidate was a fast-forward from current main `e299c256`; the last feature-branch changes after the qualified test commit `c381241d` were plan-status documentation only. The validated implementation and tests are unchanged in the integrated tree.
- Native PowerShell CLI availability was checked with `Invoke-Tests.ps1 -ListTargets` and `Get-Command .\Invoke-Tests.ps1`; the `Selective`, `Target`, and `PytestNodeId` parameters are available.

## Next

Agent-Environment adoption can use `Invoke-Tests.ps1 -Selective` independently of Toolkit-native validation. Keep generated run receipts and temp directories outside source commits.

## Parallel worker expansion — 2026-11-27

The isolated successor branch `feat/managed-parallel-validation-20261127` is
based on Scripts `8e6fb41cff749aa6e3b62b391a9341a5be95d531`. The existing
selective runner now accepts `-Workers 0..16` (serial remains the default),
includes worker count in evidence identity, uses local `loadfile` xdist with
worker restarts disabled, and requires controller plus per-worker import and
temp-root receipts. Passing parallel receipts survive evidence reuse.

The public wrapper was run in an isolated synthetic consumer at workers 0, 12,
and 16. Each run passed the same two tests. End-to-end durations were 1.703s,
5.656s, and 6.187s; worker receipt counts were 1, 13, and 17, with 12 or 16
unique worker temp roots. The short sample shows process startup cost, not a
performance benefit. The existing report does not record peak memory.

Focused `scripts_setup/tests/managed_validation_test.py`: 18 passed, including
a real 12-worker pytest subprocess. Synthetic public wrapper runs at 12 and 16
also passed. A normal `development-ledger` wrapper invocation was blocked by
the existing Scripts venv's editable import resolving to the primary checkout;
provenance correctly rejected it and the environment was left unchanged. Its
blocked receipt remains local under `docs/test-results/selective/` and is not a
source commit. A lightweight serial Toolkit invocation and Scripts wrapper were
also run concurrently; both exited 0 with isolated evidence.
