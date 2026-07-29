# Manga18FX Backend Handoff

## Branch

`agent/add-manga18fx-backend`

Base: `agent/add-development-ledger-module`

## Current Version

`mangadl 1.11.0`

## Implemented Scope

- Native Manga18FX parser/downloader and automatic backend routing.
- Destination-aware resume and deterministic chapter/image naming.
- Bounded per-series image concurrency through `-I/--image-workers`.
- Logical-CPU aggregate concurrency budgeting with one processor reserved.
- Safe outer-worker ceiling, runtime controls, and staggered process startup.
- Fixed-width two-row worker dashboard and aligned displayed activity logs.
- Immediate `q` shutdown through the Ctrl+C cleanup path.
- Authoritative native Manga18FX cumulative progress during download and resume scans.
- Native completion classification for downloaded, already-existing, and empty output.
- Concise `run` CLI with mode-specific `optimize`, `benchmark`, and nested `config` help surfaces.
- Online adaptive optimizer with decaying exploration, neighboring-state search, UCB selection, convergence reporting, and durable JSON reports.
- Online exhaustive benchmark with bounded states and alternating ascending/descending rounds.
- Interactive schema-tolerant gallery-dl archive browser.
- Compatibility aliases for the former flat auto-tune flags.
- Offline tests for backend parsing, resume reporting, concurrency, UI, CLI hierarchy, optimization, and archive browsing.

## Confirmed Live Behavior

The user confirmed correct Manga18FX URL-file downloads on Windows 11. These combinations start and download normally on the current B: destination:

- `-w 2 -I 2`
- `-w 2 -I 4`
- `-w 4 -I 1`
- `-w 4 -I 2`
- `-w 4 -I 4`
- `-w 4 -I 5`

A fifth outer worker causes immediate 100% disk utilization and no observable progress, even at `-w 5 -I 1` and `-w 5 -I 2`. Four remains the safe default outer-worker ceiling for this destination.

A four-worker run reached approximately 15-17 MiB/s aggregate. Resume-only workers advanced through many chapters while showing zero bytes because all processed files already existed in the final library. Version 1.10.2 added cumulative native progress so image counts and processing rate advance during that phase while network bytes/s correctly remains zero.

## Concise Run Interface

```powershell
mangadl run -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -w 4 -I 4
```

Normal help exposes only input, destination/archive, and routine concurrency controls. New run IDs are always generated and cannot be supplied manually.

Advanced settings are organized under:

```powershell
mangadl run config --help
```

The advanced surface contains state/log locations, backend forcing, retries, launch staggering, safety ceilings, gallery-dl configuration/rate limits, cookies, HDPornComics settings, dry-run, no-UI, quiet, verbose, and reserved compatibility settings.

The former flat advanced flags remain accepted but hidden for one transition release.

## Runtime Controls

- `+` / `-`: increase or decrease the target outer-worker count.
- `]` / `[`: change image workers for newly started Manga18FX jobs.
- Existing workers retain the image-worker value with which they started.
- Lowering outer workers drains excess active jobs rather than terminating them.
- All adjustments remain bounded by the worker ceiling and logical-CPU budget.
- `q` interrupts immediately through the same cleanup path as Ctrl+C.

## Progress and Resume Semantics

During Manga18FX processing:

- `images_done` is cumulative downloaded plus valid already-existing images processed so far.
- bytes and MiB/s represent only data transferred during the current job.
- native progress messages show cumulative downloaded, existing, processed, and discovered counts.
- exact series-wide totals appear at completion; active rows do not display misleading `/?` denominators.

At native completion:

- `downloaded > 0, skipped == 0`: succeeded.
- `downloaded > 0, skipped > 0`: succeeded with a resume summary.
- `downloaded == 0, skipped > 0`: already complete, stored as `skipped_archive` for compatibility.
- `downloaded == 0, skipped == 0`: backend failure.

## Adaptive Optimize Interface

```powershell
mangadl run optimize -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -p 1 -m 4 -P 1 -M 8
```

Bounds:

- `-p/--min-workers`
- `-m/--max-workers`
- `-P/--min-image-workers`
- `-M/--max-image-workers`

Evaluation modes:

- `-E complete`: workers retain their launch settings until their representative series finishes.
- `-E timed -D SECONDS`: candidate subprocesses run for a bounded interval, terminate cleanly, and the next state starts.

`-Q/--trials` controls adaptive trial count. Exploration decays exponentially. Selection uses low-to-high warm-up coverage, deliberate exploration, neighboring states around the current best, and UCB exploitation. The dashboard reports total/tried states, completed/planned trials, current and best states, best average speed, exploration, convergence, current trial rate, and active workers.

Advanced optimizer settings use:

```powershell
mangadl run optimize config --help
```

## Systematic Benchmark Interface

```powershell
mangadl run benchmark -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -p 1 -m 4 -P 1 -M 8 -E timed -D 30 -Q 2
```

Benchmark mode tests each valid state. The first matrix round runs upward by aggregate concurrency, and later rounds alternate direction. `-Q` is the matrix-round count.

Both modes include launch-stagger time in scores, rotate representative URL order, persist every trial, prefer lower aggregate concurrency within two percent of peak throughput, and then prefer fewer outer workers.

The selected state is applied to the normal resumable run unless `-o/--report-only` is supplied.

## Interactive Archive Browser

```powershell
mangadl archive -a .\mangadl-archive.sqlite3
```

Default behavior is an interactive paged browser with record details, filtering, navigation, and JSON export. Machine-readable/non-interactive controls are under:

```powershell
mangadl archive config --help
```

## Validation Report Status

The connected branch diff does not currently contain a newly added or modified validation-report file beyond the implementation/docs/tests listed in the branch comparison. The report the user said was pushed therefore has not been consumed; verify its branch/path during the next local handoff if it is not included after pull.

## Required Local Validation

From `modules\mangadl`:

```powershell
git pull --ff-only && python -m pip install -e . && pytest --tb=short -q .\tests\
```

Expected version:

```powershell
mangadl --version
```

```text
mangadl 1.11.0
```

Check help organization:

```powershell
mangadl run --help
mangadl run config --help
mangadl run optimize --help
mangadl run optimize config --help
mangadl run benchmark --help
mangadl run benchmark config --help
mangadl archive --help
mangadl archive config --help
```

Preview a bounded benchmark without downloading:

```powershell
mangadl run benchmark config -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -p 1 -m 4 -P 1 -M 8 -E timed -D 8 -Q 1 -n
```

Then run a small report-only live benchmark:

```powershell
mangadl run benchmark config -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -p 2 -m 4 -P 2 -M 4 -E timed -D 8 -Q 1 -o
```

## Merge Gate

Do not merge into `main` until:

1. The full Windows pytest suite passes.
2. One resume-only Manga18FX worker visibly advances processed image counts while byte speed remains honest.
3. One already-complete series is classified as skipped/already complete.
4. Normal worker rows and displayed activity-log columns align in Windows Terminal.
5. `run --help` is concise and nested config help exposes advanced settings.
6. The normal `-w 5` request is visibly reduced to four.
7. Worker launches visibly stagger rather than all starting simultaneously.
8. A bounded live optimize or benchmark report completes and selects a valid state.
9. The interactive archive browser opens and filters the selected archive.
