# Checklist: Video Compression Implementation (`20261024-0920_video-compression`)

## Stage 0: Environmental Verification & Architecture Planning
- [x] Verify local checkout, branch, and worktree isolation (`videocompress-20261024-0920`)
- [x] Copy reference handoff documentation into `modules/videocompress/docs/`
- [x] Verify local tool capabilities (FFmpeg 9.0.2, FFprobe, NVIDIA RTX 5090 NVENC, VMAF, curses)
- [x] Scaffold `modules/videocompress` with `pyproject.toml`, `README.md`, typed `contracts.py`, `capabilities.py`, and `cli.py`
- [x] Register `videocompress` in `modules/scripts_help/scripts_help/registry/registry.py`
- [x] Add baseline unit tests for contracts, CLI, and capabilities (`15/15 passed`)
- [x] Answer the 12 local agent architectural questions in `00_stage0_decisions_and_verification.md`
- [x] User review and sign-off on Stage 0 architecture and decisions

## Stage 2: Video Package Capabilities, Inventory & Eligibility Filters
- [x] Implement `videocompress.workspace`: path-hashed external workspaces (`.videocompress/<leaf>_<hash>/`), isolation enforcement
- [x] Implement `videocompress.discovery`: scoped recursive file finding, duplicate/alias detection, symlink loop guards
- [x] Implement `videocompress.probe`: FFprobe JSON extraction for video, audio, subtitles, attachments, chapters, HDR, rotation
- [x] Implement `videocompress.eligibility`: configurable filters (`-B` video bitrate, `-R` resolution, `-S` size, `-D` duration), conservative unknown handling
- [x] Implement `videocompress.inventory`: SQLite cache (`inventory.sqlite3`), incremental mtime/size change detection, stale pruning
- [x] Implement `videocompress.events`: monotonic progress event contracts and sinks (`ProgressEmitter`)
- [x] Connect `vcompress inventory` CLI with human-friendly and structured JSON streaming
- [x] Add synthetic fixtures and tests for corrupted files, missing metadata, mixed streams, cache invalidation, and eligibility boundaries (`35/35 passed`)
- [x] Verify zero encodes during inventory operations

## Stage 1: Optional TUI for Images (`compresser tui`)
- [x] Add `windows-curses>=2.4.1; sys_platform == 'win32'` to `modules/cli_tui/pyproject.toml`
- [x] Implement Windows process tree kill (`taskkill /F /T /PID`) in `modules/cli_tui/cli_tui/process_runner.py`
- [x] Add unit test for Windows process tree kill in `modules/cli_tui/tests/test_process_runner.py`
- [x] Implement `modules/compresser/compresser/tui.py` (`build_tui_app`, `launch_tui`, post-run preview action)
- [x] Update `modules/compresser/compresser/cli.py` to route `tui`, `-T`, `--tui`, and `video` before argument normalization
- [x] Add unit tests for `compresser tui` in `modules/compresser/tests/tui_test.py`
- [x] Verify `cli_tui` Windows curses launch and keyboard navigation
- [x] Run `cli_tui`, `compresser`, `mangadl`, and `videocompress` regression test suites

## Stage 3: Cheap Predictor & Feasibility Screening
- [x] Implement container byte decomposition and bit-budget feasibility arithmetic
- [x] Implement `videocompress plan`: freeze target scope, eligible population, recipes, windows
- [x] Implement `videocompress estimate --tier metadata`: zero-encode prior and honest abstention
- [x] Verify reporting of unknown fields and explicit decision states

## Stage 4: Controlled Encoder & Measurement Backend
- [x] Implement `videocompress.sampling`: deterministic temporal window selection (`s3`, `s5`, `s8`) with boundary guards
- [x] Implement `videocompress.adapters.ffmpeg`: safe FFmpeg subprocess runner with `-nostdin`, `-hide_banner`, source immutability assertions, timeouts, and process-tree cleanup
- [x] Implement `videocompress.trials`: SQLite cache (`trials.sqlite3`), trial key hashing, output probe validation, and quota enforcement (`--max-trials`, `--max-time`)
- [x] Implement sample estimation aggregator: combine measured sample bitrates with container decomposition
- [x] Connect CLI commands: `vcompress estimate --tier sampled`
- [x] Unit & integration tests for sampling geometry, source immutability, process cancellation, trial cache hit/miss, and quota exhaustion
- [x] Verify zero full-file encoding and zero source mutations

## Stage 5: Quality, Compare & Preview
- [x] Implement `videocompress.quality`: frame-aligned SSIM, PSNR, and VMAF calculation via FFmpeg filtergraph
- [x] Implement perceptual vs bitrate confidence separation contracts and generational loss caveats
- [x] Implement `videocompress.compare`: multi-recipe comparison engine across shared sample windows
- [x] Implement `videocompress.preview`: side-by-side split-screen comparison clip generator and visual manifest exporter
- [x] Connect CLI commands: `vcompress compare`, `vcompress analyze`, and `vcompress preview`
- [x] Unit & integration tests for frame-aligned scoring, multi-recipe comparison, preview rendering, and source immutability
- [x] Verify zero full-file encoding and zero source mutations

## Stage 6: Estimation Calibration & Selection
- [ ] Prepare isolated, royalty-free test video corpus
- [ ] Execute full-file ground truth encodes for baseline calibration
- [ ] Evaluate sampling schedules (S3 vs S5 vs S8 vs SA) on holdout corpus
- [ ] Calibrate prediction intervals and verify false-positive conversion rate <= 0%

## Stage 7: Safe Apply & Recovery
- [ ] Implement staged non-clobber publication to external output root (`apply -w`)
- [ ] Implement transaction journal state machine (`PLANNED -> ... -> PUBLISHED`)
- [ ] Implement verification levels (V1 structural, V2 full decode)
- [ ] Implement `vcompress recover`: read-only inspection and scoped token repair

## Stage 8: Final Integration, Performance Audit & Verification
- [ ] Connect `compresser video` router in `modules/compresser`
- [ ] Connect `compresser tui` video menu
- [ ] Execute complete repository validation suite (`Invoke-Tests.ps1`)
- [ ] Benchmark RTX 5090 encoding throughput and resource utilization
