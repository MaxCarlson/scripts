# Benchmark context and budget safety

> Historical record. The fixed 2 GiB GPU and 4 GiB combined-memory reserves are superseded by
> `20261029-runtime-resource-policy/STATUS.md`; context verification and LM Studio estimate parsing
> remain active.

## Goal

Prevent LM Studio benchmark loads from silently using a model's very large native context, validate preloaded model context before dispatch, and keep strict budget outcomes interpretable.

## Confirmed evidence

- `EXP_20261020_020814`: Devstral metadata advertised `max_context_length=393216`; the benchmark load command in the current source omits a context argument. Telemetry recorded RAM at 100%, minimum available RAM below 1 MiB, and peak RTX 5090 allocation of 31.29 GiB. This strongly implicates an oversized load configuration, though the saved run does not establish LM Studio's exact KV-cache allocation formula.
- `EXP_20261020_022222`: The user had manually loaded Devstral at 16,384 context and the benchmark reused that instance. The trial passed verification and scope audit, with RAM 51.8–54.2% and GPU allocation about 20 GiB, but completed at 60.437 seconds under `canonical-60s` and correctly scored `timed_out`. This run does not validate the benchmark's load command or prove it set the 16k context.
- `EXP_20261020_021827`: The worker job ended as `failed` after 6.078 seconds; no edit was made. The saved session lacks the underlying provider error, so the specific early-exit cause remains unknown. The run does not prove an HTTP 400 or a context-window rejection.
- Benchmark-created text subprocesses already use explicit UTF-8 with replacement or capture bytes and decode explicitly. The reported `_readerthread` traceback tail is absent, so it remains unconfirmed as a cause of these three runs.

## Implementation scope

1. Add a default 16,384-token load context and an explicit `-c/--context-length` override for experiment plan/run. Record the requested and effective context in experiment and per-model run metadata; reject requests above a model's advertised maximum.
2. Always include LM Studio's `--context-length` on benchmark-initiated loads. Reuse a preloaded instance only when its reported context exactly matches the requested context; otherwise fail clearly unless transitions are authorized, then unload and load with the requested context. Verify the context reported after load before worker dispatch.
3. Add a read-only `lms load --estimate-only` preflight for transitions. Parse its documented GPU and total memory estimates and fail closed when estimates cannot be read or exceed measured resource headroom. Preserve current host-RAM guards and never load/unload during planning.
4. Add `-b/--budget-profile` and `-c/--context-length` to experiment plan/run and define `canonical-120s` as the new default comparison budget. Keep `canonical-60s` available and strict for historical reproducibility; keep `extended-120s` explicitly experimental/ineligible. The deadline remains strict, without success grace.
5. Improve logging of terminal OpenCode job status and available diagnostics. Do not fabricate a provider error when OpenCode does not expose one.

## Explicitly excluded

- Do not add a completion grace period to canonical scoring.
- Do not compare results that use different budget profiles; persist the budget profile in each variant run.
- Do not change shared OpenCode/LM Studio configuration, model context defaults, or loaded state.
- Do not prune global OpenCode tool schemas or assume benchmark code can control them.
- Do not change UTF-8 behavior that is already correct without a reproducing failure.
- Do not run inference as part of verification.

## Verification

- Add mocked lifecycle tests for estimator invocation/parsing/resource guard, explicit context on load, exact-match preloaded reuse, mismatch refusal/reload, and post-load verification.
- Add parser/metadata tests for `-b` and `-c`, plus logging coverage for a failed OpenCode job with only available status diagnostics.
- Run focused tests, the full `agent_benchmark` test suite, Ruff, and `git diff --check`.

## Status

Follow-up: `EXP_20261020_025442` confirmed successful LMS estimates are emitted on stderr with empty stdout. Parse both captured streams after checking exit code zero; a mocked transition now reproduces the actual stderr-only output. Package patch version 1.9.1. Lifecycle and CLI regressions: 32 passed; Ruff and diff checks passed. No inference or model load/unload was used to verify this fix.

Implementation and offline verification complete on `agent/benchmark-live-stats`, commit `6997a480`, merged into local `main` by merge commit `f824e371`. The installed `lms load --help` confirms `--context-length` and `--estimate-only`; a read-only estimate for Devstral at 16,384 printed 16.54 GiB GPU and total estimates, then exited nonzero with a sandbox `EPERM` while reading the current directory. The implementation treats nonzero estimate exit as a hard block. No inference or LM Studio load/unload has been performed.

## Delivered

- Multi-model plan/run accept `-b/--budget-profile` and `-c/--context-length`, defaulting to `canonical-120s` and a shared 16,384 context cap. Planning records the requested cap and warns on unknown/exceeded model limits. `canonical-60s` remains available and strict; `extended-120s` remains comparison-ineligible.
- LM Studio transitions now require exact requested context, run read-only estimate-only before each load, check 2 GiB free GPU and 4 GiB combined-memory reserves plus existing host RAM limits, load with explicit `--context-length`, and verify the reported context. Matching preloaded models are reused only below the RAM/GPU safety limits. Mismatch or memory uncertainty blocks before worker dispatch.
- Run manifests persist requested and effective context. OpenCode worker failure name/message now flows into trial details and experiment logs when OpenCode supplies it.
- Package version bumped to 1.9.0.

## Verification

- `python -m pytest modules/agent_benchmark/tests -q -rs --basetemp=modules/agent_benchmark/.pytest_tmp_root/context-budget-final2`: 303 passed, 3 skipped (Windows symlink privilege unavailable).
- Focused lifecycle/bridge/CLI/scheduler/budget regressions: 73 passed.
- `modules/benchmark_core/tests`: passed with one historical-report skip.
- `ruff check modules/agent_benchmark/agent_benchmark modules/agent_benchmark/tests`, `git diff --check`, and `py_compile` on changed Python files passed.
- LM Studio read-only estimate command emitted the expected values but failed afterward with sandbox `EPERM`; no actual load was attempted. No inference or model load/unload was performed.
