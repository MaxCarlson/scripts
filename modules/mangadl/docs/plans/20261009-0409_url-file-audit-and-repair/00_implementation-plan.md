# URL-File Audit and Missing or Corrupt Image Repair

## Goal

Extend MangaDL's existing `audit` flow so a user can audit every URL in a URL
file, determine whether each source has a uniquely identified destination and
all expected images, identify missing or unreadable images, and explicitly
repair supported cases into the correct source folder. Preserve a read-only
default and make every network or filesystem repair an explicit apply action.

The user-facing target is a command along the lines of:

```powershell
mangadl audit -u .\URLFILE.txt -d B:\Hent\hent1imageperpage
```

The existing `-i/--input-file` behavior must remain compatible. Decide during
Stage 1 whether `-u/--url-file` is a clear audit-only alias or whether the CLI
should direct users to `-i`; do not reinterpret `run -u/--url` (direct URL).
Audit must remain distinct from `run`: it inspects existing state first and
does not download unless a future explicit repair/apply option is selected.

## Current verified design and constraints

- `mangadl audit` (`audit-destinations` alias) currently expands repeated
  `-i/--input-file` globs, loads inputs through `collect_inputs`, scans one or
  more destination roots, and reports missing URLs and duplicate top-level
  folder names. Progress goes to stderr and `--json` writes its summary to
  stdout. The scan is read-only.
- `input.py` preserves source spelling/line provenance in `InputUrl`,
  canonicalizes HTTP(S) host/scheme and nhentai numeric shorthand, removes
  fragments, and rejects duplicate canonical URLs. Audit should retain this
  behavior and report invalid/duplicate lines rather than silently losing
  them.
- `destination_audit.py` treats embedded JSON URL metadata as strongest
  identity evidence, with limited nhentai ID and HDPornComics manhwa-slug
  fallback matching. Its `_has_images` check only confirms that one
  recognized-extension file exists; it does not decode images or establish
  completeness. Ambiguous matches must never be repaired automatically.
- `backends.py` routes URLs among gallery-dl, native nhentai, HDPornComics,
  and Manga18FX, with collection classification and rejection rules. The
  audit must use this same routing decision and preserve exact URL semantics;
  it must not infer expected page counts from directory names.
- MangaDL state lives in `<destination>/.mangadl/state.sqlite3` and records
  per-run URL, backend, state, attempts, progress, destination, and errors.
  It is useful diagnostic/provenance evidence, but a historical successful
  job does not prove current files remain intact.
- The gallery-dl archive is media-key-oriented. Partial owners record exact
  archive keys and paths in `.mangadl-archive-entries.jsonl`, and partial
  metadata binds URL/backend/archive/run ownership. Archive rows are not a
  completeness oracle: a file may later be deleted, truncated, or corrupted
  while its key remains archived.
- Normal workers download into URL-keyed `_partial` owners and merge completed
  output; scratch mode has separate owners, destination checks, promotions,
  and control-database sync rules. Existing partial safety rules must be
  reused. Do not write directly into an active owner, move legacy partials,
  or run the same URL/library concurrently.
- `repair` currently handles only loose `nhentai_<id>_<page>.<ext>` files.
  It resolves nhentai metadata, plans moves, requires complete page coverage,
  and defaults to dry-run. It does not fetch missing pages or validate images
  already in a gallery folder.
- Kavita collection assignments are stored in
  `<destination>/.mangadl/kavita-assignments.json`; application and later
  reconciliation use unique exact folder paths plus explicit path maps. A
  repair must not duplicate assignments or apply changes to Kavita as a side
  effect. Keep assignment records associated with the same canonical URL and
  resolved local folder.
- The root/module docs contain historical and active plans. The active branch
  is `codex/kavita-module-mangadl-collections-20261009-0349`; do not replace
  its in-progress Kavita work or change its approval status.

## Proposed architecture

Keep URL-file parsing, source resolution, file inspection, planning, and
mutation as separate layers:

1. **Input and identity layer:** parse URL files with existing `InputUrl`
   semantics and preserve each source path/line, supplied URL, canonical URL,
   and duplicate/rejection reason.
2. **Source resolver:** return a structured per-URL result containing backend,
   source identity, expected local folder candidates, expected page/image
   identities (when knowable), provenance for those expectations, and an
   explicit `complete`, `incomplete`, `ambiguous`, `unsupported`, or
   `unknown` resolution state. Adapters own backend-specific metadata
   enumeration; a successful empty enumeration is distinguishable from an
   unsupported or failed probe.
