# MangaDL Library Identity, Audit, Repair, and Kavita Operations

## Goal

Give MangaDL one trusted way to connect source URLs, downloaded manga folders,
image/page identities, and Kavita series. Reuse that identity layer for
read-only library audits, safe repair planning, post-download collection
assignment, batch assignment from historical URL files, direct series
selection by name, and preview-first pattern selection.

The current branch already has a reusable Kavita API package, download-time
collection assignment, a partial URL-file audit, and a prior audit/repair
design. This plan closes the missing batch workflows and consolidates URL to
folder matching instead of creating another matcher for each command.

## Current baseline (2026-10-09)

- Current branch: `codex/kavita-module-mangadl-collections-20261009-0349`.
- Branch is pushed and intentionally not merged. User wants it merged after the
  remaining feature work is implemented and validated.
- Commits on this branch include Kavita integration (`0ed97c5`), read-only
  image audit (`b58b308`), and local scheduler-history ignore rules
  (`b38bd37`). `main` contains the graceful-shutdown/storage commit but does
  not yet contain the branch's Kavita or audit features.
- `modules/kavita` already offers authenticated series/collection APIs,
  exact local-to-Kavita path matching, pending assignments, and safe
  preview/apply operations. MangaDL already imports it, supports repeated
  `run --collections`, and can reconcile assignments queued after successful
  downloads.
- This plan implements historical URL-file collection assignment, exact-name
  and reviewed-pattern selection, folder-only audit, a canonical MangaDL
  URL-to-folder resolver shared by run/audit/Kavita/repair, and safe
  page-level redownload of missing/corrupt images. Current implementation
  status and remaining acceptance gates are in `STATUS.md`.
- `mangadl audit` currently audits URL-file inputs and destination roots. Its
  only proven page-count adapter is nhentai. Paradise (`nhentai-633374`) is
  detected as 192 expected pages with pages 1-158 absent and page 175 corrupt.
  Audit is read-only; it does not repair.
- `repair-loose` only organizes loose nhentai page files; it does not fetch
  missing pages.
- The approved worker policy is no fixed outer-worker ceiling when either the
  destination or selected scratch volume is SSD, while continuing to honor the
  aggregate logical-CPU budget; without SSD on either path, cap at four. This
  is implemented in the current branch worktree.

## Architecture

### Canonical library identity layer

Add an importable MangaDL library/index API that returns structured records
with canonical source URL, original URL-file provenance, backend, resolved
folder(s), evidence and confidence, expected page identities/count provenance,
and an explicit status (`complete`, `incomplete`, `ambiguous`, `unknown`,
`unsupported`, or `missing`).

Resolution precedence:

1. MangaDL's own per-folder source manifest, written atomically after a
   successful promotion and tied to canonical URL/backend/layout.
2. Existing backend metadata such as gallery-dl `info.json`.
3. Backend-specific deterministic folder identity (for example nhentai ID)
   as candidate evidence, never as permission to resolve duplicate folders.
4. No fuzzy title assignment. Multiple URLs/folders or weak evidence remain
   ambiguous/unknown and are excluded from destructive repair and Kavita
   writes.

Legacy folders without MangaDL manifests remain auditable using source
metadata and adapters. The index can build from a URL file plus an explicit
destination, or from a library root alone. Folder-only results with no proven
source URL/page set are marked unknown rather than complete.

The shared resolver owns URL-to-folder identity. Kavita keeps its server API
and exact local-path-to-Kavita-path adaptation, consuming resolved local
folder records rather than implementing URL matching again.

### Expected-page and integrity adapters

Use backend adapters to enumerate stable expected page identities and
associated source-specific archive keys without downloading payloads. The
nhentai metadata resolver is the first proven adapter. Add other backends only
after proving that enumeration is complete, read-only with respect to the
download archive, and deterministic. Local inspection validates numbered
images (nonzero size and decode), identifies missing/duplicate/extra/corrupt
pages, and preserves evidence for every conclusion.

### Safe operations

- Audits and selection previews never mutate image payloads, the download
  archive, assignment store, or Kavita. URL-file audit and historical
  `assign-file` may atomically add only a source-identity sidecar for a proven
  unique match; both expose a read-only opt-out. Expected-page enumeration can
  make source metadata requests but never fetches image payloads or writes the
  download archive.
- Collection writes remain explicit and idempotent.
- Repair previews enumerate exact source URLs, folders, pages, archive rows,
  and recovery actions. Applying repair requires an explicit flag and a token
  bound to the displayed plan. Preserve corrupt originals in a
  recoverable quarantine; never overwrite valid files or clear an entire
  gallery archive entry set to repair one page.
- Repair uses MangaDL's worker, retry/auth, `_partial`, scratch, promotion,
  archive, and state lifecycle, then re-audits before reporting complete.
- Pattern selection always prints the exact matched Kavita series and
  collections before confirmation. Ambiguous name/path matches are excluded.
  Clarify/document pattern syntax: Python regex `blahblah*` repeats the last
  `h`; a prefix wildcard is `blahblah.*`.

## Stages

### Stage 1 — remove the fixed fast-storage worker ceiling

