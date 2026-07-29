# Manga18FX Backend Handoff

## Branch

`agent/add-manga18fx-backend`

Base: `agent/add-development-ledger-module`

## Implemented Files

- `modules/mangadl/mangadl/manga18fx.py`
- `modules/mangadl/mangadl/backends.py`
- `modules/mangadl/mangadl/worker.py`
- `modules/mangadl/tests/manga18fx_test.py`
- `modules/mangadl/tests/backends_test.py`
- `modules/mangadl/tests/worker_test.py`
- `modules/mangadl/tests/conftest.py`
- `modules/mangadl/pyproject.toml`
- `modules/mangadl/mangadl/__init__.py`

## Behavior

A normal auto-routed invocation now accepts Manga18FX series URLs:

```powershell
mangadl run -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -s .\mangadl-state.sqlite3
```

Each series is written as one top-level manga directory. Each chapter receives a naturally ordered numeric prefix, and each image receives a zero-padded numeric filename. The native backend uses the existing `-C/--cookies` Netscape/Mozilla cookies-file option when supplied.

## Validation State

- The user confirmed that the Manga18FX URL-file workflow is downloading correctly on Windows 11.
- The initial full-suite run exposed a Windows pytest base-temp parent-directory failure and one environment-dependent gallery-dl extractor assertion.
- The base-temp path is now selected by a module-local pytest hook, which creates its parent before `tmp_path` fixtures initialize.
- The gallery-dl routing test now mocks `extractor.find`, testing mangadl's routing contract rather than the installed gallery-dl catalog.
- An isolated replica of the corrected pytest hook and routing tests passed: `11 passed`.
- The complete mangadl suite must still be rerun in the user's checkout before merge.

## Required Local Validation

From `modules/mangadl` after pulling the latest branch:

```powershell
pytest --tb=short -q .\tests\
```

After that passes, rerun one already-downloaded Manga18FX URL and confirm the summary reports existing files as skipped rather than downloading them again.

## Risks

- Manga18FX can change HTML structure or add anti-bot behavior.
- Browser-cookie extraction is not implemented for this backend; use an exported Netscape/Mozilla cookie file if anonymous requests fail.
- Do not merge into `main` until the complete Windows pytest suite passes.
