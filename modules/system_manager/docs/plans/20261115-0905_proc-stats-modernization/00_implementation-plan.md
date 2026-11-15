# Proc-Stats Modernization Implementation Plan

## Goal

Modernize `proc_stats` into an interactive, read-only process explorer (`proc-stats` and `sm proc watch`) while preserving `proc_stats` / `python pyscripts/proc_stats.py` and fixing `system_manager` editable packaging (`ModuleNotFoundError: No module named 'system_manager'`).

## Architecture

1. **Measurement (`modules/resource_metrics`)**:
   - Preserve existing APIs.
   - Add cached/throttled GPU backend (`pynvml` preferred, `nvidia-smi` fallback) with explicit backend provenance, measurement age, and honest WDDM/unavailable handling.
2. **Monitoring Engine (`modules/system_manager/process_watch`)**:
   - Framework-independent sampler using stable `(pid, create_time)` identities.
   - Monotonic-time CPU% and I/O rate deltas with PID-reuse, counter-reset, and access-denied handling.
   - Single-pass topology builder for parent/descendant navigation and non-double-counted subtree aggregation.
   - Bounded rolling histories, peak tracking, process churn detection, grouping, and sanitized summaries.
   - One-shot Rich table, JSON, and CSV exporters.
3. **Interactive UI (`modules/system_manager/process_watch/tui.py`)**:
   - Textual app (`Processes`, `Tree`, `Pinned`, `History` tabs), modal inspector, sort/column/group choosers, live filter, freeze, dynamic row count, and background sampling worker.
4. **CLI & Packaging**:
   - Fix `modules/system_manager/pyproject.toml` flat-package mapping (`system_manager = "."`), add `proc-stats` console script, optional `[tui]` extra, and bump to `1.0.0`.
   - Wire `sm proc watch` and legacy `pyscripts/proc_stats.py` adapter.
   - Regenerate wrappers/manifest via `scripts_setup/launcher_generator.py` and update `scripts_help` registry.
