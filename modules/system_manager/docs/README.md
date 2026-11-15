# system_manager

Cross-platform system management CLI (`sm`, `sys-mgr`) and interactive process explorer (`proc-stats`, `sm proc watch`).

## Commands

- `proc-stats` — Interactive Textual process explorer and one-shot Rich/JSON/CSV reporter.
- `sm proc watch` — Equivalent subcommand under `sm`.
- `sm` / `sys-mgr` — System, process, network, disk, service, Docker, Git, text, crypto, file, and permission utilities.

## Architecture

- `resource_metrics`: Low-level process, tree, system, I/O, and cached GPU measurements.
- `system_manager.process_watch`: Framework-independent process identity, sampling, filtering, sorting, topology aggregation, history/peaks, grouping, and JSON/CSV/Rich export.
- `system_manager.process_watch.tui`: Optional Textual interactive UI (`textual>=0.58.0`).
- `system_manager.process_watch.cli`: Unified CLI for `proc-stats`, `sm proc watch`, and legacy `proc_stats.py` adapter.