- Detect media for both the destination and explicit scratch path.
- If either is SSD, set the worker target ceiling to the aggregate
  logical-CPU budget (`logical_cpus - 1`) rather than a fixed constant. Keep
  the existing aggregate worker/image-thread CPU budget in force.
- If neither path is SSD, retain a four-worker maximum. Reject unsupported
  explicit values rather than silently exceeding the selected policy.
- Show both media classifications and the effective policy in dry-run/UI
  status; make `+` able to increase workers until the effective limit/budget.
- Tests cover SSD destination, SSD scratch, rotational/unknown on both paths,
  explicit limits, and runtime increments at/over the budget.

### Stage 2 — single canonical URL-to-folder index and provenance

- Extract the current matching rules from `destination_audit.py` into the
  shared library-index API and route audit through it without changing existing
  JSON/input compatibility.
- Add an atomic, versioned per-folder MangaDL source manifest for new
  successful downloads. Include canonical URL, backend, folder identity, and
  optional expected-page evidence; avoid storing credentials or transient
  auth data.
- Make run-time Kavita assignment creation use the same resolved folder
  record. Preserve legacy metadata fallbacks and surface ambiguity explicitly.
- During URL-file audit and Kavita `assign-file`, backfill missing source
  manifests for unique, non-empty matches established by exact source metadata
  or deterministic backend identity. Never overwrite an invalid/different
  source identity; report existing, created, skipped, and conflicting pairs.
- Tests cover exact metadata, legacy fallback, duplicate URL/folder
  assignment, interrupted promotion, manifest mismatch, stale manifests, and
  no silent folder merging.

### Stage 3 — complete-library and URL-file audit on the shared index

- Support audit by destination folder alone and by URL file plus an explicit
  expected destination. Folder-only mode derives source identity from
  manifests/metadata and reports unknown where it cannot.
- Compare URL list membership with the library (missing URLs, untracked extra
  manga, duplicate folders, missing folders) and audit each source's expected
  page set when an adapter can establish it.
- Make audit output deterministic, progress-visible, and safe for large
  libraries; keep folder-only mode read-only and provide `--no-index-backfill`
  for URL-file audits that must not create metadata sidecars.
- Tests cover nested/large roots, multiple destinations, folder-only mode,
  duplicate URL lines, extra folders, inaccessible files, and no mutation.

### Stage 4 — assign historical URL-file manga to Kavita collections

- Add a `mangadl kavita` batch workflow that reads a processed URL file,
  resolves each URL through the shared index, maps its folder to exactly one
  Kavita series, and previews all assignments to one or more collections.
- Reuse existing Kavita collection creation/addition and path-map logic.
  Missing, ambiguous, incomplete, or not-yet-scanned series remain visible
  but are not written. Reconcile pending exact-path assignments after scans.
- Keep download-time `run --collections` as a separate supported path.
- Tests cover URL provenance, unresolved entries, duplicate/ambiguous folder
  matches, existing collection membership, multiple collections, path maps,
  and preview/apply idempotency.

### Stage 5 — assign Kavita series by exact name and previewed pattern

- Support selecting already indexed Kavita series by exact name and a bounded,
  documented pattern expression against series names and optionally local
  folder names.
- Before writes, show every matching series (ID, name, path) and requested
  collections, with count and excluded ambiguities. Require an explicit
  interactive confirmation or a reviewed preview/apply token for automation.
- Reuse the same collection APIs; never add a fuzzy name fallback.
- Tests cover no matches, duplicate names, regex syntax errors, pattern
  examples, stable preview ordering, declined confirmation, and API writes
  only after confirmation.

### Stage 6 — reversible missing/corrupt-page repair

- Build exact page repair plans only for uniquely resolved URLs with complete
  expected identities and proven backend support.
- Reconcile only exact archive keys for the target missing/corrupt pages with
  archive backup/recovery evidence; preserve valid files and originals.
- Execute through normal workers/partials/scratch and verify image decode,
  expected page coverage, and archive/state consistency after promotion.
- Unsupported or ambiguous cases remain report-only. Tests cover preview
  no-mutation, missing/corrupt repair, rollback, crash/resume, archive
  restoration, scratch, and post-repair re-audit.

### Stage 7 — docs, validation, acceptance, and merge readiness

- Update package READMEs, CLI registry/help, active plan handoffs, validation
  targets, and generated reports.
- Run focused tests at every stage and full MangaDL/Kavita/module dispatcher
  targets before acceptance.
- Use bounded, user-selected live acceptance. Do not apply repair to the live
  library or perform a Kavita API write until the user approves the preview.
- Review branch-only commits and main-only validation evidence; preserve the
  independent Kavita feature in this authorized integration. The user approved
  merging into main on 2026-10-12. Live repair and Kavita collection writes
  remain preview-first and have not been performed.

## Open decisions / assumptions

- “By name” defaults to exact case-insensitive match; substring matching is
  available only through explicit pattern selection.
- Pattern syntax is Python regex unless user prefers glob syntax; preview is
  mandatory either way.
- SSD means `cross_platform.storage_media_for_path` reports solid-state for
  either destination or scratch. Unknown is treated as non-SSD for the
  four-worker policy.
- Removing the fixed ceiling does not remove aggregate CPU-budget enforcement.
- Stage 6 repairs only page identities with exact backend and archive mapping;
  other cases stay manual/report-only.
