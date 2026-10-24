# Status: Video Compression (`20261024-0920_video-compression`)

## Operational Ledger

- **2026-10-24 14:15 (Stage 3 Corrections Completed & Verified)**
  - Reconciled quantile consistency: verified identity $\text{Output}(q) + \text{Savings}(q) = \text{Source}$ strictly for all quantiles ($p_{10}, p_{50}, p_{90}$).
  - Monotonic ordering verified: $p_{10} \le p_{50} \le p_{90}$ for output size, and $p_{10} \ge p_{50} \ge p_{90}$ for savings.
  - Implemented `SizeReconciliation` tracking `probed_video_bitrate_bps`, `implied_video_bytes`, `reconciled_video_bytes`, and `unaccounted_container_bytes` (e.g. 7.5 Mbps over 1440s = 1.35 GB vs 1.50 GB source with 107.25 MB discrepancy).
  - Renamed decomposition claims: all non-video and mux components labeled as `estimated_stream_heuristics`, `estimated_fallback`, or `estimated_container_model`.
  - Re-classified quality floor violations: `quality_floor_violation` is a heuristic risk signal (`is_hard_infeasible = False`), reserving `is_hard_infeasible = True` solely for true budget overflows ($V_{\max} \le 0$).
  - Labeled `calibration_status = "uncalibrated_scenario_assumptions"` and capped confidence at `medium`/`low`.
  - Added parameterized property-based tests in `test_predictor.py` (57/57 passed in 1.39s).
  - Next Action: Commit Stage 3 corrections and proceed to Stage 4 (Controlled Encoder & Measurement Backend).

- **2026-10-24 13:35 (Stage 3 Completed — Cheap Predictor & Feasibility Screening)**
  - Stage 3 implementation complete: `videocompress/recipes.py`, `videocompress/predictor.py`, `videocompress/plan.py`, and `videocompress/cli.py`.
  - Zero-encode guarantee verified: pure mathematical predictor with zero FFmpeg/subprocess imports; subprocess calls forbidden and tested under monkeypatch guard.
  - Container byte decomposition operational: separate accounting for audio streams (exact or codec/channel fallback), bitmap vs text subtitles, font attachments, and container mux overhead.
  - Missing video bitrate handled conservatively: never substituted silently for container bitrate; explicitly labeled as `container_derived_approximation` when derived.
  - Hard impossibility constraints distinguished from heuristic predictions: non-video budget overflows and bitrate quality floor violations trigger `infeasible` with explicit rejection reasons.
  - Codec transition priors implemented across H.264, HEVC, and AV1 with adjustments for HDR10/10-bit color, low bpppf, and rate control CQ deltas.
  - Plausible uncertainty ranges reported as `[p10, p50, p90]` intervals with honest calibration caveats (`calibration_status = "uncalibrated_metadata_prior"`).
  - CLI operations `vcompress plan` and `vcompress estimate --tier metadata` connected with human-readable tables and structured JSON (`-J`).
  - Unit and integration tests expanded to 51 tests (`51/51 passed` in 1.34s).
  - Full regression verification: `cli_tui` (107/107 passed), `compresser` (523 passed, 1 skipped), `scripts_help` (55/55 passed).
  - Next Action: Present Stage 3 report to user for validation before advancing to Stage 4 (Controlled Encoder & Measurement Backend).

- **2026-10-24 13:20 (Stage 1 & 2 Approved, Findings Addressed)**
  - Addressed User Review Finding 1: Refined `ProcessRunner.terminate()` to use non-forced `taskkill /PID <pid> /T` preserving graceful semantics, while `ProcessRunner.kill()` uses forced `taskkill /F /T /PID <pid>`. Verified with tests.
  - Addressed User Review Finding 2: Decoupled `source_id` from mutable `mtime:size` stat fingerprint; `source_id` is now derived stably from normalized canonical path (`sha256(canonical_path)[:16]`).
  - Addressed User Review Finding 3: Added `-f` / `--force` / `--force-refresh` to `vcompress inventory` CLI and `scan_inventory(..., force_refresh=True)` to force re-probing even when file stat fingerprint is unchanged. Added regression test `test_scan_inventory_force_refresh_and_source_id_stability`.
  - Staged all Stage 0, Stage 1, and Stage 2 implementation artifacts.
  - Verified test suite: `videocompress` 36/36 passed, `cli_tui` 107/107 passed, `compresser` 524/524 passed.
  - Committing and pushing Stage 1 & 2 to feature branch `videocompress-20261024-0920`.
  - Next Action: Begin Stage 3 — Cheap Predictor & Feasibility Screening.

