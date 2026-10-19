# Checklist: Repair and Consolidate LM Studio Console Client

## Stage 1: Documentation and Planning Setup
- [x] Create `modules/lmstui/docs/README.md`, `HANDOFF.md`, and `plans/HANDOFF.md`
- [x] Create dated plan `20261019-0615_repair-consolidate-lmst-client` with `STATUS.md`, `checklist.md`, and `00_implementation-plan.md`

## Stage 2: Core HTTP Transport, Streaming, and Unified API Client
- [x] Implement `HttpClient` with standard library `urllib` supporting JSON requests, timing (`now_seconds()`), and line streaming
- [x] Implement SSE parsing functions in `sse.py` (`parse_sse_events`, `iter_openai_stream_chunks`, `extract_delta_text`, `extract_reasoning_delta`)
- [x] Implement consolidated `LMStudioAPI` (aliased as `LmStudioApi` and `LMStudioClient` for compatibility) supporting `/v1` and `/api/v0`
- [x] Implement loaded model discovery and deterministic selection logic
- [x] Add unit tests for HTTP client, SSE parsing, API client, and model selection

## Stage 3: Defaults Persistence Configuration
- [x] Implement `lmstui.defaults` module with JSON file storage in module directory (`defaults.json`)
- [x] Implement global defaults and per-model defaults with hierarchical override resolution
- [x] Implement default configuration actions (`get`, `set`, `clear`, `show`)
- [x] Add unit tests for defaults persistence and precedence

## Stage 4: CLI Implementation and Interface Consolidation
- [x] Implement unified CLI argument parser supporting `lmst` and `lmstui`
- [x] Ensure all user-facing CLI arguments have both short and long forms
- [x] Support one-shot prompt (`-p/--prompt`), stdin piping, output formats (`--json/-j`, `--stats/-a`, `-S/--silent`)
- [x] Support interactive chat REPL with multi-turn history, slash commands (`/help`, `/reset`, `/exit`), and clean Ctrl+C handling
- [x] Support CLI defaults manipulation flags (`-D/--set-default`, `-d/--show-defaults`, `-C/--clear-defaults`, `-M/--per-model`)
- [x] Add unit tests for CLI argument parsing, execution paths, stdin, and error cases

## Stage 5: Packaging, Discovery, and Integration
- [x] Update `pyproject.toml` with `lmst`, `lmstui`, and `lmc` scripts and bump version to `1.0.0`
- [x] Reinstall editable package in `.venv` and verify entry point execution for `lmst`, `lmstui`, and `lmc`
- [x] Update `modules/lmstui/README.md` with usage examples
- [x] Register `lmst` readiness documented; propose registration for user authorization
- [x] Run full test suite (41 passed), lint (ruff passed), and type checks

## Stage 6: Final Verification and Report
- [x] Run offline verification commands and confirm output (41 passed, ruff passed)
- [x] Stage only intended files (`modules/lmstui/`)
- [x] Commit changes upon user instruction
- [x] Report root causes, consolidation approach, test evidence, commit SHA, and notify user that server can be turned back on
