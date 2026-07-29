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

Use a repository-wide plan when the work changes shared tooling, validation infrastructure, common standards, root scripts, or conventions that apply to several modules.

## Shared Agent Documentation

Reusable agent and development standards live under:

```text
docs/agent/
```

## Validation Evidence

Tracked validation evidence lives under:

```text
docs/test-results/<target>/
```

For each target:

- `LATEST.txt` is the authoritative current test report.
- `LATEST_CONTEXT.md` pairs the report with current project status/checklist context.
- `LATEST_PROGRESS.diff` shows project-context changes since the previous validation.
- `history/` contains a small bounded set of prior artifacts for regression comparison.
