# Repository-Wide Plans Handoff

## Current branch

`compression-inventory-and-analysis-20261016`: I1a inventory, I2a/I2b cache reuse,
I2c automatic cache policies and I3a stable expanding samples. Each tested checkpoint
is committed/pushed under explicit user authorization; main is not pushed. Remaining
advisor, fast/trusted inventory, scratch and reader gates stay open in active status.

Active performance/cache continuation:
[plan](20261013-0600_compression-performance-sampling-and-cache/00_plan.md),
[status](20261013-0600_compression-performance-sampling-and-cache/STATUS.md).
Prior compression safety/reader acceptance gates still apply. Publish each usable
feature before the next; user explicitly authorizes scoped commits/pushes.

`compression-module-mangadl-20261013-0151` uses `20261013-0151_compression-module-and-mangadl-integration/`. The plan covers the standalone `modules/compresser` package, `mangadl compress` subcommand, termdash table and horizontal comparison bar enhancements, perceptual SSIM search, smart caching, and safe non-destructive defaults.

## Other plans

The compression plan REVIEW.md and05_reviewed-plan.md supersede predecessor
completion claims; S5–S8 reopened. Audit follow-up is module-owned at
`modules/mangadl/docs/plans/20261013-0300_audit-ux-and-manual-folder-repair/`.

- `20261012-2039_codex-agent-instructions/`
- `20261009-0349_kavita-module-mangadl-collections/`
- `20261009-0941_scheduler-log-explorer-and-shared-logging/`
- `20260926-0107_missing-only-bootstrap/`
- `20260729-0900_validation-evidence-context-history/`

These plans have separate histories and possible remaining acceptance work. Check each plan's current status and repository evidence before continuing it. Use a module's own `docs/plans/` for module-owned work.
