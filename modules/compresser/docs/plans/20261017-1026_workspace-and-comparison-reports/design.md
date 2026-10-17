# Compression workspace and comparison report design

Approved direction: the user's revised terminal mockup and one-folder artifact workflow,
2026-10-17. This document makes implementation decisions explicit; no implementation
or production operation has been performed. Baseline: `64b33d1`, branch
`compression-ui-color-and-stats-20261017`.

## Intent and scope

Make comparison results readable and actionable without requiring a full-library
encode. Show estimated whole-target impact first, sample coverage and limitations
alongside it, and save the same summary as Markdown automatically. One compression
workspace owns ordinary persistent analysis artifacts. Share behavior between
standalone compresser and MangaDL; retain MangaDL's page/source/partial safeguards.

Do not implement the previously paused Plan03 P8 canonical argument overhaul,
pilot/confirmation sampling, codec/thread scheduling changes, automatic lossy writes,
or migration of downloader/repair/source state. Existing actual encoding, sampling
selection, resource policy and write interlocks remain unchanged.

## 1. Workspace contract

For `mangadl compress -d B:\Hent\tmphent3 -I B:\Hent`, resolve:

```text
B:\Hent\tmphent3-mangadl\
  workspace.json
  tmphent3-mangadl-inventory.sqlite3
  tmphent3-mangadl-trials.sqlite3
  reports\latest.md
  reports\<UTC timestamp>-<run ID>-<operation>.md
  previews\<existing unique preview run>\...
```

`-I/--workspace` takes a parent directory, not the resolved workspace itself. With
no `-I`, use the target's parent. Print the resolved workspace. For standalone
compresser use the suffix `-compresser` and equivalent filenames; a single-file
input uses its filename stem as the folder-name component and its parent as base.
Names are valid filesystem leaf names; reject roots without a usable leaf and
request an explicit suitable target (do not guess a drive name).

Pure resolution precedes creation. Workspace must be outside the source tree;
reject linked/reparse workspace paths, source aliases, and inventory/cache/report
collisions. Existing source safety checks still apply. Nonexistent parent directories
may be created only after CLI validation/target ownership checks. A nonempty folder
without a recognized manifest is not claimed. A manifest records schema1, canonical
target path, owner (`mangadl-pages` or `compresser`), creation UTC and naming policy.
Different target/owner or unsupported schema fails with guidance to choose another
`-I` parent. This prevents two equally named targets from silently sharing state.

Use short coordinator-owned workspace publication locks for manifest initialization
and report/latest updates; never pass SQLite handles to workers. Lock ordering is
target guard before workspace publication lock. Revalidate ownership under the lock;
do not hold a workspace publication lock while waiting for encoders.

Inventory and trial cache remain separate SQLite databases with existing schemas,
fingerprint checks and retention policy. Keep SQLite journal/WAL siblings beside
their database. No implicit discovery, copying, renaming or merging of old databases.

### Compatibility

Keep hidden `--inventory-file` as a deprecated alias for one major transition.
An existing file or a nonexistent `.sqlite3`/`.sqlite`/`.db` argument to `-I` or that
alias remains legacy explicit-file mode with a stderr warning. Existing directories
always mean a workspace parent, even if their names have those suffixes. Legacy
inventory stays at the requested path; the legacy trial path remains unchanged;
reports go in a target workspace under its parent. Manifest explicitly records the
legacy paths. Detect normal-vs-legacy manifest conflict rather than switching stores.
Document this temporary exception to consolidated storage. Never silently ignore an
old inventory and do a fresh production scan under `trust`.

`-K` remains an expert external cache override; `-O` remains explicit preview output.
`-O` with no value becomes the opt-in to workspace preview output; an omitted `-O`
does not generate previews. Retain `-n`/quality controls. Scratch `-X` stays external
and disposable, not a persistent workspace artifact. Explicit overrides are printed
and recorded. Inventory-only does not open a trial cache. Cache-off creates no trial
DB. Compression recovery journals/backups remain at their existing source-safe paths;
recovery itself is excluded from this reporting redesign.

