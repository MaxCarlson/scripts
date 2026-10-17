# Inventory, estimation and compression command redesign

Date: 2026-10-17 America/Los_Angeles. Native execution authorized; currently paused
for model handoff. Read [execution-review.md](execution-review.md) for binding execution
clarifications, stronger-model gates and current implementation evidence.
Baseline: `8cdc7fe91e289abe68a26666d3fe5a914ab6abb4`, branch
`compression-ui-color-and-stats-20261017`; parent checkout clean when inspected,
with inaccessible `pscripts` excluded. No implementation, installation, commit,
push, migration, deletion, production scan or image write authorized by this plan.

## Intent and success criteria

Estimate library savings without turning the estimate into a near-complete compression
job. Inventory describes the complete population; separate estimation plans select
small random samples and the particular recipes each sample needs. Bound expensive
work, explain uncertainty, resume completed measurements, simplify both command
surfaces and retain the polished shared terminal/Markdown reporting already delivered.

The user explicitly permits a breaking replacement: no old CLI aliases, compatibility
parser, old workspace discovery or old inventory/plan import. Existing files remain
untouched. New inventories/plans may be rebuilt. Preserve internal safety and useful
engine capabilities, rather than preserving obsolete syntax.

## Evidence and previous plans

- `distribution.py:SamplingProfile.from_images/from_file_report` currently recommends
  `min(N,max(sum(min(2,N_gallery)),ceil(.01*N)))`; this is a heuristic, not measured precision.
- `sampling.py:gallery_sample` and `GallerySample` select within galleries; confirmation
  support in `confirmation.py` adds known pilot totals to an estimate of the remainder.
  Its normal intervals explicitly do not support outcome-adaptive repeated stopping.
- `cli.py:run_comparison` enumerates PNG/WebP/JPEG/AUTO strategies and evaluates each
  on the same complete selected list. Multi-quality settings multiply that work.
- `file_inventory.py` already persists per-file paths/bytes, not just folder summaries.
  `validate_analysis_arguments` currently restricts file-depth to inventory-only.
- `workspace.py` produces `<target>-mangadl` / `<target>-compresser`; its ownership,
  link, samefile and reserved-artifact checks are substantive safeguards.
- `report_models.py`, `reporting.py`, `report_session.py`, `markdown_report.py`, `ui.py`
  and TermDash own the recently completed shared report and progress experience.
- Completed workspace/report plan: `../20261017-1026_workspace-and-comparison-reports/`.
  Preserve its implemented safety and visual requirements.
- Paused repository Plan03 P8 in `docs/plans/20261013-0600_compression-performance-sampling-and-cache/`
  proposed canonical argument merging. This design replaces its unimplemented P8 and
  unimplemented repair Task6; earlier exclusion of pilots applied to that earlier work.
  Do not execute either historical task in addition to this replacement.

## Considered approaches

1. Retain inventory's large starter heuristic and accelerate the full comparison matrix:
   insufficient, because work still scales with gallery coverage and recipe count.
2. Fix a small inventory-owned pool once: simple, but couples population discovery to
   later accuracy/recipe choices and can make pool exhaustion an artificial barrier.
3. Recommended: full descriptive inventory, separate reproducible estimation plan,
   bounded pilot/confirmation and image-recipe scheduling. A distinct-image cap belongs
   to the plan; expanding it never requires rescanning an unchanged inventory.

## Workspace contract

`-I/--workspace` means the parent beneath which the owner directory is placed.
For target `B:\Hent\hent1imageperpage` and `-I B:\Hent`:

```text
B:\Hent\.mangadl\hent1imageperpage\
    workspace.json
    inventory.sqlite3
    trials.sqlite3
    plans\<plan-id>.json
    reports\<existing unique operation report names>
    previews\<existing unique preview run directories>
```