3. **Local inspector:** enumerate candidate files deterministically, map
   files to expected image identities, and record missing, duplicate,
   zero-byte, unreadable, and malformed files. Validation must use bounded
   reads and the project's supported image-decoding capability; tests must
   cover truncated data and format/extension mismatches. Do not classify an
   image as valid based only on extension, size, or a matching archive row.
4. **Audit report and repair planner:** produce stable JSON and human output
   from structured evidence. A repair plan binds each operation to canonical
   URL, backend, exact expected item, exact folder, damaged/missing local path,
   and any archive key that can be safely reconciled.
5. **Repair executor:** dry-run by default; `--apply` is required before
   network or library mutation. Reuse manager/worker, backend routing, retry,
   partial ownership, scratch, and archive safety primitives where possible.
   Keep valid images untouched. Verify repaired files and the full expected
   set before reporting completion.

Adapters that cannot enumerate a complete expected page set or safely redownload
one item must return `unknown`/`unsupported`, retain the findings, and refuse
automatic repair for that URL. Never represent an unknown count as complete.

## Stages

### Stage 1 — contract, CLI, and structured audit result

- Define audit states and output schema, including URL provenance, backend,
  matching candidate paths, expected-count provenance, observed file counts,
  missing/corrupt/duplicate items, ambiguity, errors, and repair eligibility.
- Preserve `audit`, its `audit-destinations` alias, repeatable input files,
  multiple destinations, current missing/duplicate outputs, stderr progress,
  JSON stdout cleanliness, and existing parser behavior.
- Decide and document audit `-u/--url-file` alias semantics without changing
  `run -u/--url` direct URL behavior.
- Keep the command read-only unless `--apply` is explicitly present. Preview
  output must state which URLs cannot be completely verified and why.
- Tests: CLI compatibility/help, URL canonicalization/provenance, comments,
  malformed lines, repeated files/globs, duplicates, JSON/stdout versus
  progress/stderr, no writes in default mode, and backward-compatible output
  files.

### Stage 2 — exact folder/source matching and backend completeness adapters

- Refactor the existing destination match into reusable evidence-producing
  code. Prefer canonical URL metadata; retain current conservative nhentai ID
  and HDPornComics slug fallback only as candidate evidence, and label it as
  weaker than embedded exact URL metadata.
- Detect multiple candidate folders across roots and multiple source URLs
  claiming the same folder. Mark ambiguous ownership and prohibit repair.
- Add an adapter protocol around `choose_backend` that resolves stable source
  identity, the folder layout, and expected page/image identity set with
  explicit provenance.
- Start with backends for which source enumeration and layout can be proven
  from existing code. Confirm gallery-dl metadata-only enumeration does not
  download and does not mutate the active archive. Determine Manga18FX's
  expected page identities from its existing parser/manifest flow. Treat
  native nhentai and HDPornComics independently; do not infer support merely
  because `run` supports them.
- Collection URLs, unavailable/auth-required metadata, changing source
  contents, and backends without deterministic page identities remain
  `unknown` until a safe resolver exists. Preserve `--allow-collection`
  semantics; audit must not expand broad collections unexpectedly.
- Tests: adapter selection, expected identities, no-download/no-archive
  mutation probes, unsupported and partial metadata, API errors, collection
  refusal, stable URL-to-folder association, and ambiguity.

### Stage 3 — local image integrity and audit reporting

- Inspect only uniquely owned candidate folders; enumerate nested layouts
  according to the selected adapter and avoid counting control files, sidecars,
  temporary files, or unrelated images.
- Match file identity to expected page identity, preserving natural page order
  and explicit indices. Report missing numbers, duplicate numbers, unknown
  extras, zero-byte files, decode failures/truncation, and extension/format
  mismatch separately.
- Bound directory traversal, image size, decoder work, and error details so a
  large library scan has visible progress without unbounded memory or noisy
  JSON stdout.
- Add report fields for expected, present-valid, missing, corrupt, duplicate,
  extra, and unverifiable counts plus evidence and error summaries. Keep the
  existing human summary concise and machine-readable JSON deterministic.
- Tests: valid fixtures for supported formats, zero-byte/truncated/corrupt
  fixtures, natural ordering, missing/duplicate numbering, nested layouts,
  ignored controls, read/permission errors, progress, and repeatable stable
  JSON.

### Stage 4 — dry-run repair planning and archive-safe targeted redownload