This is a breaking default/path contract: next available major versions for
compresser and MangaDL, synchronized dependencies, registry and full wrapper reinstall.
No other compression arguments are redesigned here.

## 2. Whole-target extrapolation, not a coverage gate

Maintain the existing gallery/design-based estimate separately. Add an explicit
`format_ratio_v1` model-based extrapolation; do not relabel it as design-unbiased
or attach the old confidence intervals to it.

For each strategy and original decoded source format f:

`ratio_f = sum(original_bytes - retained_bytes) / sum(original_bytes)`

Use all completed selected trials, including validated cache hits. Failed trials
retain original bytes and contribute zero savings; unchanged originals likewise.
Group using inventoried source format (normalize JPG/JPEG), not requested output.
For an unsampled format, use the overall sampled byte-savings ratio and mark its
population bytes as fallback. Sum `inventory_bytes_f * ratio_f`; estimated retained
bytes = inventory total minus that sum. Round only the final summed byte result.
Do not average per-image percentages. Respect signed growth if allow-larger is
explicitly enabled; never display larger retained size as positive savings.

Small samples, missing galleries and singleton observations do NOT suppress the
extrapolation. Coverage warnings remain. No observations or zero sampled original
bytes is genuinely insufficient evidence; do not divide by zero or invent a ratio.
An all-failed strategy has a zero-retention-change scenario labeled `no successful
encodes; originals retained`, and is excluded from highlights. Format fallbacks
are not measured evidence for that format.

Full selection with a result for every eligible image uses exact retained totals
and `Calculated`, not `Estimated`; failures still retain originals and are flagged.
An interrupted census is not complete; partial observations can only produce an
explicit partial model extrapolation. Unknown-size/unreadable inventory entries are
excluded from calculable totals and counted visibly; file-only inventory is unverified
and must never authorize encoding or fabricate SSIM/size predictions.

## 3. One report model, multiple renderers

Use a versioned data model for coverage, per-strategy impact/outcomes, highlights,
issues, execution/resource facts, snapshot scope and workspace/report paths. Compute
once from current input metadata and results, render console and Markdown from it.
Keep existing JSON keys/semantics; add `extrapolation` and report-artifact metadata,
do not replace old `estimate` fields. Do not persist raw ImageResult lists unnecessarily.
Capture compact per-format totals, complete structured error counts, actual strategy
settings and current-run wall-time facts before batch results leave scope.

Section order:

1. Target/read-only or applied status and resolved workspace.
2. Sample coverage: per-format target count/bytes, sampled count/bytes, count/byte
   percentages; total and galleries sampled/total, method/seed, fallbacks and freshness.
3. Whole-target impact: ID, strategy/quality, mean SSIM, estimated retained/saved bytes
   and reduction. `Calculated` labels for completed census.
4. Outcomes/execution: failed, unchanged, cached, actual trial rate and interpretation.
5. Qualified highlights: largest estimated reduction, higher-SSIM alternative,
   lossless alternative. No contradictory independent hero fallback.
6. Issues: complete grouped reason counts with per-strategy attribution, never just
   the existing top3 formatted strings. Preserve originals on failures.
7. Resource/cache summary; per-strategy phase timing and raw candidate-size diagnostics
   only under verbose output. Distinguish wall time, task-seconds and estimated RAM.
8. Preview/refine/refresh next steps, saved report path and final operation status.

Units are binary MiB/GiB from byte values. Mean SSIM includes unchanged originals;
no `imperceptible` promises or `bit-for-bit exact` lossless claims. Cached throughput
is not encoding speed and cannot determine a speed winner. Zero/nonfinite/unmeasured
rates display truthful status; investigate rate construction rather than replace
zero with a made-up value. Highlights exclude entirely failed/no-positive scenarios;
partial failures and extrapolation fallback remain visible. Higher-SSIM alternative
uses the existing0.98 heuristic, labeled as a heuristic, not a guarantee.

