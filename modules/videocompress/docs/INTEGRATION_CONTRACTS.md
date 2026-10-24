# Integration Contracts — `videocompress` / `compresser` / `cli_tui`

**Companion to:** [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md), especially §§2–4, 11–13; also [`ESTIMATION_BENCHMARK_PROTOCOL.md`](ESTIMATION_BENCHMARK_PROTOCOL.md) and [`MEDIA_SAFETY_CONTRACT.md`](MEDIA_SAFETY_CONTRACT.md).  
**Status:** Proposed v1 interface design; **not implemented**. The agent must review the current checkout and finalize contracts before editing.  
**Guiding rule:** Preserve image behavior and explicit user authorization. Share stable infrastructure; do not inject videos into image-only Pillow models.

## 1. Packages, ownership and dependency direction

| Package | Owns | Must not own |
|---|---|---|
| `videocompress` (new) | Video CLI, video inventory/FFprobe, encoder recipes, video sampling/estimation, quality, apply, verification, media-specific recovery and video schemas | Image codec engine, MangaDL gallery discovery, TUI rendering internals |
| `compresser` (existing) | Image operations; optional lightweight `video` and `tui` CLI routing | Video FFmpeg measurements, video stream preservation, mandatory heavyweight video dependencies |
| `cli_tui` (existing) | Argparse introspection, navigation/forms, pane state, subprocess output and post-run actions | Compression math, source media operations, file transactions |
| `cross_platform` (existing) | OS-backed target-aware read/write locks, process inspection, platform utilities | Media-specific transaction semantics |
| `termdash` (existing) | Shared progress widgets, multi-worker stats | Media business logic |
| `benchmark_core` (existing) | Generic benchmark record/statistics/report abstractions | FFmpeg execution or resource scheduling; do not break `agent_benchmark` callers |
| `mangadl` (existing) | Gallery download/audit and its image compression integration | Generic video processing |
| `scripts_help` (existing) | CLI discovery/registry | Application execution logic |

**Dependency rule:** `compresser` may lazy-import `videocompress` for `video` commands, preferably an **optional dependency**. `videocompress` should not import `compresser.cli` or depend on image-only `RecipeSpec`, `MeasurementJob`, image inventory or image transactions. Both can import shared infrastructure. If extracting a `compression_core`, prove the abstraction in tests first, add compatibility imports and do not force a broad migration. Do not transitively require `vdedup` with torch/PyNvVideoCodec merely for basic FFmpeg operations.

## 2. Required CLI entry points and dispatch

```text
compresser inventory|plan|estimate|analyze|compare|preview|apply|recover  # unchanged images
compresser video capabilities|inventory|plan|estimate|analyze|compare|preview|apply|recover
compresser tui                                          # images + video
vcompress capabilities|inventory|plan|estimate|analyze|compare|preview|apply|recover
```

`compresser video ...` and `vcompress ...` must normalize to **the same typed video options** and call the same backend. `compresser tui` introspects a single argparse command tree and runs either image or video operations using the same underlying CLI implementation; no independent business logic in the TUI.

**Critical current code detail:** `modules/compresser/compresser/cli.py` parses and then calls image-only `normalize_compression_arguments`; register/dispatch `video` and `tui` before this normalization. Do not pass video arguments through `build_operation_parsers()` image validation. `compresser/cli.py` currently advertises a `2.0.0` embedded version while package metadata says `3.2.0`; reconcile package/version display during authorized edits.

Suggested CLI conventions (exact flags to be finalized with parser tests): `-i/--input`, `-I/--workspace`, `-B/--min-video-bitrate`, `-R/--min-resolution`, `-E/--estimate-tier`, `-M/--max-time`, `-T/--max-trials`, `-r/--plan-id`, `-J/--json`, `-N/--no-ui`, `-w/--write`, `-L/--allow-lossy`. Every user-visible flag has short and long spellings, and operation-specific flags must not conflict inside an operation. Recovery has its own confirmation semantics.

- `inventory`: no target encoding (ever); `files`/`probe`, optional explicitly expensive `deep`.
- `plan`: freeze selections, recipes, filters, population and work budget; no target encoding.
- `estimate`: **default metadata-only or require deliberate sampled-tier opt-in**, following plan; `sampled` mode must enforce hard time/trial/encoded-seconds limits.
- `analyze`/`compare`: exact or bounded recipe trials; external scratch only.
- `preview`: numbered, external sample clips with manifest; no source changes.
- `apply`: dry-run until explicit write authorization; source-affecting lossy operations need separate permission.
- `recover`: inspection by default; write recovery needs scoped confirmation.
- `capabilities`: active FFmpeg/FFprobe encoder/filter/model tests, no blind FFmpeg-listing claims.

