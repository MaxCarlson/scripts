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

The current Phase 3 feature branch plan is:

`20261024-runmux-web-explorer-workspace/`

Phase 3 is implemented, committed, and pushed on its dedicated branch; read its
`HANDOFF.md`, `STATUS.md`, and `checklist.md` for verified results and limits.

Phase 2 terminal/log correctness and Phase 5B telemetry are integrated in `origin/main`
at `9f01984d3dedf05781a19f8d131956662ee5b29d`; Phase 2 evidence is retained in
`20261024-runmux-web-terminal-log-correctness/`. Phase 1 launch evidence is in
`20261024-runmux-web-process-launching/`.

The previously active native TUI integration plan is:

`20261023-2120_runmux-native-tui-final-integration/`

Its documents remain historical design and implementation evidence. The older
multi-attach and history plan is also retained as history.

New implementation plans that require multiple work stages must receive their
own dated folder here. Completed plans remain available as historical design and
implementation evidence.
