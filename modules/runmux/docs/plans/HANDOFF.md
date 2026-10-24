# Runmux Plans Index Handoff

Last updated: 2026-10-24

This folder contains dated, self-contained implementation plans for runmux.

Optional project-wide future planning, if created, belongs in:

- `master_plan.md`
- `master_plan_checklist.md`

Their absence is not an error.

Folder naming:

```text
YYYYMMDD-HHMM_<descriptive-plan-name>/
```

The completed Runmux Web UI Phase 5C historical telemetry plan is:

- `20261024-runmux-historical-telemetry/`: Phase 5C historical telemetry architecture, empirical benchmarks, and implementation plan. Read its `00_implementation-plan.md`, `01_architecture_specification.md`, `02_alternatives_analysis.md`, `03_resource_budget_and_benchmarks.md`, `04_api_proposal.md`, `05_implementation_plan.md`, `06_approval_decisions.md`, `STATUS.md`, and `HANDOFF.md` for full implementation, verification results, and architecture details.

The completed Runmux Web UI Phase 4A lifecycle controls plans are:

- `20261024-1315_runmux-web-lifecycle-frontend/`: Phase 4A browser-facing process lifecycle controls for Stop, Kill, Restart, Duplicate, and Pause/Resume. Merged to `origin/main`. Read its `00_implementation-plan.md`, `checklist.md`, `STATUS.md`, and `HANDOFF.md` for scope, invariants, verification results, and screenshots.
- `20261024-runmux-lifecycle-backend/`: Phase 4A lifecycle controls backend integrated into `main`. Read its `HANDOFF.md`, `STATUS.md`, `checklist.md`, and `LIFECYCLE_API_SPEC.md` for endpoint specs, verification results, and safety boundaries.

The completed Runmux Web UI Phase 5A+ overview modes and live telemetry plan is:

- `20261024-runmux-web-overview-telemetry/`: Phase 5A four selectable overview modes (Minimal, Inline, Dashboard, Expanded) and complete frontend integration of Phase 5B live telemetry endpoints. Merged to `origin/main`. Read its `HANDOFF.md`, `STATUS.md`, `checklist.md`, and `screenshots/` for implementation details, verification results, and representative browser screenshots.

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