## 3. Proposed typed boundaries and persisted schemas

Prefer `@dataclass(frozen=True, slots=True)` for immutable domain objects and explicit `schema_version` for persisted JSON/SQLite records. JSON examples below are **interface proposals**, not already deployed. Keep time/byte units explicit; no display-formatted values in machine records.

| Model | Required fields / invariants |
|---|---|
| `SourceIdentity` | `scope_id`, `relative_path`, `canonical_path`, `stat_fingerprint`, optional `strong_digest`, `fingerprint_method`, `observed_at`; path must remain under target |
| `VideoStream` | `stream_index`, `type`, `codec`, `bit_rate_bps: int | null`, bitrate provenance, durations/time base, video dimensions/FPS/color or audio codec/layout/language/disposition as relevant |
| `VideoAsset` | `schema_version`, `source_id`, source bytes, container, duration, **all** streams, chapters, attached-artwork distinction, probe runtime, inspection status/errors |
| `EligibilityDecision` | `stage`, `status`, `reasons[]`, `applied_thresholds`, unknown handling; status e.g. `eligible`, `excluded`, `unknown`, `unsupported` |
| `VideoRecipe` | `recipe_id`, target codec/encoder, exact preset, rate-control mode/value, pixel/temporal/color policy, container, all stream policy fields, quality/retention thresholds, encoder runtime identity |
| `SamplingWindow` | `source_id`, start/end PTS/timebase, requested vs actual time span, frame count, probability/weight, purpose (`uniform` vs `stress`) and seed |
| `VideoEstimationPlan` | `schema_version`, target/workspace IDs, frozen source membership+fingerprints, recipes, sampled windows, strata/inclusion weights, budgets, plan hash, created time |
| `TrialObservation` | immutable source/recipe/window IDs, actual video payload bytes and/or bps, real clip frames/seconds, runtime/tool identity, elapsed time, quality metrics+model, error/state, cache provenance |
| `Prediction` | source+recipe IDs, `video_bytes`, `nonvideo_bytes`, `mux_overhead_bytes`, predicted whole bytes, uncertainty/coverage method, calibration version, `tier`, `abstention_reason`, decision |
| `VideoApplyJob` | immutable job/source/recipe/target IDs, candidate and rollback paths, journal state, verification evidence, signed hashes, authorized publish policy |
| `CompressionResult` | versioned per-file outcomes and totals: source bytes, predicted bytes, verified output bytes, true/expected savings distinguished, status/errors, report artifacts |

### Minimal example: one video prediction

```json
{
  "schema_version": 1,
  "source_id": "opaque-source-id",
  "recipe_id": "sha256-of-canonical-recipe-and-runtime",
  "tier": "sampled",
  "units": "bytes",
  "source_container_bytes": 3221225472,
  "predicted_video_bytes": 1500000000,
  "predicted_nonvideo_bytes": 200000000,
  "predicted_mux_overhead_bytes": 6000000,
  "predicted_output_container_bytes": 1706000000,
  "predicted_gross_saved_bytes": 1515225472,
  "prediction_interval": null,
  "interval_status": "uncalibrated",
  "decision": "needs_full_validation",
  "calibration_version": null,
  "observation_count": 5,
  "unknowns": ["nonvideo_bytes_approximate"],
  "errors": []
}
```

This is intentionally **not** a fabricated sample of user media. A null interval is correct when no defensible calibrated interval is available. No byte savings become realized until publication is verified.

## 4. Identity, cache and workspace compatibility