Standalone uses `<parent>/.compresser/<target-leaf>/`. Default parent remains target
parent. File targets use the full filename (including extension) as leaf to avoid
`page.jpg`/`page.png` sharing state. Reject ambiguous existing owner manifests, linked
ancestors, workspace-inside-source and reserved database aliases before creating files.
Two different targets with the same leaf and parent fail explicitly; user chooses a
different parent. Do not invent a hidden disambiguating suffix or overwrite ownership.
For a whole-library target `B:\Hent`, explicitly choosing parent `B:\Hent` would put
artifacts inside the source and must fail; its default parent `B:\` stays outside.
Normal Windows dot-prefixed directory naming is sufficient; no Hidden attribute needed.
The `.mangadl` container has no exclusive target owner; each target workspace does.
If `.mangadl` already contains downloader controls, never claim/rewrite those controls.
No old-path probing, automatic moving/copying/deletion or inventory schema migration.

## Inventory and plan separation

Inventory refresh remains encoder-free. It records full eligible membership, metadata
depth, fingerprints, errors, exact MangaDL filters, scanner revision and population ID.
Descriptive profile revision 2 removes `starter_samples` and per-gallery quota advice.
Format counts/bytes, size summaries and known restrictions remain useful.

Plans are operation artifacts, not inventory output. `plan` reads an existing completed
inventory and writes a plan without encoding. `estimate` may construct a plan implicitly.
Both fail with an inventory command hint when no matching inventory exists; neither
silently refreshes it. Snapshot age/staleness is shown. Selected files are revalidated
before using measurements. Changed selection/metadata invalidates a plan; rebuild it.

Use extension groups for file-depth and actual-format groups for header-depth. Within
each format, at most four log2-size bands, merging adjacent bands until each has at
least eight files (unless the whole format has fewer). Known codec-ineligible classes
remain separate. Do not require each gallery to be represented. Seeded per-group
uniform random priority orders provide stable prefixes; persist the hash algorithm,
seed, ordering revision, selected identities and quotas. Do not materialize every order
in JSON: membership stays in SQLite; selected prefixes suffice with the population ID.

At file-depth inspect only selected image headers, maintaining their original selection
weights. Unsupported/unreadable images are never silently dropped or replaced. Report
unresolved bytes unless the requested policy explicitly defines retaining originals.
These results describe inventoried candidates; do not claim a census of valid images.

## Recipes and budgets

Recipe identity includes effective encoder/version, format, mode, quality, effort,
metadata/alpha/dimension policy and retained-original policy. No implicit comparison
matrix or AUTO expansion. Multiple formats/qualities describe explicit requested recipes;
lossless produces one effective recipe per distinct settings identity, not one per q.
Reject contradictory settings rather than silently ignoring an explicit option.

Proposed defaults for estimation (policies, not precision claims): max 512 distinct
images, 2,000 new candidate encodes, 300 seconds active run time; pilot at most 64
images per recipe subject to the shared caps. If coverage cannot fit, report uncovered
groups; never enlarge caps to force coverage. Changing caps does not rebuild inventory.
No default accuracy target. With `--accuracy-pp`, the target applies simultaneously
to requested exact recipes, with 95% family confidence in certified sequential mode.

Trial admission is enforced at actual codec encode entry, including AUTO candidates,
perceptual searches, retries and failures. Cache hits cost zero new encodes. Completed
measurements include candidate bytes, retained bytes, status, phase timings and policy.
Track executed and reserved tokens atomically to avoid concurrent overshoot. Time is
monotonic from controller start and includes validation/cache/encoding/report preparation;
stop admitting at deadline. In-flight native encodes drain and may exceed wall time.
On resume, explicitly supplied budgets are additional per-invocation allowances; plan
keeps cumulative counts. Accuracy continues to refer to the same population/recipes.

## Statistical delivery

### A. First usable estimator: fixed pilot and confirmation

Pilot learns cost and variation by group/recipe. Freeze disjoint confirmation quotas
before observing confirmation outcomes; uniform draws come from remaining membership.
Start with stratified totals plus known pilot totals, finite-population variance and
explicitly approximate intervals. Pilot-based cost/variance allocation includes coverage
floors and caps. A budget-limited run may miss its accuracy goal.

Then introduce a frozen per-group linear predictor `m_i = a_h + b_h * input_bytes` from
pilot observations (constant prediction when data are insufficient). Estimate:

```text
sum(actual savings on pilot)
+ sum(predictions over remaining population)
+ sum_h(N_remaining_h * mean_confirmation(actual - predicted))
```

Use confirmation residual variance; group counts and byte totals suffice to sum linear
predictions. Missing/failed observations make the affected contribution unresolved.
Avoid `ImageResult.saved_bytes` clipping for signed force-conversion estimates: compute
input minus retained/candidate bytes explicitly. Approximate signed intervals may be
reported for fixed complete designs; do not claim rigorous stopping for unbounded growth.

An interrupted/incomplete frozen batch does not receive its planned interval. Retain
its measurements for resumption, show interim descriptive results and the most recent
complete valid interval, if any. Never use the fastest finished tasks as a random sample.

### B. Certified repeated accuracy stopping

Separate checkpoint after A is validated. Do not apply ordinary normal intervals after
adaptive top-ups. Start with a conservative bounded-without-replacement Hoeffding method
and alpha spending; tighter methods require separate evidence and tests.

For recipe index k>=1 and round r>=1 with H groups, give each group
`delta = .05 * 2**(-k) * 2**(-r) / H`. Each complete round freezes quotas/predictor using
past information, counts all earlier observed values as known, then draws uniformly
from the remaining per-recipe population. For residual `y_i-m_i`, known input bounds
under keep-smaller policy give lower `-max(m_i)` and upper `max(input_bytes_i-m_i)`.
For residual range width W and n samples, use total half-width
`N_remaining * W * sqrt(log(2/delta)/(2*n))`; sum group half-widths. A census remainder
has exactly zero uncertainty. Union bounds cover groups, recipes and all completed
rounds, including adaptive allocations. Intersect valid intervals across rounds.
Sparse groups may yield very wide intervals; disclose this rather than promising speed.

This conservative method supports early accuracy stopping, recipe-specific frozen quotas
and time/trial/image caps. Near-zero savings use absolute percentage points of source
bytes, not relative error. Certified mode requires bounded keep-smaller outcomes and
complete prescribed observations. Unknown failures block certification for that recipe.
Accuracy control with allow-larger is rejected in this first certified implementation.
Adding/changing recipes or reusing results from a different design requires a new plan;
cache values may satisfy preselected jobs but cannot choose the confirmation sample.

### C. Quality exploration

Explicit quality lists are measured exactly. A later opt-in quality range uses per-codec
anchors and held-out checks; intermediate predictions are labelled interpolated, with
no certified interval. Confirm selected exact qualities with a new registered recipe/plan.
Lossless remains separate. Never select an AUTO library total by minimizing aggregate
recipe totals; AUTO is an image-level policy, measured on selected sources.

## CLI replacement

See [cli.md](cli.md) for canonical operations, exact flag ownership and the old-to-new
decision ledger. Both entrypoints use shared typed options and operation builders.
Validate before workspace setup/locks/report output. No canonical flags accepted in an
irrelevant operation. No flat legacy parser or hidden deprecated aliases.

## UI is a preserved product contract

Keep shared `ReportSession` facts, immutable report sections, TermDash panels, wrapped
full-value records, binary units, colour semantics, independent gallery/overall progress,
live in-place updates and automatic Markdown summaries. Do not replace them with print
loops, rolling log spam, raw escape sequences, hand-written tables or unbounded histories.
Use operation-specific help and focused panels instead of exposing internal model data.

Estimation progress shows recipe, round/phase, completed/new/cache counts, budget remaining,
uncertainty status and stopping reason. Completed trial totals are exact; future totals
are labelled planned/unknown. Keep the last valid estimate stable while another round is
pending. ETA only from sufficient measurements; no invented countdown from encode count.
No candidate bytes on disk unless preview explicitly requested. JSON stdout remains one
machine-readable document; progress/diagnostics go to stderr. Markdown and terminal consume
the same facts and retain complete values in narrow layouts.

Before UI editing capture fixture-backed current report/progress baselines. Verify at
80/120/160 columns, long paths, CJK/control characters, colours on/off, TTY/non-TTY,
cancellation, unknown uncertainty, cache-only and budget exhaustion. Real Windows
terminal resize/colour review is a manual acceptance gate; automated stream tests alone
do not satisfy it. User reader quality review is separate from savings estimation.

## Verification and scope

Each subproject is independently testable: workspace; command migration; estimator;
measurement scheduling/UI; advanced statistics/exploration. Use exact finite populations
and synthetic codec doubles for invariants, plus a small generated real-image benchmark
encoded exhaustively at selected settings to measure sample error/coverage/cost. Statistical
simulation is required; no production library corpus or external services by default.
No image transformation, recovery or library ownership safeguard may be weakened.
No unrelated MangaDL command redesign or automatic deleting of old artifacts.

## Research basis

These are proposed engineering decisions, not measured performance claims. Primary
references consulted in the conversation: Statistics Canada, stratified totals/allocation
(`https://www150.statcan.gc.ca/n1/pub/12-001-x/2019002/article/00006/02-eng.htm`);
Google WebP parameter semantics (`https://developers.google.com/speed/webp/docs/cwebp`);
Waudby-Smith and Ramdas, confidence sequences without replacement
(`https://proceedings.neurips.cc/paper/2020/file/e96c7de8f6390b1e6c71556e4e0a4959-Paper.pdf`).
Review the particular bound implemented at the statistical checkpoint; do not advertise
a stronger guarantee than the implementation and assumptions support.
