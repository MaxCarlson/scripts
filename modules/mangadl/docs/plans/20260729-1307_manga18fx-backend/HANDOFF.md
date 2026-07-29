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
- `modules/mangadl/pyproject.toml`
- `modules/mangadl/mangadl/__init__.py`

## Behavior

A normal auto-routed invocation now accepts Manga18FX series URLs:

```powershell
mangadl run -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -s .\mangadl-state.sqlite3
```

Each series is written as one top-level manga directory. Each chapter receives a naturally ordered numeric prefix, and each image receives a zero-padded numeric filename. The native backend uses the existing `-C/--cookies` Netscape/Mozilla cookies-file option when supplied.

## Validation State

The isolated new parser/naming tests passed: `5 passed`. The full module test suite and live-site smoke test remain local validation requirements.

## Risks

- Manga18FX can change HTML structure or add anti-bot behavior.
- Browser-cookie extraction is not implemented for this backend; use an exported Netscape/Mozilla cookie file if anonymous requests fail.
- Do not run the full URL list until one disposable single-series smoke test succeeds.
