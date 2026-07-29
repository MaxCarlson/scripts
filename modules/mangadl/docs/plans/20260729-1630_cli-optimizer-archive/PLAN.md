# MangaDL CLI, Optimizer, and Archive UI Plan

## Objective

Reduce the normal `mangadl run` surface, replace the old `--auto-tune` flag cluster with explicit online optimization and benchmarking modes, and turn `mangadl archive` into an interactive archive browser.

## Public CLI Shape

### Normal run

```text
mangadl run -i URLS.txt -d DESTINATION -a ARCHIVE [-w WORKERS] [-I IMAGE_WORKERS]
```

The normal help surface contains only routine inputs, destination/archive selection, and the two live concurrency controls. Run IDs are always generated automatically.

### Advanced normal run

```text
mangadl run config [normal inputs] [advanced options]
```

Advanced options include backend forcing, state/log paths, retries, retry delay, process launch staggering, safety ceilings, gallery-dl configuration/rate limits, cookies, HDPornComics executable/threads, dry-run, no-UI, quiet, verbose, and log anonymization.

### Adaptive optimization

```text
mangadl run optimize [normal inputs] [optimization bounds]
```

Optimization is always online against the real source. It uses a discrete `(workers, image_workers)` state space, bounded by user-supplied minimums/maximums and the logical-CPU concurrency budget. Selection begins with coverage, then favors neighbors/UCB around the best observed state while exponentially reducing deliberate exploration.

Optimization evaluation modes:

- `complete`: a worker keeps the settings it started with until its representative series download completes.
- `timed`: a candidate runs for a configured duration, is stopped cleanly, and the next state starts from preserved partial data or an isolated probe directory.

After optimization, the best state is applied to the real resumable run.

The optimizer dashboard must show:

- total valid states;
- unique states tried;
- total completed trials;
- current state and selection reason;
- best state and average throughput;
- exploration probability;
- convergence estimate;
- elapsed optimization time.

### Exhaustive benchmark

```text
mangadl run benchmark [normal inputs] [benchmark bounds]
```

Benchmarking tests the bounded state matrix systematically from low to high concurrency, with optional reversed/rotated rounds to reduce ordering bias. It supports the same `complete` and `timed` evaluation modes, writes a durable JSON report, and applies the best state to the subsequent real run unless `--report-only` is selected.

### Advanced optimization/benchmark settings

```text
mangadl run optimize config ...
mangadl run benchmark config ...
```

These expose the same advanced backend/runtime settings as `mangadl run config` without cluttering the routine optimization help.

### Archive browser

```text
mangadl archive -a ARCHIVE
```

The default is an interactive terminal dashboard. It introspects the SQLite archive schema, displays records in a paged table, supports navigation and filtering, shows selected-record details, and can export the current filtered view. Machine-readable summary/list behavior remains available under:

```text
mangadl archive config -a ARCHIVE --json
```

## Backward Compatibility

For one transition release, old flat `mangadl run` advanced flags and `--auto-tune` aliases remain accepted but are suppressed from normal help. They normalize into the new command model and emit a deprecation notice where appropriate.

## Runtime Controls

Normal and optimized real runs preserve live controls:

- `+` / `-`: raise or lower the target outer-worker count;
- `]` / `[`: change the Manga18FX image-worker value used by newly started jobs;
- existing workers keep the image-worker value with which they started;
- outer-worker reductions drain rather than terminate active jobs;
- all changes remain inside the configured worker and logical-CPU budgets.

## Implementation Phases

1. Fix authoritative Manga18FX live progress for resume-only jobs.
2. Introduce a shared run-settings model and concise/nested parser hierarchy.
3. Replace exhaustive-only auto-tune with persistent state/trial models and adaptive selection.
4. Add optimizer/benchmark dashboard and JSON report lifecycle.
5. Add complete-series and timed evaluation engines.
6. Apply the selected state to the normal resumable manager.
7. Add the interactive archive browser and schema-tolerant archive reader.
8. Update documentation, help snapshots, compatibility tests, optimizer tests, archive UI tests, and end-to-end CLI tests.

## Validation Gates

- Existing normal-run behavior remains compatible.
- `mangadl run --help` is materially shorter than the old flat help.
- `mangadl run optimize --help`, `benchmark --help`, and nested `config --help` expose only their relevant options.
- Run IDs cannot be manually supplied to new runs.
- Adaptive exploration decays and state selection converges toward measured maxima in deterministic tests.
- Bounds and logical-CPU constraints exclude invalid states.
- Complete trials never change a worker's image-thread value mid-series.
- Timed trials terminate workers cleanly and retain inspectable partial state/report data.
- Optimizer dashboard state counts and best-state values match the persisted report.
- Archive UI loads real gallery-dl schemas without assuming one fixed column set.
- Full Windows pytest suite passes before merge.
