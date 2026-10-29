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

The active Runmux Web server lifecycle plan is:

- `20261029-0030_runmux-web-server-lifecycle/`: Web server lifecycle management, existing-instance discovery, credential recovery, graceful stop, and status controls. Read `00_implementation-plan.md`, `STATUS.md`, and `checklist.md`.

The active Runmux LLM Monitor host integration plan is:

- `20261029-0135_runmux-llm-monitor-host-integration/`: Integration of LLM Monitor 0.5.0 read-only functionality into Runmux Web as an optional, authenticated monitoring workspace. Read `00_implementation-plan.md`, `STATUS.md`, and `checklist.md`.

The latest active Runmux Web UI phase plan is:

- `20261024-1805_runmux-history-frontend-local-pilot/`: Phase 6C historical explorer frontend and controlled local-model dispatch evaluation. Read its `00_implementation-plan.md`, `STATUS.md`, `checklist.md`, and `LOCAL_DISPATCH_LEDGER.md`. Current branch is `codex/runmux-6c-history-frontend-local-pilot-20261024`; D0–D7 are complete, and the pushed branch remains unmerged for independent audit.

- `20261024-1530_runmux-historical-runs-backend/`: Phase 6C historical run discovery, filtering, keyset pagination, and lifecycle events backend. Read its `00_implementation-plan.md`, `01_existing_capabilities_matrix.md`, `STATUS.md`, and `HANDOFF.md` for architecture, contracts, and verification evidence.

The completed Runmux Web UI Phase 5C historical telemetry plan is:

- `20261024-runmux-historical-telemetry/`: Phase 5C historical telemetry architecture, empirical benchmarks, and implementation plan. Read its `00_implementation-plan.md`, `01_architecture_specification.md`, `02_alternatives_analysis.md`, `03_resource_budget_and_benchmarks.md`, `04_api_proposal.md`, `05_implementation_plan.md`, `06_approval_decisions.md`, `STATUS.md`, and `HANDOFF.md` for full implementation, verification results, and architecture details.

The completed Runmux Web UI Phase 4A lifecycle controls plans are:

- `20261024-1315_runmux-web-lifecycle-frontend/`: Phase 4A browser-facing process lifecycle controls for Stop, Kill, Restart, Duplicate, and Pause/Resume. Merged to `origin/main`. Read its `00_implementation-plan.md`, `checklist.md`, `STATUS.md`, and `HANDOFF.md` for scope, invariants, verification results, and screenshots.
- `20261024-runmux-lifecycle-backend/`: Phase 4A lifecycle controls backend integrated into `main`. Read its `HANDOFF.md`, `STATUS.md`, `checklist.md`, and `LIFECYCLE_API_SPEC.md` for endpoint specs, verification results, and safety boundaries.

The completed Runmux Web UI Phase 5A+ overview modes and live telemetry plan is:

- `20261024-runmux-web-overview-telemetry/`: Phase 5A four selectable overview modes (Minimal, Inline, Dashboard, Expanded) and complete frontend integration of Phase 5B live telemetry endpoints. Merged to `origin/main`. Read its `HANDOFF.md`, `STATUS.md`, `checklist.md`, and `screenshots/` for implementation details, verification results, and representative browser screenshots.

The Phase 5C historical telemetry frontend is being completed on its own review branch:

- `20261024-1530_runmux-web-historical-telemetry-frontend/`: Dashboard and Expanded history charts consuming the already-integrated Phase 5C API. Read `HANDOFF.md`, `STATUS.md`, `checklist.md`, and `screenshots/` for the current implementation and validation evidence. Do not merge until separately authorized.

The earlier integrated Runmux Web UI phase plans on `main` are:
- `20261024-runmux-web-enhanced-logs/`: Phase 4B enhanced output search and filtering integrated into `main`. Read its `HANDOFF.md`, `STATUS.md`, and `checklist.md` for implementation details, verification results, and boundaries.
- `20261024-runmux-web-explorer-workspace/`: Phase 3 integrated into `main` at `54502666b5724596ee3d21c1e694b8522d5a5151`. Read its `HANDOFF.md`, `STATUS.md`, and `checklist.md` for verified results and limitations.

Phase 2 terminal/log correctness and Phase 5B telemetry backend are included in the
integrated baseline; Phase 2 evidence is retained in
`20261024-runmux-web-terminal-log-correctness/`. Phase 1 launch evidence is in
`20261024-runmux-web-process-launching/`.

The previously active native TUI integration plan is:

`20261023-2120_runmux-native-tui-final-integration/`

Its documents remain historical design and implementation evidence. The older
multi-attach and history plan is also retained as history.

New implementation plans that require multiple work stages must receive their
own dated folder here. Completed plans remain available as historical design and
implementation evidence.