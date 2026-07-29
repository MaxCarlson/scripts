# Manga18FX Backend Handoff

## Branch

`agent/add-manga18fx-backend`

Base: `agent/add-development-ledger-module`

## Implemented Files

- `modules/mangadl/mangadl/manga18fx.py`
- `modules/mangadl/mangadl/backends.py`
- `modules/mangadl/mangadl/cli.py`
- `modules/mangadl/mangadl/worker.py`
- `modules/mangadl/tests/manga18fx_test.py`
- `modules/mangadl/tests/image_workers_test.py`
- `modules/mangadl/tests/backends_test.py`
- `modules/mangadl/tests/worker_test.py`
- `modules/mangadl/tests/conftest.py`
- `modules/mangadl/pyproject.toml`
- `modules/mangadl/mangadl/__init__.py`
- `modules/mangadl/README.md`

## Behavior

A normal auto-routed invocation accepts Manga18FX series URLs:

```powershell
mangadl run -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -s .\mangadl-state.sqlite3
```

Each series is written as one top-level manga directory. Each chapter receives a naturally ordered numeric prefix, and each image receives a zero-padded numeric filename. The native backend uses the existing `-C/--cookies` Netscape/Mozilla cookies-file option when supplied.

Manga18FX now has two concurrency controls:

- `-w/--workers`: simultaneous series jobs; default `2`.
- `-I/--image-workers`: simultaneous image transfers within each Manga18FX series; default `4`, valid range `1-8`.

```powershell
mangadl run -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -s .\mangadl-state.sqlite3 -w 2 -I 4
```

The approximate maximum number of simultaneous Manga18FX image transfers is `workers × image-workers`. Chapter-page discovery remains serial. Missing images inside each chapter use a bounded thread pool with a separate HTTP opener/cookie jar per thread. Deterministic filenames, existing-file checks, `.part` files, and atomic renames remain unchanged.

## Validation State

- The user confirmed that the original serial Manga18FX URL-file workflow downloads correctly on Windows 11.
- The serial implementation averaged approximately 800 KiB/s with two outer workers, motivating bounded per-series image concurrency.
- The initial full-suite run exposed a Windows pytest base-temp parent-directory failure and environment-dependent gallery-dl tests; those test-harness defects have been corrected.
- Offline tests were added for `-I` parsing, the default value, worker-environment propagation, actual concurrent overlap, and the maximum value.
- The complete mangadl suite must be rerun in the user's checkout after the concurrency changes before merge.

## Required Local Validation

From `modules/mangadl` after pulling the latest branch:

```powershell
python -m pip install -e .
pytest --tb=short -q .\tests\
```

After that passes, rerun the URL file using the conservative default:

```powershell
mangadl run -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -s .\mangadl-state.sqlite3 -w 2 -I 4
```

Compare aggregate throughput with the prior serial baseline. If the source remains responsive, try `-I 6` and then `-I 8`; reduce the value if rate-limit, timeout, or transient server errors increase.

Also rerun one already-downloaded Manga18FX URL and confirm existing files are skipped rather than downloaded again.

## Risks

- Aggregate concurrency multiplies across outer and inner workers; `-w 4 -I 8` could attempt roughly 32 simultaneous image transfers and is not recommended as a starting point.
- Manga18FX can change HTML structure or add anti-bot behavior.
- Browser-cookie extraction is not implemented for this backend; use an exported Netscape/Mozilla cookie file if anonymous requests fail.
- Do not merge into `main` until the complete Windows pytest suite and one live concurrency run pass.
