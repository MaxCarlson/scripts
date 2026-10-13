# Reviewed compression implementation plan

Branch: `compression-module-mangadl-20261013-0151`; baseline HEAD `9a8e95b`.

## Goal and scope

Provide independently usable `modules/compresser` library/CLI and thin
`mangadl compress` adapter. Analyze JPEG/WebP libraries, compare supported
encoders under explicit quality constraints, optionally apply smaller verified
results. Reuse termdash. Preserve pre-existing work. All seven predecessor plan
documents were read; REVIEW.md supersedes their completion claims.

## Contract and decisions

- Analysis/comparison NEVER recover, rename, delete or rewrite source images,
  journals, manifests or download state. Optional caches use a separate explicit
  location. Dry-run means no source-tree mutation even when recovery is pending.
- Both CLIs default to lossless. Writes need `-w/--write`; lossy/perceptual writes
  additionally need `-L/--allow-lossy`. Quality is an encoder setting, not a
  percentage of lost visual quality. Validate ranges and contradictory options.
- No silent format/codec fallback. Unavailable combinations report reasons.
  `keep` preserves extension and format. Explicit oversized WebP is refused;
  auto may evaluate supported alternatives.
- JPEG coefficient optimization passes ORIGINAL JPEG bytes to jpegtran with
  portable `-outfile` and `-copy all`. Pillow JPEG and AVIF quality=100 aren't
  lossless. Verify lossless decoded samples/dimensions/alpha and metadata.
  Refuse unsupported color/bit-depth/frame conversion rather than discard data.
- Preserve ICC, EXIF orientation and supported XMP. Reject animated inputs until
  all-frame fidelity is tested. MangaDL excludes covers, hidden controls,
  `_partial`, sidecars and links, and refuses active download/repair conflicts.
- Never overwrite/delete existing output collisions. Recheck source fingerprint
  before publication. Cross-extension publication is NOT atomic: use durable
  journaled transitions, exclusive writer ownership, unique temps, hashes and
  containment validation. Same-extension replacement uses `os.replace`, not move.
  Explicit preview-first recovery refuses legacy/malformed/externally changed
  records; unresolved evidence survives. Never delete based only on decodability.
- Enforce decode/resource bounds before loading. Keep Pillow guards enabled.
  Bound aggregate decoded/metric buffers and queued futures. An unused max-pixels
  constant does not implement memory safety.
- Preserve page stems and audit defect sets, including pre-existing missing,
  corrupt/duplicate pages. Conversion cannot prove remote completeness or archive
  correctness. Do not promise universal reader compatibility.

## Stages (implement in order)

### S5 — safety/fidelity

Remove dry-run recovery; owned durable transactions and explicit safe recovery;
collision/concurrent-writer/source-change refusal; true codec dispatch and JPEG
lossless path; WebP alpha/sample fidelity; perceptual below-threshold rejection;
full output verification. Validate CLI/exit status/JSON purity. Fault-inject every
publication/recovery stage, source/target drift, and concurrent workers/processes.
Isolated fixtures only. No live writes at this gate.

### S6 — measured analysis/selection

Real PNG codec and selectable supported encoder/effort. Auto chooses smallest
passing measured candidate in a bounded codec/settings set, including original.
Do not add content-classification heuristics unless measurements justify them.
Cache inventory and benchmark results across sessions using source identity,
actual codec/version, metric revision and every output-affecting setting. Validate
inventory incrementally; distinguish cached lookup speed from encoding throughput.
Stratify sampling by format/size/dimensions; label measured vs projected savings,
coverage, uncertainty, exclusions and failures. Unsupported files aren't successes.
Replace high-memory SSIM window products with bounded separable filtering; protect
color/detail differences rather than call thumbnail luminance a visual guarantee.

### S7 — shared UI/exact integration

Actual TermDash rendering, not handwritten ANSI cursor control. stderr progress,
clean JSON stdout, NO_COLOR/plain redirected output, Unicode/narrow/resize handling,
finally cleanup. Active/last file, genuine gallery and overall completion,
elapsed and rolling 15-second ETA; unknown when stalled/unmeasurable. Pillow
encoding exposes no percent callback: activity only, not fabricated percentages.
MangaDL URL filters resolve canonical exact identities via library index; explicit
folder selection stays separate. No URL/title substring matching.
Termdash table must enforce width and terminal-cell-safe clipping; bar edge widths
have tests. Document actual exports/options/API signatures, not designed names.

### S8 — acceptance

Focused regressions at each gate; full affected suites, Ruff/compile/help,
dispatcher evidence, installed CLI/version sync including MangaDL shim; real
Windows terminal/resize/redirect and isolated fixture write acceptance. Pre/post
audit defect non-regression and metadata/alpha/frame/tall fixtures. Production
compression needs a separate scoped user choice. No merge.

## Scope control and publication

Implement Pillow JPEG/WebP/PNG and optional verified jpegtran first. Defer JXL and
unverified mozjpeg/jpegli/cwebp wrappers. AVIF remains explicitly lossy/opt-in until
constraints are proven. Stage/commit/push docs first, then implement directly as
authorized. Only task files, never runtime caches/SQLite. Keep planning separate
from implementation commits and update handoffs/status at each gate.

Audit work: [module-owned follow-up](../../../modules/mangadl/docs/plans/20261013-0300_audit-ux-and-manual-folder-repair/00_implementation-plan.md).
Keep `audit -F . -d .` explicit discovery; `audit -d .` remains folder-only.
