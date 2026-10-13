# Generalized audit and batch repair status

Branch: `codex/mangadl-generalized-audit-repair`

Status: implementation and repository validation complete; live audit output
confirmed by the user. Live repair acceptance remains pending.

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

- Full MangaDL suite: 264 passed.
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

Next action: retry the user's reviewed repair apply with 1.26.1.
No live repair was executed by the agent; no push or merge has been performed.
