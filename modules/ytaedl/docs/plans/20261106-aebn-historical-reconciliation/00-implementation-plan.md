# AEBN Historical Download Reconciliation

## Goal

Provide a resumable `ytaedl reconcile-aebn` workflow that resolves scene URLs from AEBN metadata, inventories only configured media roots, plans corrected scene replacements, verifies them, records per-file deletion approvals, and performs separately authorized removal only after rechecking all evidence.

## Design

- Keep the workflow in `ytaedl.aebn_reconcile`, separate from the archive validator.
- Use a schema-versioned SQLite database with WAL, transactions, indexed movie/scene/job/candidate state, and an append-only event journal. JSON and CSV are exports, not canonical state.
- Use the existing `aebn_dl.Movie` parser and `scene_ordinal_for_id()` resolver. Keep scene-ID mapping in document order and never infer an ordinal from numeric ID order.
- Treat filenames and archive statuses as evidence only. Candidate matching must be conservative; unresolved identity stays ambiguous and ineligible for deletion.
- Do not edit existing archives during scan. Isolate corrected downloads from historical archive completion records. Verify outputs independently before changing replacement status.
- Keep scanning, replacement download, verification, review, archive sync, and deletion as separate commands. `delete --apply` requires a persisted approval and a second explicit confirmation; permanent removal has a separate confirmation.
- All tests use synthetic files, mocked metadata, and mocked subprocesses. No live media downloads or real-file removal.

## Approaches considered

1. Extend the archive validator: rejected because its archive-repair transaction is not a suitable owner for the multi-stage media replacement lifecycle.
2. Persist plans as rewritten JSON: rejected because independently progressing jobs, approvals, and deletions need row-level transactions and crash recovery.
3. Dedicated SQLite subsystem: selected by this implementation based on the user's requirements for resumability, per-item audit history, and safe approval invalidation.

## Execution stages

1. Establish the dedicated package, schema, input validation, metadata resolution, bounded media inventory, conservative candidate classification, and read-only scan CLI.
2. Add idempotent replacement jobs, AEBN scene-ID subprocess integration, resumability, and independent media verification.
3. Add grouped review, approval binding/invalidation, interactive decisions, and JSON/CSV export.
4. Add approved-only quarantine/permanent deletion, preflight checks and intent journaling; add optional targeted archive reconciliation with existing locking.
5. Run focused synthetic tests, relevant ytaedl regressions, lint/type/compile checks, review the complete diff, and update user documentation/status.

## Safety boundaries

No production URL file, media library, archive, manager, or worker will be changed during implementation or validation. No real downloads, media removals, merges, or pushes are authorized. The resulting branch may be committed; integration requires the user's explicit merge approval.
