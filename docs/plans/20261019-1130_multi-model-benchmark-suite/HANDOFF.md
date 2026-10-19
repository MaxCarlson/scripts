# Plan Handoff — Multi-Model Benchmarking

**Plan Directory:** `docs/plans/20261019-1130_multi-model-benchmark-suite/`  
**Branch:** `agent/multi-model-benchmark-20261019-1130`  
**Worktree:** `C:\Users\mcarls\src\scripts-multi-model-benchmark`  
**Parent / Baseline:** `main` at `91d04f5d`  
**Stage 1 Commit:** `8ec27f46`  
**Stage 2 Commit:** `18e77612`  
**Stage 3 Commit:** `5135984c`  
**Stage 4 Commit:** `ecbabf55`  
**Stage 5 Commit:** `19ee259f`  
**Active Plan Stage:** Stage 5 Complete & Verified (Awaiting final user review and merge approval)

---

## Architecture Summary
- **Generic Core (`modules/benchmark_core`)**: Owns `Experiment`, `ExperimentConfig`, `ExperimentRunRef`, production comparison eligibility filtering (enforcing `comparison_eligible=True`), denominator preservation (`passed + failed + timed_out`), Wilson score confidence intervals (95% CI), atomic experiment persistence (`save_experiment`, `load_experiment`), and report artifact generation (`comparison.json`, `comparison.csv`, `report.md`, `index.html`).
- **Interactive Reports (`modules/interactive_reports`)**: Standalone reusable reporting package providing portable offline HTML visualization, task divergence matrix, execution efficiency scatterplots (with hover tooltips), and trial inspection drawer across benchmarking domains. Zero external CDN dependencies; operates cleanly under `file://` protocols.
- **Agent Lifecycle & Scheduler (`modules/agent_benchmark`)**: Owns `list_downloaded_models`, `get_loaded_model`, safe `transition_model` (with explicit authorization checks, VRAM release verification, and zero blind retries), `expand_experiment_plan` (batched model grouping to eliminate GPU thrashing), and `ExperimentScheduler` (enforcing strictly 1 active GPU trial, per-trial reservation, and incremental persistence).
- **CLI Subcommands & Entry Points (`modules/agent_benchmark/pyproject.toml`, `cli.py`)**: Directly callable via `agent_benchmark`, `agent-benchmark`, and `agent-bench`. Subcommands wired for `models list`, `experiment plan`, `experiment run` (with explicit `-x` execution gate), `experiment status`, and `experiment report`.
- **Non-API Local CLI Agent Support (`models_lifecycle.py`, `attempt.py`, `scheduler.py`, `runner.py`)**:
  - Programmatic model discovery and execution for Gemini via `agy` (`list_gemini_models`, `agy models`) and ChatGPT via `codex` (`list_codex_models`, `~/.codex/models_cache.json`) alongside LM Studio (`list_downloaded_models`).
  - Consistent model naming syntax (`resolve_model_provider_and_key`) supporting `<provider>/<model_key>` (`gemini/...`, `codex/...`, `lmstudio/...`) and shorthand aliases (`gemini-3.8-flash`, `gemini-4-Argon`, `ChatGpt-6.1-sol`, `6-sol`, `6-luna`, `6-Astra`, `5.6-Luna`, `5.6-Terra`, `5.6-Sol`).
  - `run_cli_attempt` executes `agy` (`--mode accept-edits --dangerously-skip-permissions -p`) and `codex` (`exec -C <workspace> --dangerously-bypass-approvals-and-sandbox --ephemeral` with `DEVNULL` stdin) inside the isolated trial workspace, preserving S0/S1 snapshots, scope auditing, and hidden verification without requiring cloud API keys or GPU VRAM transitions.
- **Terminal UI Adapter (`modules/agent_benchmark/agent_benchmark/dashboard.py`)**: Consumes `termdash.LiveBlock` and `termdash.Table` to render bounded in-place console progress (max 10-12 rows) with quiet mode (`-Q`/`--quiet`), non-interactive fallback, and safe terminal restoration.
- **Terminal Primitives (`modules/termdash`)**: Reusable bounded in-place rendering (`LiveBlock`) and ANSI table formatting.
- **Offline & Safe**: No live cloud calls or inference during offline test suite runs; historical evidence immutable.

---

## Verification Evidence
- `pytest modules/interactive_reports/tests`: 15 passed
- `pytest modules/benchmark_core/tests`: 94 passed, 1 skipped
- `pytest modules/agent_benchmark/tests`: 267 passed, 3 skipped
- `pytest modules/termdash/tests`: 76 passed, 1 skipped
- Total tests passed: 452 passed, 5 skipped (0 failures)
- `ruff check modules/interactive_reports modules/benchmark_core modules/agent_benchmark`: All checks passed (0 errors)

