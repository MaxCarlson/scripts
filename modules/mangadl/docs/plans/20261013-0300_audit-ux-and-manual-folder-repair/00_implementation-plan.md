# Audit UX and manually mapped folder repair

## Scope

Readable large audits and safe repair candidates for folders lacking source
identity. Reuse existing guarded batch repair/worker/scratch UI, no fuzzy/title
guesses, no implicit URL discovery. `audit -F . -d .` selects URL files;
`audit -d .` stays folder-only. No production apply without reviewed mappings.

## A1 — findings, evidence and associations

Identity (matched/unknown/ambiguous) and completeness are separate. Never hide
defects behind ambiguity. Default details show missing/corrupt/duplicate/extra
pages, while defect-free unknown/ambiguous entries are summary counts. Optional
detail option exposes everything; JSON always retains all findings.
Place colored summary at bottom immediately before Audit report for BOTH modes:
input/duplicate/rejected counts, found/missing folders, completeness and identity
counts (overlapping), affected folders/page totals, inferred versus source-confirmed
missing pages, corruption/duplicates/extras. Unknown-total sequence gaps are
heuristic candidates; numbering may intentionally be non-contiguous and trailing
missing pages cannot be inferred. Explain evidence rather than imply certainty.

Associations: `.mangadl-source.json`, not archive rows. Count already indexed,
missing/safely creatable, created, conflicts, ambiguous, empty and unresolved;
with -x show disabled writes and missing associations, not fabricated zeroes.
URL audit currently backfills exact unique matches by default; repair does after
verification; folder-only stays read-only. Review metadata extraction: arbitrary
URLs in recursive JSON strings are weak evidence; use backend gallery identity
fields and retain rejected/conflicting evidence.

## A2 — per-item in-place progress

One shared termdash-owned3-row stderr block: current URL/folder plus phase/index/
elapsed/ETA; real current-item checked-images bar; overall completed-items bar.
Metadata is indeterminate, never fabricated percentage. Rolling15s ETA, unknown
until measurable and when stalled. Width/Unicode/resize safe; logs cooperate;
quiet/NO_COLOR/TERM=dumb/redirects/JSON/cancellation tested. Folder-only emits
same structured item events rather than only every50 logs. Reproduce Windows
screenshot scenario with terminal capture and slow fake metadata resolver.

## A3 — stable manual URL worksheet

Export defective folders only by default, including ambiguous+defective ones,
as readable numbered worksheet, editable one-line-per-row URL template and
versioned mapping manifest. Bind stable row ID, report digest, exact root/folder,
original defects, file fingerprint and line order. Prefill unique source URL;
unresolved uses NOT FOUND. Preserve existing output files with suffixes.

Proposed commands (not yet implemented):
`mangadl repair-map -r REPORT -o OUTPUT_BASE` exports;
`mangadl repair -r REPORT -i EDITED_URLS -M MAPPING_MANIFEST` previews.
All options short/long. NOT FOUND occupies/skips one row; blanks/extra/missing
lines, malformed URLs, repeated ambiguous URL assignments, report mismatch,
changed/moved folders and manifest conflict fail closed. Never deduplicate away
positional rows or rely on separately sorted lists.

## A4 — mapped repair with existing lifecycle

Supplied URL is manual candidate, not validated historical identity. Resolve
exact source page IDs and available metadata, compare layout/source with selected
folder, show mismatches; explicit plan/token approves pairing. Refuse conflicting
source sidecar, don't overwrite. Unsupported page/filename/backend/archive mapping
or unknown totals remains report-only. Non-contiguous source numbering must be
enumerated; never assume every backend has nhentai sequential IDs.

Route exact approved pages into exact existing folder via normal workers,
scratch/archive backup/quarantine and valid-file preservation. No extra title-named
gallery or implicit merge. Post-repair source coverage verification then missing
association creation; summaries count skipped/unsupported/failed/verified and
association changes. Token binds mapping digest and reviewed pairing. Keep -f/-C.

## Sequence and validation

A1 -> A2 -> A3 -> A4 after compression safety. Focused/full tests at each gate:
ambiguous+defective and unknown gaps; worksheet reorder/drift/NOT FOUND; changed
paths, unsupported source, identity conflict, valid-file preservation, scratch
and failed postverification. Read saved user report only; no broad live audit,
automatic source searches or live repair apply merely for feature validation.