No prominent automatic write recommendation from a small sample. Preview guidance
can include a copyable command generated from actual settings, with PowerShell quote
escaping, explicit URL filters and appropriate preview operation. If an apply example
is included in verbose details, preserve effort/algorithm/resource/filter settings
and required `-L`; never infer mode from a strategy-name substring.

## 4. Responsive console and Markdown

One logical results dataset; wide terminals combine fitting columns. Otherwise split
columns into stacked panels, repeat ID/strategy and preserve identical row order.
No ellipsis truncation of headers, identifiers or numeric values. Very narrow widths
use wrapped labeled records. Other tables wrap cells including long paths/errors.
Use TermDash for reusable layout; add an opt-in panel renderer, without changing
existing callers' truncation behavior. Visible width handles ANSI, combining/CJK
characters; non-SGR control characters in filenames/errors are escaped, not executed.

Use cyan/blue headings and IDs, green positive savings, yellow coverage/partial-failure
warnings, red errors/all-failed statuses, muted neutral values. Text labels carry meaning
without color. Honor stdout TTY, NO_COLOR and TERM=dumb; stderr TTY alone must not
inject ANSI into redirected stdout. Both renderers share facts and issue counts.

Markdown is terminal-width independent: conventional tables by logical section,
escaped pipes/backticks/newlines, no ANSI/progress animation. Wrap commands in fenced
code, not tables. Do not capture arbitrary stdout, subprocess logs or secrets.

## 5. Automatic durable reports

Inventory, comparison, single analysis/write and preview operations publish summaries
to reports, including JSON-mode operations (stdout remains machine-parseable).
Inventory creation/refresh MUST save its inventory report: verified/unverified depth,
counts/bytes by format and gallery, unreadable/excluded counts, profile information
when available, freshness and resolved artifacts. Other detailed summary output is
also retained in the operation report; verbose affects console verbosity, not whether
available summary diagnostics are preserved in Markdown. This does not require raw
per-file listings, animation frames, private subprocess logs or undocumented debug dumps.
Timestamp/run-ID archives are exclusive and never overwritten. Write validated temp
content in the destination directory, flush, then atomic publish. Update latest only
after archive publication; latest means most recently published run, including a
clearly marked partial/failed run. Coordinator owns publication, after workers drain.
No report from parser validation failures. After run context exists, catch cancellation
or operation errors for best-effort partial reporting without masking the original error.

A reporting error prints its path/actionable cause to stderr, preserves an older
latest where publication did not succeed, and returns exit2 if computation otherwise
succeeded; preserve original nonzero/cancellation exit status. A completed compression
with report failure must say images may already have been modified, not recommend
blindly rerunning writes. No automatic deletion or report-retention pruning.

## Validation and documentation

Generated fixtures only; no B:\Hent scan/encode/write is authorized by this plan.
Test80/100/120/160-column and very narrow outputs, CJK/combining/ANSI, NO_COLOR,
redirected streams, complete/partial/failed/cache-only runs, path aliases, workspace
ownership/concurrency, legacy files, atomic publication and Markdown/JSON parity.
Manual real Windows terminal resizing and reader visual quality remain explicit gates.

Docs freshness assessment at64b33d1: compresser/MangaDL README+handoffs stale80/100
(several user-facing changes since last update); TermDash needs review60/100 (ANSI
table change newer than handoff). Update affected docs during delivery, including current
memory policy from live code, without resurrecting the paused CLI overhaul.

Execution authorized by the user2026-10-17 after written plan review.
Execution method: native/inline, preserving the user's existing workflow. Each usable
checkpoint gets focused/full affected tests before scoped commit/push under applicable
explicit authority; no automatic merge. User chose the current feature branch.
