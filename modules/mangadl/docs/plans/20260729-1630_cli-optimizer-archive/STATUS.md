# MangaDL CLI, Optimizer, and Archive UI Status

## State

Implementation complete on `agent/add-manga18fx-backend`; local Windows validation required.

## Version

`1.11.0`

## Implemented

- Concise normal `mangadl run` help surface.
- `mangadl run config` advanced settings surface.
- `mangadl run optimize` adaptive online Manga18FX optimization.
- `mangadl run benchmark` bounded systematic online benchmarking.
- `config` variants for optimize and benchmark.
- Generated-only run IDs for new runs.
- Complete-series and timed candidate evaluation modes.
- Decaying deliberate exploration, low-to-high coverage, neighbor search, and UCB exploitation.
- CPU-budgeted `(workers, image-workers)` state generation.
- Optimizer dashboard with state/trial counts, best/current state, throughput, exploration, and convergence.
- Durable JSON reports updated after every completed trial.
- Automatic application of the selected state to the real resumable run.
- Report-only mode.
- Hidden compatibility aliases for the former flat auto-tune interface.
- Interactive gallery-dl archive browser with navigation, filtering, record details, and JSON export.
- Cumulative Manga18FX processed-image reporting during resume-only scans.
- New offline tests for progress parsing, CLI hierarchy, optimizer selection/reporting, and archive UI behavior.

## Confirmed by Source Review

- New-run parsing does not expose `--run-id`.
- Normal run help suppresses advanced flags while continuing to accept them for one transition release.
- Optimize and benchmark act only on URLs routed to the native Manga18FX backend.
- Candidate state products cannot exceed logical CPUs minus one.
- Benchmark rounds alternate ascending and descending state order.
- Near ties prefer lower aggregate concurrency, then fewer outer workers.
- Timed trials terminate candidate subprocesses before continuing.
- Complete trials retain launch settings until candidate series processes exit.
- Runtime normal-run `+/-` and `[/]` controls remain intact.

## Not Yet Validated

- Full Windows pytest suite after the 1.11.0 changes.
- Actual help output in the installed PowerShell entry point.
- Live adaptive optimizer convergence and report quality.
- Live timed-process termination on Windows.
- Live complete-series optimizer behavior.
- Interactive archive browser against the user's current gallery-dl archive.
- The validation report the user said was pushed is not visible in the connected branch diff.

## Local Validation

```powershell
git pull --ff-only && python -m pip install -e . && pytest --tb=short -q .\tests\
```

```powershell
mangadl --version
mangadl run --help
mangadl run config --help
mangadl run optimize --help
mangadl run optimize config --help
mangadl run benchmark --help
mangadl run benchmark config --help
mangadl archive --help
mangadl archive config --help
```

```powershell
mangadl run benchmark config -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -p 1 -m 4 -P 1 -M 8 -E timed -D 8 -Q 1 -n
```

## Merge Gate

Do not merge until the full test suite, one bounded live optimization/benchmark, resume-only progress, and archive browser have been validated on Windows.
