# Legacy Planning Migration

The old scripts-repo planning system used repository-level paths such as:

```text
plans/modules/<module>/INDEX.md
plans/modules/<module>/user/
plans/modules/<module>/ai/
plans/modules/<module>/ai/perma/
```

That taxonomy is legacy for new work.

## New Canonical System

For new substantial work, use project-local docs:

```text
project_root/docs/
├── README.md
├── HANDOFF.md
└── plans/
    ├── HANDOFF.md
    └── YYYYMMDD-HHMM_descriptive-plan-name/
        ├── 00_implementation-plan.md
        ├── 01_stage-name__planned.md
        ├── HANDOFF.md
        ├── STATUS.md
        └── checklist.md
```

## Migration Rules

- Do not create new canonical plans under `plans/modules/<module>/`.
- Do not delete old plans automatically.
- Treat old plans as historical evidence.
- If an old plan is still active, summarize its current actionable state into the new project-local `docs/` system.
- Link to old plans from the new docs only when they are still relevant.
- Use `stage`, not `cycle`, as the canonical term in new docs.

## Incoming Agent Rule

If old planning docs conflict with current `docs/HANDOFF.md`, active plan `STATUS.md`, `checklist.md`, source code, tests, or git evidence, trust current repository evidence and update the new docs before continuing.
