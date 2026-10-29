# Runmux Plans Index Handoff

Last updated: 2026-10-29

This folder contains dated, self-contained implementation plans for runmux.

Optional project-wide future planning, if created, belongs in:

- `master_plan.md`
- `master_plan_checklist.md`

Their absence is not an error.

Folder naming:

```text
YYYYMMDD-HHMM_<descriptive-plan-name>/
```

### Integrated Plans in Main Baseline

The following dated plans have completed implementation, passed all validation gates, and are merged into `main`:

1. **Runmux Web Server Lifecycle Management** (`20261029-0030_runmux-web-server-lifecycle/`):
   - Existing-server auto-discovery on `runmux web`, status inspection via `-S/--status`, graceful stop via `-x/--stop`, and JSON output via `-j/--json`.
   - Security: Zero-knowledge HMAC challenge-response, owner-only ACLs (`icacls` on Windows, POSIX 0600), reparse-point rejection, pre-bound sockets (`SO_EXCLUSIVEADDRUSE` on Windows).
   - Invariant: Supervisor independence (stopping web server leaves supervised runs uninterrupted).
   - Merged into `main` at `e9a5e788` with maintenance hardening on `codex/runmux-maintenance-cleanup-20261029`.

2. **Runmux LLM Monitor Host Integration & Browser Workspace** (`20261029-0135_runmux-llm-monitor-host-integration/`):
   - Stages 0–3 (Backend): Optional, read-only `/api/llm-monitor/v1/` REST routes, lazy imports, no background mutation. Merged into `main` at `39603daa`.
   - Stages 4–5 (Frontend): Browser workspace, composite session identities, hardware metrics, alerts, cursor timeline, visibility throttling, and auth expiration handling. Merged into `main` at `ee4fcb19`.

3. **Phase 6C Historical Explorer Frontend** (`20261024-1805_runmux-history-frontend-local-pilot/`):
   - Historical run explorer workspace, advanced filters/sorting, keyset cursor pagination, bounded DOM rendering, event provenance, and Run ID lineage navigation. Merged into `main` at `ee4fcb19`.

4. **Phase 6C Historical Runs Backend** (`20261024-1530_runmux-historical-runs-backend/`):
   - Keyset-paginated historical queries, event history, lineage mapping, and query optimization. Merged into `main`.

5. **Phase 5C Historical Telemetry Backend and Frontend** (`20261024-runmux-historical-telemetry/` & `20261024-1530_runmux-web-historical-telemetry-frontend/`):
   - Telemetry persistence, compaction, SQLite history ring-buffer, and dashboard/expanded charts. Merged into `main`.

6. **Phase 4A Lifecycle Controls Backend and Frontend** (`20261024-runmux-lifecycle-backend/` & `20261024-1315_runmux-web-lifecycle-frontend/`):
   - Authenticated process control endpoints and UI for graceful stop, kill, restart, duplicate, and pause/resume. Merged into `main`.

7. **Phase 5A+ Overview Modes and Live Telemetry** (`20261024-runmux-web-overview-telemetry/`):
   - Overview density modes (Minimal, Inline, Dashboard, Expanded) and live telemetry. Merged into `main`.

8. **Earlier Integrated Web and Native TUI Plans**:
   - `20261024-runmux-web-enhanced-logs/`: Phase 4B log search/filtering.
   - `20261024-runmux-web-explorer-workspace/`: Phase 3 explorer workspace.
   - `20261024-runmux-web-terminal-log-correctness/`: Phase 2 terminal and log streaming.
   - `20261024-runmux-web-process-launching/`: Phase 1 process launch.
   - `20261023-2120_runmux-native-tui-final-integration/`: Native TUI (`runmux tui`).

New implementation plans that require multiple work stages must receive their own dated folder here. Completed plans remain available as historical design and implementation evidence.