- **2026-10-24 10:02 (Stage 1 Completed)**
  - Stage 1 implementation complete: `modules/compresser/compresser/tui.py`, `modules/compresser/compresser/cli.py`, `modules/compresser/compresser/arguments.py`, `modules/cli_tui/pyproject.toml`, and `modules/cli_tui/cli_tui/process_runner.py`.
  - Resolved Blocker 1: Added `windows-curses>=2.4.1; sys_platform == 'win32'` platform dependency in `modules/cli_tui/pyproject.toml` and graceful error reporting in `launch_tui` when curses is unavailable.
  - Resolved Blocker 2: Enhanced `ProcessRunner.terminate()` and `ProcessRunner.kill()` in `modules/cli_tui/cli_tui/process_runner.py` with `taskkill /F /T /PID <pid>` on Windows. Tested and verified that child and grandchild processes are terminated without orphan leaks.
  - Connected `compresser tui`, `compresser -T`, and `compresser --tui` CLI routing *before* image-only argument normalization.
  - Introspected `compresser` parser into interactive form widgets with recursion filtered out, title set to "Compresser Interactive Dashboard", and post-run preview action registered for the `preview` operation.
  - Added unit test suite `modules/compresser/tests/tui_test.py` (`6/6 passed`).
  - Added process-tree termination test in `modules/cli_tui/tests/test_process_runner.py` (`10/10 passed`).
  - Verified full test regression:
    - `modules/videocompress`: 35/35 passed in 1.40s.
    - `modules/cli_tui`: 107/107 passed in 6.56s.
    - `modules/compresser`: 523/523 passed (517 existing + 6 new) in 48.0s.
    - `modules/mangadl`: 329/329 passed in 91.85s.
  - Next Action: Present Stage 2 and Stage 1 report to user for validation before proceeding to Stage 3 (Cheap Predictor & Feasibility Screening).

- **2026-10-24 09:38 (Stage 2 Completed)**
  - Stage 2 implementation complete: `workspace.py`, `discovery.py`, `probe.py`, `eligibility.py`, `events.py`, and `inventory.py`.
  - SQLite inventory cache (`inventory.sqlite3`) operational with WAL mode, schema version 1, incremental mtime:size change detection, and stale file pruning.
  - Full FFprobe 9.0.2 stream layout parsing: video, audio, subtitles, chapters, dispositions, rotation, and HDR (PQ / HLG / BT.2020) metadata.
  - Video stream bitrate strictly isolated from container bitrate (`bitrate_provenance = "ffprobe_stream" | "missing"`).
  - Configurable lower-bound filters (`-B`, `-R`, `-S`, `-D`) with display rotation adjustment and conservative unknown handling.
  - Monotonic progress event emission (`ProgressEmitter`) established for CLI and future `cli_tui` integration.
  - Zero encodes verified: inventory operations are 100% non-destructive read-only.
  - Test suite expanded to 35 unit/integration tests (`35/35 passed` in 1.34s).
  - Next Action: Proceed to Stage 1 `compresser tui` image integration via `cli_tui` using the established inventory/progress contracts.

- **2026-10-24 09:27 (Stage 0 Initial Module Bootstrap Complete)**
  - Worktree created: `C:\Users\mcarls\src\scripts\.worktrees\videocompress-20261024-0920` on branch `videocompress-20261024-0920`.
  - Handoff documentation set copied to `modules/videocompress/docs/` (`IMPLEMENTATION_PLAN.md`, `ESTIMATION_BENCHMARK_PROTOCOL.md`, `MEDIA_SAFETY_CONTRACT.md`, `INTEGRATION_CONTRACTS.md`, `README.md`).
  - New module `modules/videocompress` scaffolded: `pyproject.toml` (0.1.0), `README.md`, `contracts.py`, `capabilities.py`, `cli.py` (`vcompress`).
  - Unit tests created: `tests/test_contracts.py`, `tests/test_cli.py`, `tests/test_capabilities.py`.
  - Registered `videocompress` CLI in `modules/scripts_help/scripts_help/registry/registry.py`.
  - Environmental verification: FFmpeg 9.0.2 full build (with `av1_nvenc`, `hevc_nvenc`, `libvmaf`), NVIDIA RTX 5090 Blackwell GPU (Driver 617.14, 32GB VRAM), Python 3.12 curses support verified.
  - Test suites verified: `videocompress` tests: 15/15 passed; `scripts_help` tests: 55/55 passed.
  - Next Action: Complete Stage 0 documentation review with user, then proceed to Stage 1 (`compresser tui` image integration) or Stage 2 (`videocompress` inventory & filters).