- Workspaces must be separate: e.g. `.compresser/<target>/` and `.videocompress/<target>/`, both **outside** the scanned input tree. Workspace manifest binds owner/media type, canonical target root, schema, creation policy and identity digest. Path basename alone is insufficient when targets share a name.
- Maintain separate `inventory.sqlite3` and `trials.sqlite3` and distinct versioned `plans/`, `reports/`, `previews/`, `jobs/`. Do not reinterpret image database records as video or migrate images implicitly.
- A video trial cache key must depend on source fingerprint, sampled PTS/windows, effective recipe and stream handling, FFmpeg binary/build/encoder and driver where needed, metric model/preprocessing, and schema/runtime identity.
- Source changed, recipe changed, tool changed, calibration version changed or selected tracks changed => deterministic invalidation/re-evaluation. Expose cache hit, miss and rejection reasons.
- Plan identity is a hash of canonical frozen inputs; resumed plans must reject drift instead of quietly substituting newer files. Fresh plans may use refreshed inventory.
- A test fixture may use provisional stat identity, but source replacement requires stronger revalidation as defined in [`MEDIA_SAFETY_CONTRACT.md`](MEDIA_SAFETY_CONTRACT.md).

## 5. Typed operation and progress contracts

**Backend API shape (candidate):**

```python
# Sketch only; not executable code or a required exact namespace.

def scan_videos(options: InventoryOptions) -> InventoryReport: ...
def build_video_plan(options: PlanOptions) -> VideoEstimationPlan: ...
def estimate_videos(options: EstimateOptions, emit: ProgressSink) -> EstimateReport: ...
def compare_videos(options: CompareOptions, emit: ProgressSink) -> CompareReport: ...
def preview_videos(options: PreviewOptions, emit: ProgressSink) -> PreviewReport: ...
def apply_videos(options: ApplyOptions, emit: ProgressSink) -> ApplyReport: ...
def inspect_video_recovery(options: RecoveryOptions) -> RecoveryReport: ...
```

Each operation must accept an immutable normalized options type, return a typed result, and raise typed, user-actionable failures. `cli.py` handles argparse and converts results to JSON or terminal reports. Reuse available `termdash` views, but progress producers should not depend on terminal layout.

**Progress event envelope (proposed JSONL contract):**

```json
{"schema_version":1,"sequence":12,"run_id":"opaque-run-id","event_type":"trial_progress","phase":"sample_encode","timestamp":"2026-10-23T20:15:01Z","source_id":"asset-003","recipe_id":"hevc-preset-id","current":35.4,"total":120.0,"unit":"encoded_seconds","estimated":false,"state":"running"}
```

- Producer sequence must be monotonically increasing per run; include run identity, phase and source/recipe/job identity when applicable.
- Progress states: `queued`, `eligible`, `running`, `completed`, `skipped`, `failed`, `interrupted`, `unsupported`, `recovery_required`; define terminal transitions and report counters.
- Encode progress tracks **actual** media time/frames and bytes written, with approximate ETA clearly labeled. Do not claim an exact percentage if duration is unknown or FFmpeg timestamps are unreliable.
- A `--json` run must reserve stdout for valid JSON/JSONL, putting diagnostics on stderr or a sidecar. No ANSI dashboard pollution in machine output.
- Batch summaries distinguish `predicted_savings_bytes` from `realized_savings_bytes`, report no silent partial successes, and include versioned `status`/`reason_code` fields.

## 6. `cli_tui` adapter contract

Use `cli_tui.introspect_parser()` / `CliTuiApp()` and the current `modules/mangadl/mangadl/tui.py` as an implementation pattern. `compresser tui` must:

1. Show existing **image** operations plus `video` operations when `videocompress` is installed; otherwise show a clear optional-install notice without crashing image TUI.
2. Exclude `tui` itself from the recursively introspected menu to prevent self-launch loops.
3. Reuse operation-specific argparse defaults, types, choices, required flags and validation; avoid separate hard-coded TUI-specific constraints.
4. Display source and benefit lower bounds, probe depth, selected recipes and **maximum sample-encode budget** before enabling expensive operations.
5. Show estimator tier (`metadata` vs `sampled`), actual encoding work, cached trials, estimate interval status, unsupported tracks and per-item reasons. Never label a prediction as verified savings.
6. Offer `compare`→`preview` post-run links using structured manifest IDs. Current Tk/Pillow image viewer stays image-only; video previews should open a user-chosen external video player or expose file paths, **not** silently assume image-viewer compatibility.
7. Not interpret `Q` as permission to abandon FFmpeg children. TUI runner/process group cancellation must reach the backend and descendants, and backend must journal interruption. Verify both native Windows and WSL/Linux mechanisms.
8. Keep ordinary CLI/`--json` functioning in noninteractive and headless contexts; TUI dependencies remain lazy/optional where feasible.
9. Verify 80/120/160-column layouts and workspace multiple panes; duplicate simultaneous overlapping apply operations must be prevented by target-aware locks.

