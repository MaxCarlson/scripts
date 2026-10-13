# URL-File Audit and Repair Status

Plan created on 2026-10-09 for branch
`codex/kavita-module-mangadl-collections-20261009-0349`.

## Current state

- Stage: Stages 1–3 implemented; next is repair planning and execution.
- Added audit-only `-u/--url-file` aliases while preserving `-i/--input-file`
  and `run -u/--url` behavior.
- Fixed the sibling-module import failure from the user's attempted run:
  `modules/kavita` is a repository project root and previously resolved as an
  empty namespace package when `modules/` was on `sys.path`. Added a small
  package-root re-export shim and a regression test for this import layout.
- Audit JSON includes per-URL provenance and folder matches, expected image
  totals where nhentai metadata resolves, and missing/corrupt/duplicate/extra
  numbered page findings. Completeness remains unknown when source totals are
  unavailable and local numbering gives no evidence of gaps. Findings remain
  read-only and no result is marked repair-eligible.
- User's Paradise example (pages 159–192 only) exposed that URL-to-folder
  matching alone falsely implied success. Audit now detects its 1–158 leading
  gap, uses nhentai expected-count metadata when available, and validates image
  data with Pillow. The unreadable page is reported as missing-valid and corrupt.
- Bumped MangaDL to 1.22.0 and declared Pillow as a runtime dependency.
- Missing-URL and duplicate-folder outputs are optional, so the basic audit
  command no longer needs report-output paths. Existing explicit output flags
  continue to work.
- Default audit remains read-only; destination scan produced no extra files in
  the focused no-mutation check.
- No commit, push, merge, or live download approval was given.

## Verification

- `python -m pytest tests/destination_audit_test.py -q -o addopts=""` from
  `modules/mangadl` with `PYTHONPATH='.;..\\kavita;..'`: **7 passed**.
- `python -m mangadl audit --help` with the same `PYTHONPATH`: passed; help
  lists `-u/--url-file` and existing `-i/--input-file`.
- `ruff check mangadl/cli_core.py mangadl/destination_audit.py tests/destination_audit_test.py`:
  **All checks passed**.
- `python -m pytest modules/kavita/tests -q -o addopts="" --basetemp modules/kavita/.pytest_tmp_root/codex-validation`
  with `PYTHONPATH=modules` and `TEMP`/`TMP` inside the workspace: **16 passed**.
- `python -m pytest modules/mangadl/tests -q -o addopts=""` with
  `PYTHONPATH=modules` and `TEMP`/`TMP` inside the workspace: **230 passed**.
- `python -m ruff check modules/kavita/__init__.py modules/kavita/kavita modules/kavita/tests/package_import_test.py modules/mangadl/mangadl/cli_core.py modules/mangadl/mangadl/destination_audit.py modules/mangadl/tests/destination_audit_test.py`:
  **All checks passed**.
- `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest tests -q -o addopts=""`
  from `modules/mangadl`: **232 passed** (pytest emitted a cache-permission
  warning for `.pytest_cache`; test results passed).
- `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m ruff check`
  on the changed audit source and test files: **All checks passed**.
- `git diff --check` in the actual checkout: passed.
- `python -m mangadl audit --help` with `PYTHONPATH=modules`: passed and
  showed the new URL-file alias.
- Before page-integrity checks were implemented, replayed the user's read-only audit on
  `B:\\Hent\\hent1imageperpage\\urls32.txt` against
  `B:\\Hent\\hent1imageperpage` using the branch sources: **38 unique URLs,
  38 folder matches, 0 missing, 0 duplicate-folder groups**. The URL file had
  **16 duplicate lines**, all reported with reason `duplicate`. No report
  output paths were supplied, and the destination was only scanned.
- An initial pytest collection from the repository root failed because the
  module test environment did not include `modules/kavita` on `PYTHONPATH`;
  rerunning from the module root with the dispatcher-equivalent paths passed.
- An initial full-suite run using the sandbox's default temporary directory
  had four unrelated auth/temporary-cleanup failures; rerunning with `TEMP`
  and `TMP` rooted inside the workspace passed all 230 tests.
- User's manual command failed before audit because the installed entry point
  encountered the package-root import collision. The collision is fixed and
  covered locally; the provided command then completed with the read-only
  results above.

## Next action

Proceed to Stage 4: construct exact repair plans and preserve read-only preview
as the default. Do not perform live downloads or archive mutations without the
user's explicit approval.
