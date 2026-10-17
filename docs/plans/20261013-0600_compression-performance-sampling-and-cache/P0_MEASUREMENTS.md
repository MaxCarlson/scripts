# P0 current-run diagnostics baseline — 2026-10-17

Branch `compression-pipeline-and-cli-20261017`; compresser0.27.0/MangaDL1.53.0.
Generated fixtures only; no production target scanned or modified.

## Reproduce

```powershell
.venv/Scripts/python.exe modules/compresser/tests/pipeline_benchmark.py -r 3 -t 1 2 4 8
.venv/Scripts/python.exe modules/compresser/tests/pipeline_benchmark.py -M -r 3 -t 1 2 4 8
```

The first uses standalone compression; `-M` requires the installed MangaDL adapter.
Each matrix uses the same four generated fixture shapes, fresh per-repetition trial
DBs and saved-header inventories, then warm-cache/trusted-population runs. Retained
sizes/formats/SSIM/failure counts agree across worker settings; no failed trials.
Inventories are serial in P0 regardless of the requested encoder worker count.

## Observations

Medians of3 repetitions; seconds, WebP lossless effort0, default512MiB aggregate:

| Adapter / fixture | Workers requested | Inventory | Fresh-trial analysis | Warm trust/cache |
| --- | ---: | ---: | ---: | ---: |
| Standalone /64 small PNG | 1 | 0.0794 | 0.3834 | 0.1146 |
| Standalone /64 small PNG | 8 | 0.0908 | 0.3615 | 0.1367 |
| MangaDL /64 small PNG,8 galleries | 1 | 0.1303 | 0.4084 | 0.1243 |
| MangaDL /64 small PNG,8 galleries | 8 | 0.1557 | 0.4164 | 0.1702 |
| MangaDL /3 larger PNG | 1 | 0.0605 | 0.1441 | 0.0949 |
| MangaDL /3 larger PNG | 8 | 0.0637 | 0.1444 | 0.0955 |
| MangaDL /9 nested mixed JPEG/WebP/PNG | 1 | 0.0736 | 0.1746 | 0.0950 |
| MangaDL /9 nested mixed JPEG/WebP/PNG | 8 | 0.0816 | 0.1698 | 0.1103 |

The standalone64-image inventory uses2 inventory connections/commits and134 SQL
statements; MangaDL's equivalent8-gallery scan uses10 connections/commits and166
statements. A representative standalone64-image fresh-trial run measured0.151s
worker cache work versus0.0156s encoding; these extremely cheap generated inputs
make persistence overhead visible. The earlier review's256-image stat-count probe
is recorded in plan03; it is a separate instrumented experiment.

RSS sampled every10ms was roughly58–62MB for representative standalone1-worker
cases, including process baseline. Sampling can miss peaks. Full per-run current
phase/counter/settings/runtime records were captured in this plan's ignored
execution workspace; this summary records the useful conclusions durably.

## Decisions for subsequent work

- P2: reduce repeated path queries and per-gallery connection setup before increasing
  header concurrency; compare both adapters, not standalone alone.
- P3: batch/overlap readonly preparation outside cache locks; putting the same
  serialized cache calls into a pool is not evidence of a speedup.
- P5: keep immediate durable trial saves; candidate reuse avoids repeated encoding
  without silently removing the user's realtime persistence guarantee.
- Keep512MiB default and bounded existing encoder admission. No evidence here
  supports a silent memory increase or a process pool.
- Repeat identical benchmarks after each optimization and report both improvements
  and regressions. Inventory differences across requested-worker rows are noise:
  that stage is still serial, not proof of inventory scaling.

## Limits

Python3.12.10 on Windows; runtime versions are included in the JSON reports. These
are small, simple generated inputs on the local workspace volume, not the production
B: library or representative complex screentones. Fresh trial caches are not cold
OS caches. Library `pipeline.wall_seconds` is captured at report construction;
benchmark command wall/CPU measurements enclose the entire CLI call and cleanup.
No guaranteed ETA, peak RSS, production throughput or statistical sampling accuracy
is established by these measurements.
