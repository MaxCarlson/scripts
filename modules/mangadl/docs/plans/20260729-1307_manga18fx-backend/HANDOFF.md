# Manga18FX Backend Handoff

## Branch

`agent/add-manga18fx-backend`

Base: `agent/add-development-ledger-module`

## Implemented Scope

- Native Manga18FX parser/downloader and backend routing.
- Destination-aware resume and deterministic chapter/image naming.
- Bounded per-series image concurrency through `-I/--image-workers`.
- Logical-CPU aggregate concurrency budgeting with one processor reserved.
- Safe outer-worker ceiling, runtime tuning controls, and staggered process startup.
- Fixed-width dashboard rows, per-worker progress/activity rows, runtime concurrency header, and immediate `q` shutdown.
- Bounded preflight auto-tuning with JSON reports and automatic winner application.
- Native completion parsing that distinguishes downloaded, already-existing, and empty output.
- Fixed-width displayed activity-log fields and unknown-total normalization.
- Offline tests covering backend parsing, routing, concurrency, UI, safety limits, stagger behavior, tuning/scoring, and resume classification.

## Confirmed Live Behavior

The user confirmed correct Manga18FX URL-file downloads on Windows 11. These combinations start and download normally on the current B: destination:

- `-w 2 -I 2`
- `-w 2 -I 4`
- `-w 4 -I 1`
- `-w 4 -I 2`
- `-w 4 -I 4`
- `-w 4 -I 5`

A fifth outer worker causes immediate 100% disk utilization and no observable progress, even at `-w 5 -I 1` and `-w 5 -I 2`. Six and eight outer workers exhibit the same or worse behavior. Four remains the safe default outer-worker ceiling for this destination.

A later four-worker run reached approximately 15-17 MiB/s aggregate. One series reported zero new files and then success because all of its images were already present in the final library. The 1.10.1 wrapper now reads the native `downloaded` and `skipped` counts and reports that case as already complete/skipped with an exact final image total.

## Concurrency Interface

- `-w/--workers`: requested simultaneous series jobs; default `2`.
- `-m/--max-workers`: outer-worker safety ceiling; default `4`, hard maximum `8`.
- `-U/--worker-start-delay`: seconds between worker launches; default `2`.
- `-I/--image-workers`: image transfers inside each Manga18FX series; default `4`, range `1-8`.

A plain request above the ceiling is reduced before launch:

```powershell
mangadl run -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -s .\mangadl-state.sqlite3 -w 5 -I 2
```

The effective outer-worker count is four. An experimental fifth worker requires an explicit override:

```powershell
mangadl run -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -s .\mangadl-state.sqlite3 -m 5 -w 5 -U 5 -I 2
```

Runtime controls:

- `+` / `-`: increase or decrease the target outer-worker count.
- `]` / `[`: increase or decrease image workers for newly started Manga18FX jobs.
- Lowering outer workers drains excess active jobs rather than terminating them.
- `q` interrupts immediately through the same cleanup path as Ctrl+C.

## Progress and Resume Semantics

During an active Manga18FX run, the final series-wide image total is not known without preloading every chapter. The UI therefore displays `456 img` rather than the misleading `456/? img`; the second row uses an activity bar until an exact total is available.

At native completion:

- `downloaded > 0, skipped == 0`: succeeded.
- `downloaded > 0, skipped > 0`: succeeded with a resumed/existing-file summary.
- `downloaded == 0, skipped > 0`: already complete, persisted as `skipped_archive` for compatibility.
- `downloaded == 0, skipped == 0`: backend failure, never silent success.

Displayed activity logs use fixed timestamp, state, identity, image-count, byte-count, and rate columns. Existing persisted `N/? img` records are normalized to `N img` in the dashboard.

## Auto-Tune Interface

```powershell
mangadl run -i .\urls8.txt -d .\downloads -a .\mangadl-archive.sqlite3 -s .\mangadl-state.sqlite3 -T -W 1:4 -Y 1:8 -D 8 -Q 2 -K 24
```

- `-T/--auto-tune`: enable preflight tuning.
- `-W/--tune-workers MIN:MAX`: inclusive outer-worker bounds; cannot exceed `--max-workers`.
- `-Y/--tune-image-workers MIN:MAX`: inclusive inner-thread bounds.
- `-D/--tune-seconds`: target sample time per combination.
- `-Q/--tune-rounds`: repeated samples per combination.
- `-K/--tune-sample-images`: representative image cap per active series/candidate.
- `-O/--tune-report`: JSON report destination.

Candidate startup and stagger time count against measured throughput. Near-ties within two percent select the lower-concurrency combination.

## Required Local Validation

From `modules\mangadl`:

```powershell
git pull --ff-only && python -m pip install -e . && pytest --tb=short -q .\tests\
```

Verify the installed version:

```powershell
mangadl --version
```

Expected: `mangadl 1.10.1`.

Then rerun one already-complete Manga18FX series and confirm that it finishes as skipped/already complete with an exact image count rather than `FINISH_SUCCESS ... 0 img`.

Also confirm that the restarted dashboard shows:

- the workers/images-per-worker header,
- two rows per worker,
- aligned first-row separators,
- `M18:<slug>` identities,
- no `/?` or byte `/?` fields,
- aligned displayed activity logs.

## Merge Gate

Do not merge into `main` until:

1. The full Windows pytest suite passes.
2. One already-complete series is classified as skipped/already complete.
3. Worker rows and displayed activity-log columns align in the Windows terminal.
4. The normal `-w 5` request is visibly reduced to four.
5. Worker launches visibly stagger rather than all starting at once.
6. The live auto-tune report completes and applies a valid winner.
