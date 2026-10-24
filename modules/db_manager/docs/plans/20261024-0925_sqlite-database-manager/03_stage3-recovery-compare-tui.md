# Stage 3: P2 Recovery, TUI Adapter, Registry & Handoff Integration

**Parent Plan:** [00_implementation-plan.md](00_implementation-plan.md)  
**Status:** Planned  

## Scope

Deliver recovery diagnostics, external SQLite `.recover` invocation, terminal UI adapter, scripts-help registry integration, and full validation:
- `recover`: inspect valid backups, analyze database corruption, invoke external SQLite CLI `.recover` to a new output path with clear caveats, or extract surviving tables to new file.
- `tui`: terminal presentation adapter providing table layouts, headers, and status line.
- Registry: register `db-manager` CLI in `modules/scripts_help/scripts_help/registry/registry.py`.
- Documentation & Handoff freeze: update `README.md`, `HANDOFF.md`, `STATUS.md`, and `checklist.md`.

## Deliverables

1. `db_manager/recovery.py`: Recovery diagnostics and external `.recover` runner.
2. `db_manager/tui.py`: Table formatting and CLI layout rendering.
3. `modules/scripts_help/scripts_help/registry/registry.py` update.
4. `tests/recovery_test.py`, `tests/tui_test.py`.
5. Full repository test, format, and lint verification (`pytest`, `ruff check`, `ruff format`).

## Verification Criteria

- `.recover` handles missing external CLI gracefully with clear message.
- TUI table formatting handles long text, NULLs, and wide columns cleanly.
- `db-manager` is listed in `scripts_help` registry and validated against registry checks.
- Code cleanly passes `ruff check` and `ruff format`.
