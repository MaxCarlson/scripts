# Generalized audit and batch repair status

Branch: `codex/mangadl-generalized-audit-repair`

Status: live repair fix committed/pushed (`55d02b2`); summary/color improvements
implemented and validated in 1.27.0. Shared downloader UI is the next stage.
The user requested commit/push after each stage.

Implemented: URL directory discovery, durable audit reports, visible batch
repair planning, exact-token apply for proven actions, and post-repair source
mapping backfill. The plan checks for folders that appeared after the audit
and reports unknown completion explicitly.

Live audit diagnosis: the user's `mangadl-url32-audit-report.json` already
identified nhentai 633374 as incomplete (192 expected, 34 valid/present,
pages 1-158 missing). Input line 42 is a duplicate of line 5; the retained URL
was audited once. The console omitted per-URL findings, which hid this result
behind the aggregate three-incomplete count. A fresh read-only folder check
confirmed the same result. Console findings, separate loading counts, and
automatic source-labeled report names with collision numbering are now added.

Validation:

- Full MangaDL suite: 271 passed.
- Focused scripts-help registry suite: 42 passed (one known pytest cache
  permission warning).
- Ruff passed for MangaDL and the changed registry file.
- Package compilation, CLI version/help, and Git diff checks passed.

The user requested preserving this usable 1.26.0 state and authorized a scoped
commit. The proposed live progress bar and colored audit/repair summaries are
deferred; no implementation of those enhancements was started.

Live apply failed before downloads: missing-only repairs did not create the
quarantine directory before writing `repair-manifest.json`. Read-only comparison
of the three 20261012-2328 archive backups and the current archive found identical
70708-entry sets. The repair lock was removed; no image downloads started.

Fixed in 1.26.1: always create the repair directory, keep long gallery names in
the manifest rather than its Windows path, and write the manifest before deleting
target archive entries. Focused repair/CLI regressions: 44 passed; Ruff passed.

Live retry in 1.26.2 fixed archive-key enumeration: gallery-dl's print-only mode
had produced `None` for every key because it disabled skip/archive checks.
Re-enabling checks against an empty temporary archive preserves download-disabled
enumeration while generating distinct real keys. Placeholder/repeated keys are
now rejected. All three authorized galleries were repaired and independently
verified complete; see LIVE_REPAIR.md for counts and run IDs.

Summary stage: readable wrapped URL/folder/page fields, terminal-aware colored
statuses, NO_COLOR/plain-output support, detailed failure/remaining-page output,
and a transient audit row with URL position, metadata activity, and real image
checks. Existing termdash indicators and progress bars are reused. JSON stdout
remains clean. Console rendering and all 271 MangaDL tests passed.

Next: commit/push summaries, then route all repair jobs through a shared normal
download manager with available workers.
No merge is authorized.