**Current blocker to verify:** `cli_tui/cli_tui/app.py` imports `curses` directly and `pyproject.toml` does not declare `windows-curses`; standard Python for Windows lacks built-in `curses`. Test the actual user environment before selecting a dependency or alternate terminal backend. `cli_tui.process_runner.terminate()` uses immediate-child `Popen.terminate()` and is not a proven descendant-tree cleanup mechanism. Audit Windows process groups/Job Objects and Unix session handling; integrate a cooperative backend cancel if possible and require kill-tree fallbacks with tests.

## 7. FFmpeg and external backend adapter boundary

- Use structured **FFprobe JSON** for inventory. Probe every stream; do not inherit `vdedup/probe.py`'s `v:0`-only scope.
- Use an argument vector (never untrusted shell string) for FFmpeg; machine-readable `-progress` transport; no `-y` for user-content publication, and unique scratch outputs.
- FFmpeg encoder discovery must be verified by a bounded smoke encode to scratch; just listing `av1_nvenc` does not establish working driver/FFmpeg/GPU configuration.
- Introduce a `VideoEncodeBackend` protocol/adaptor returning validated `EncodedClip` / `EncodedFile` metadata and event stream; native FFmpeg implementation first. Its API must not depend on TUI or Pillow images.
- Optional `ab-av1` adapter should use documented newline-delimited JSON (`--stdout-format json`) when supported, validate schema/version/runtime, count all nested FFmpeg encode attempts in budgets, and never parse unstable console prose. If API promises don't match installed binary, disable adapter with diagnostic rather than guessing.
- Support runtime identity capture (FFmpeg executable path/hash/build, encoder flags, driver, metric models). Quality metrics need explicit reference alignment and model validity.
- Preserve all source streams by contract; use explicit `-map` and verified container compatibility; the FFmpeg command and validation belong in media backend, not the UI.

## 8. Installation, versioning and test ownership

Follow repository rules in `AGENTS.md`, `REPO_LLM_INSTRUCTIONS.md`, `docs/agent/PYTHON_REPO_STANDARDS.md`, `docs/agent/SCRIPTS_REPO_STANDARDS.md`, and module instructions.

- Register new `[project.scripts]` entry point and `modules/scripts_help/scripts_help/registry/registry.py` entry. Repository standards require a **major version change** for added/removed/renamed console scripts (even where conventional semver might differ); verify intended setup/reinstall behavior.
- Keep package version fields and `__version__` consistent when touched. Declare optional video/TUI extras without making image-only installations unexpectedly require heavy video dependencies.
- Add tests primarily under `modules/videocompress/tests/`; parser/TUI dispatch tests in `modules/compresser/tests/`; changed `cli_tui` tests under its own module. Test generated temp files must stay in their module's permitted temp root.
- Use `validation-targets.json`, `Invoke-Tests.ps1`, `pytest`, `ruff`, `black` and the repository's current commands; include baseline and post-change regression counts with exact environment.
- Required integration tests: `compresser inventory` behaves exactly as before; `mangadl compress` and `mangadl tui` remain functional; `compresser video` and `vcompress` normalize to identical options/results; `compresser tui` operates under native Windows and fails gracefully without optional video package; no orphan FFmpeg process on cancellation.
- Don't commit/push/merge or run live-media apply based on this document alone. Record explicit approval and preserve unrelated worktrees/files.

## 9. Versioned schema and cross-module acceptance gate

Before significant coding, agree to v1 contracts for: (1) `VideoAsset` and stream preservation, (2) `VideoRecipe` and tool identity, (3) `VideoEstimationPlan`/`SamplingWindow`, (4) `TrialObservation`/`Prediction`, (5) `VideoApplyJob` journal, (6) progress event and operation report.

For each contract require `schema_version`, canonical serialization/hash rules, unknown-field behavior, migration/reject policy, ownership and tests. If code evolves, document changes and keep one source of truth rather than diverging CLI/TUI/worker schemas.

**Cross-module gate:** Demonstrate typed API roundtrips (save/load/validate), stable recipe/source/cache identities, CLI/TUI parity, early rejection of invalid/unsupported video and full preservation of existing image behavior before expensive experimental encodes or production-like apply.
