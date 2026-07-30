# Scripts Repository Documentation

This directory contains repository-wide documentation for changes that affect multiple modules or shared repository infrastructure.

## Repository-Wide Plans

Active and historical repository-wide plans live under:

```text
docs/plans/
```

Module-specific plans remain inside the owning module, for example:

```text
modules/<module>/docs/plans/
```

Use a repository-wide plan when the work changes shared tooling, validation infrastructure, common standards, branch integration, or conventions that apply to several modules.

## Shared Agent Documentation

Reusable agent and development standards live under:

```text
docs/agent/
```

Read `docs/agent/BRANCH_INTEGRATION_WORKFLOW.md` for the `main` → `agent/unified` → `agent/<work>` lifecycle.

## Validation Evidence

Tracked raw validation evidence lives under:

```text
docs/test-results/<target>/
```

For each target:

- `LATEST.txt` is the authoritative current raw transcript.
- `history/` contains a small bounded set of prior raw artifacts.
- `LATEST_CONTEXT.md` and `LATEST_PROGRESS.diff` are transitional migration artifacts where still enabled.

A ledger-enabled active plan additionally maintains:

```text
<active-plan>/ledger/
├── RUNS.jsonl
├── LATEST.json
├── PROGRESS.md
├── TRACEABILITY.md
├── MANUAL_CHECKS.md
└── LOCAL_HANDOFF.md
```

- `RUNS.jsonl` is append-only permanent normalized history.
- `PROGRESS.md` is the primary generated current-state orientation.
- `TRACEABILITY.md` maps plan items to automated and manual evidence.
- `MANUAL_CHECKS.md` contains pending environment-dependent acceptance work.
- `LOCAL_HANDOFF.md` appears only when routing recommends narrow local-agent work.

Never manually edit generated ledger files. During migration, use the ledger for normalized progress/routing and `LATEST.txt` for complete diagnostic detail.