- Add a repair plan that includes only uniquely matched URLs with a complete
  expected set and precisely identified missing/corrupt page identities.
  Ambiguous, unknown, collection, or unsupported results remain report-only.
- Require `--apply`; a dry-run prints exact URLs, destination folders, file
  actions, archive actions, backend routing, and unresolved risks. No network,
  archive, state, assignment, or library mutation occurs during preview.
- Preserve corrupt originals using a reversible quarantine/backup naming and
  manifest policy. Never silently overwrite a different valid file. Decide
  recovery/rollback semantics before coding.
- For gallery-dl, use only verified source-specific expected archive
  key/path mappings. Remove or bypass only the exact archive entries for
  identified damaged/missing items, with a pre-mutation archive backup or
  recoverable transaction. Do not clear all keys for a URL or delete by fuzzy
  path. Reconcile both canonical and active scratch archives under existing
  scratch rules.
- Download through the normal worker/partial ownership lifecycle with bounded
  retries, rate/concurrency policy, cookies/auth, and existing destination
  checks. Promote only verified target pages; retain partial owner, logs, and
  archive manifest on interruption/failure. Do not launch a second manager
  against the same library/URL.
- Verify repaired files decode, expected page identities are covered, valid
  pre-existing files remain unchanged, and archive/state evidence matches
  the resulting local files before marking repaired.
- Tests: dry-run no mutation, exact archive-key targeting, archive backup and
  rollback, missing and corrupt page repairs, existing valid preservation,
  conflicts, auth/network failures, interruption/resume, scratch mode, retry
  bounds, and post-repair incomplete detection.

### Stage 5 — Kavita assignment continuity and user documentation

- Preserve existing URL-to-folder Kavita assignments. A repaired URL remains
  associated with its exact resolved folder; do not create a second assignment
  record or apply collection mutations implicitly.
- If audit discovers a valid folder absent from the assignment store, report
  this as informational only. Keep `mangadl kavita reconcile` as the explicit
  path for pending assignment application after Kavita scans the folder.
- Update module README and CLI examples with URL-file audit, interpretation
  of unknown/incomplete states, image validation limits, dry-run/apply
  behavior, recovery/quarantine, archive/state semantics, and backend support
  matrix. Update docs handoffs, checklist, and validation targets as the stage
  implementation proceeds.
- Tests: assignments unchanged by audit/repair planning, exact-path
  continuity after repair, and no Kavita API writes without the existing
  explicit apply controls.

### Stage 6 — bounded acceptance and rollout

- Run focused audit/adapter/repair tests, the full MangaDL tests, CLI help and
  JSON checks, compile/Ruff, and the repository validation dispatcher target.
- Use isolated temporary destinations and mocked network/API behavior by
  default. Record exact commands and results in plan status and validation
  reports.
- Before any live download acceptance, review a small user-selected URL set,
  exact destination roots, expected requests, and maximum transfer volume.
  Do not use an unknown-size or broad collection acceptance run by default.
- Require a read-only audit preview first; compare planned repairs and
  counts, then apply only the approved bounded set. Verify resulting page
  identities, image decode, archive/state continuity, partial cleanup state,
  and Kavita assignment continuity.
- Stop at user manual validation before commit/push/merge unless the user
  explicitly authorizes those actions.

## Cross-cutting safeguards

- Audit never edits files or databases by default. Network metadata probing
  must be separately disclosed in output and must not download page payloads.
- Do not trust manager `success`, gallery-dl archive rows, image extension,
  folder name, or image count alone as proof of present-day completeness.
- Missing expected-set evidence means `unknown`, not `complete`; source changes
  after a prior run are detected where the backend exposes stable page IDs or
  content metadata, otherwise reported as a limit.
- Resolve a URL to one exact destination or refuse repair. Preserve canonical
  source URLs and provenance; never merge duplicate-looking folders
  automatically.
- Preserve normal destination, scratch, partial ownership, archive manifest,
  retry/backoff, authentication, and worker-concurrency behavior. Keep control
  databases/logs and credentials out of public report fields.
- Preserve originals and keep repair reversible. A failed repair must leave
  enough manifest, logs, and archive evidence to resume or roll back safely.

## Approval and implementation boundary

The user explicitly approved implementation on 2026-10-09. Proceed through
the stages below, preserving the repository's manual-validation pause after
each stage unless the user explicitly waives those pauses. Live acceptance,
commit, push, and merge remain separate approval gates.
