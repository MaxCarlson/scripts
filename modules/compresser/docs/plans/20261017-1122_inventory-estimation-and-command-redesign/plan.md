# Inventory, Estimation and Compression Commands Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` for native execution or
> `superpowers:subagent-driven-development` if the user selects that method after review.
> Steps use checkbox (`- [ ]`) syntax. Native implementation was authorized on October 17.
> Read [execution-review.md](execution-review.md) before continuing: it resolves design
> ambiguities and records model escalation gates and the current partial checkpoint.

**Goal:** Replace expensive blanket sampling/matrices with budgeted, reproducible
estimation, a clean operation CLI and `.mangadl/<target>` workspaces without UI regression.

**Architecture:** Descriptive inventories feed independent persisted estimation plans.
One shared typed command layer and estimation controller serve both adapters; existing
codec, safety, cache, memory scheduler and report foundations remain. Deliver workspace,
CLI and estimator as independently verified checkpoints; advanced statistics are gated.

**Tech Stack:** Python 3.12 repo venv, argparse, dataclasses, SQLite, Pillow, existing
TermDash/cross_platform, pytest. No new dependency by default.

**Spec:** [design.md](design.md), with exact CLI decisions in [cli.md](cli.md).
Execution supplement: [execution-review.md](execution-review.md); its explicit resolutions
take precedence over conflicting draft wording in these three documents.
Baseline `8cdc7fe91e289abe68a26666d3fe5a914ab6abb4` on
`compression-ui-color-and-stats-20261017`. Recheck HEAD/status before execution.

## Global Constraints

- Implementation and local main fast-forward were authorized. New implementation commits,
  pushes, installs and production operations remain unauthorized.
- No backwards compatibility: no legacy aliases, argument translator, workspace probing,
  inventory import or automatic artifact migration. Old artifacts remain untouched.
- Inventory describes all eligible files; sampling decisions belong to separate plans.
- Validate arguments before workspace creation, locks or failure-report publication.
- Keep ownership/link/hardlink/dimension/metadata/alpha/memory/source-write safeguards.
- Preserve the existing shared polished TermDash/Markdown experience. UI changes require
  automatic layout checks and real Windows visual acceptance; do not claim that acceptance
  from a fake TTY stream alone.
- Use operation-specific short/long options and exact schemas from cli.md; no hidden aliases.
- Time budgets stop admission; in-flight native work drains. Count actual codec encodes.
- Do not promise accuracy, constant runtime, complete image validity or visual quality.
- No automatic inheritance of earlier plans' commit/push authority. Ask only if needed
  under the user's then-current instruction; otherwise leave verified edits uncommitted.

## Review Focus

1. Shared `.mangadl` may already contain downloader state: target ownership cannot claim
   the shared container, alias a database, or escape into the source (Tasks 1, 3).
2. File-depth selections with invalid headers cannot be dropped and replaced; population
   weights and unresolved bytes remain honest (Tasks 4, 5).
3. Fast tasks finishing before a deadline are not a random confirmation sample; partial
   batches cannot acquire full-design intervals (Tasks 5, 7, 8).
4. Internal AUTO/perceptual work and simultaneous workers must obey actual encode caps,
   while cache-only/resumed jobs use correct identities and accounting (Tasks 6, 7).
5. Narrow/CJK/control-character output, new rounds and unknown uncertainty must preserve
   complete values, stable panels and parseable JSON/Markdown (Tasks 2, 7, 10).

## File responsibilities

Existing paths below are module-relative unless otherwise stated.

| Unit | Responsibility |
| --- | --- |
| `compresser/workspace.py` | New target directory layout and ownership |
| New `compresser/arguments.py` | Shared operation parsers and normalized options |
| New `compresser/estimation_models.py` | Immutable recipes, budgets, plan/result contracts |
| `compresser/distribution.py`, `inventory.py`, `file_inventory.py`, `snapshots.py` | Descriptive profile, completed population loading and validation |
| New `compresser/sampling_plan.py`, `plan_store.py` | Format/size random design and atomic plan persistence |
| New `compresser/estimation_stats.py` | Fixed estimator/predictor/interval arithmetic |
| New `compresser/estimation.py` | Pilot, confirmation, caps, resume and stopping coordination |
| New `compresser/measurement.py`, `trial_budget.py`; `engine.py`, codec call sites | Per-source recipe jobs, real encode admission, safe cache/metric reuse |
| New `compresser/sequential_estimation.py` | Certified complete-round bounds/alpha spending |
| New `compresser/quality_curves.py` | Optional explicitly interpolated quality exploration |
| `report_models.py`, `reporting.py`, `report_session.py`, `ui.py`, `markdown_report.py` | Existing shared report/progress contract, extended estimation facts |
| `compresser/cli.py`; `modules/mangadl/mangadl/cli_core.py`, `cli_structure.py`, `compress.py` | Thin adapters; MangaDL exact selection/ownership remains module-owned |

Interfaces are specified as contracts below, not permission to duplicate existing
models. Keep new modules focused; reuse current public types where their semantics fit.

## Verification commands

Run from repository root with `.venv/Scripts/python.exe`. For each task's RED/GREEN
cycle substitute its stated test paths:

```powershell
.venv/Scripts/python.exe -m pytest modules/compresser/tests/TEST.py -q -p no:cacheprovider --basetemp=modules/compresser/.pytest_tmp_root/estimation-N --tb=short
```

At checkpoints affecting both adapters run:

```powershell
.venv/Scripts/python.exe -m pytest modules/compresser/tests -q -p no:cacheprovider --basetemp=modules/compresser/.pytest_tmp_root/estimation-full --tb=short
.venv/Scripts/python.exe -m pytest modules/mangadl/tests -o addopts= -q -p no:cacheprovider --tb=short
.venv/Scripts/python.exe -m pytest modules/scripts_help/tests -q -p no:cacheprovider --basetemp=modules/scripts_help/.pytest_tmp_root/estimation-full --tb=short
```

Only if TermDash changes, run its full suite with its own module-local basetemp.
Run `.venv/Scripts/python.exe -m ruff check <changed Python paths>` and
`.venv/Scripts/python.exe -m black --check --line-length 120 <changed Python paths>`.
Run `git diff --check`; final status uses submodule-ignore fallback if needed.
Record exact outcomes in STATUS.md; historical test counts are not new verification.

## Subproject A: workspace and UI preservation baseline

### Task 1: Change workspace layout without moving data

**Files:** Modify `compresser/workspace.py`, tests/workspace_test.py,
tests/inventory_test.py; `modules/mangadl/tests/compress_test.py`.
**Interfaces:** Keep `resolve_workspace(target: Path, parent: Path|None, *, owner: str)
-> CompressionWorkspace`; remove legacy inventory argument/path detection. Properties
resolve fixed inventory.sqlite3/trials.sqlite3, plans/, reports/, previews/.

- [x] RED: assert `B:\Hent\hent1imageperpage` with parent `B:\Hent` resolves exactly
  `B:\Hent\.mangadl\hent1imageperpage` (use PureWindowsPath arithmetic/unit fixtures,
  local temp paths for filesystem tests). Standalone owner yields `.compresser`.
  Pure resolution creates no files; default parent is target.parent.
- [x] RED: full filename distinguishes file targets; two target manifests with same
  leaf fail; shared `.mangadl` unrelated controls survive byte-for-byte; source inside
  artifact container/explicit parent causing workspace-in-source rejects. Links,
  hardlinked DBs and reserved report/cache aliases reject. Existing sibling
  `<target>-mangadl` is never read, moved or removed.
- [x] Implement versioned manifest and exact layout, preserve atomic publication and
  target guards; update source callers removing legacy behavior. Reject a file-valued
  `-I` before side effects. Do not recursively claim a shared owner container.
- [x] GREEN: run workspace/inventory/MangaDL compression tests and common checks.
  Record new layout and no-migration rule in README at this checkpoint.
- [x] Update STATUS/checklist/handoff with results; commit/push only as authorized.

### Task 2: Pin existing UI/report quality before adding estimator output

**Files:** Existing tests/reporting_test.py, ui_test.py, reporting_layout_test.py if
present (verify exact filenames); add tests/estimation_ui_test.py. Read report_models.py,
reporting.py, report_session.py, markdown_report.py and termdash/table.py.
**Interfaces:** Shared `CompressionReport`/`ReportContext` remain presentation sources;
new `EstimationProgress` added in Task 7 must use the same renderers.

- [x] Establish fixture-backed existing comparison/inventory/progress baselines with
  deterministic colours/time. Record 80/120/160-column layouts and long/CJK labels.
  Existing accepted rendering must pass before changes; specify new required estimation
  fixtures here, but add their failing behavior assertions during Task 7's RED cycle
  so no earlier checkpoint leaves the suite knowingly failing.
- [x] Assert no raw ANSI in redirected/Markdown output, complete wrapped numbers/paths,
  correct binary units, independent overall/gallery counters and clean close/cancel.
- [x] Record manual Windows resize/colour review as pending, not passed. No product UI
  edits justified merely by making a screenshot test easier.

## Subproject B: shared command replacement

### Task 3: Canonical operations and complete argument audit

**Files:** Create compresser/arguments.py and tests/arguments_test.py; modify shared
argument owners sampling.py/preview.py, cli.py, report_session.py; MangaDL cli_core.py,
cli_structure.py, compress.py and CLI/structure/compression tests; both READMEs/help registry.
**Interfaces:** `build_operation_parsers(parent, *, owner: str) -> None` and
`normalize_compression_arguments(namespace) -> CompressionOptions` (frozen value object
defined in arguments.py). Options carry operation, target, exact filters, recipe specs,
population policy, budget, plan ID, resource paths and explicit safety decisions.
Both adapters consume these values; no implicit Namespace defaults inside workers.

- [ ] RED: table-test every cli.md operation/option, integer/fraction qualities,
  duplicate recipe elimination, invalid finite numbers/durations/percentages, required
  target and format/mode compatibility. Standalone/MangaDL normalize equally except
  target spelling and MangaDL filters. Top/leaf help lists only relevant options.
- [ ] RED: removed `-l/-c/-b/-P/-Q/-R/--inventory-file/--output-dir` forms fail with
  operation guidance and no files; no legacy parser. `apply` without -w fails;
  lossy/perceptual apply without -L fails; recovery writes require fresh exact -C token
  plus -w. All invalid options fail before configure_workspace/report decorators.
- [ ] Implement all operation builders/normalization from cli.md. Route existing
  inventory/analyze/compare/preview/apply/recover engines without changing safety.
  Plan/estimate may report explicit not-yet-delivered errors until Tasks 4/7, with no
  output artifacts. Remove superseded argument-owner parsing rather than duplicate it.
- [ ] Update normalized report context, operation labels and retained existing report
  semantics; no estimate masquerading as full benchmark. Remove dead placeholder flags.
- [ ] GREEN: parser, installed entrypoint help (after authorized execution setup),
  adapter/ownership/recovery tests and full affected suites. Select next available major
  versions (baseline suggests compresser2/MangaDL3; recheck at execution), synchronize
  exposed versions/dependency minima/help registry and reinstall wrappers per repo rules.
- [ ] Record replacement examples and pending plan/estimate capability; no commit/push assumed.

## Subproject C: separate inventory and estimation plans

### Task 4: Descriptive profile and persistent sampling plans

**Files:** Modify distribution.py, inventory.py, file_inventory.py, snapshots.py;
create estimation_models.py, sampling_plan.py, plan_store.py; tests/estimation_plan_test.py,
profile tests and plan CLI integration tests.
**Interfaces:** `RecipeSpec`, `EstimationBudget`, `EstimationPlan` frozen contracts in
estimation_models.py. `build_plan(population, recipes, budget, *, seed: int) -> EstimationPlan`;
`save_plan(workspace, plan) -> Path`; `load_plan(workspace, plan_id: str) -> EstimationPlan`.
`load_population(workspace, *, owner: str, filters: tuple) -> PopulationView` in
sampling_plan.py supports file/header depth and exposes group counts/bytes/membership.
Plan state separates immutable design inputs from atomic measured-stage updates.

- [ ] RED: profile revision2 has no starter_samples/mandatory gallery quotas; new plan
  from identical population/seed is deterministic, depends on requested scope/recipes,
  and never changes inventory. Size bands/merge rule match design; many galleries do
  not inflate pilot count. Stable prefixes survive cap expansion on unchanged population.
- [ ] RED: plan-only opens no codec/trial DB/images; missing inventory, invalid depth,
  changed fingerprints/filter/seed/recipe/runtime identity and linked plan path fail
  explicitly. Atomic replace interruption leaves the last parseable plan; concurrent
  same-plan updates serialize; plan IDs reject path traversal.
- [ ] Implement plan JSON schema/version/identity and descriptive profiles. Default
  cap512 images/2000 new encodes/300s and pilot64 are resource policies, not optimal
  sample counts. Plan stores selected prefixes and separate per-recipe stage quotas.
- [ ] GREEN: run inventory/profile/plan/adapter tests; plan-only report uses shared
  report/Markdown layout and names all planned budgets, gaps and snapshot age.

### Task 5: Fixed design estimator and independent numerical validation

**Files:** Create estimation_stats.py, tests/estimation_stats_test.py;
reuse/refactor confirmation.py/sampling.py only for shared primitives without changing
old interval semantics silently; add tests/estimation_population_test.py.
**Interfaces:** `allocate_confirmation(plan, pilot_results) -> ConfirmationDesign`;
`estimate_fixed(plan, design, pilot_results, confirmation_results) -> tuple[RecipeEstimate, ...]`.
Define ConfirmationDesign and RecipeEstimate in estimation_models.py. Quotas, selection,
population remainder and estimator revision are immutable before confirmation observations.

- [x] RED: tiny enumerated finite populations recover known stratified expectations;
  full census has exact total/zero sampling variance; unsampled/singleton/failed groups
  have explicit uncertainty gaps; skewed bytes and signed growth are not clipped.
  Distinct input sizes demonstrate ratio-of-sums is not mean percentage savings.
- [x] Implement known pilot totals + residual population sample totals with finite
  correction. Allocate using group size, observed variation and cost with floors/caps;
  missing variation gets a labelled conservative planning proxy, not fake precision.
- [x] Add frozen group linear predictor and confirmation residual correction in a
  separate RED/GREEN step: constant fallback, exact predictions yield zero residual
  variance, deliberately wrong predictions still yield correct expectation across all
  confirmation samples. Store model coefficients and revision in the plan.
- [x] RED/GREEN: unreadable selected files never replaced/dropped; missing results,
  duplicate identities, stale source and partial outcome-selected confirmation batches
  cannot produce complete statistical intervals. Ordinary fixed normal intervals are
  explicitly approximate, with no repeated-stopping guarantee.
- [x] Run focused tests and repeated seeded known-population simulations; record bias,
  interval coverage and errors by recipe, not merely unit pass counts.

## Subproject D: bounded measurement and useful estimation UI

### Task 6: Count actual encodes and execute image-recipe jobs

**Files:** New trial_budget.py, measurement.py, tests/trial_budget_test.py,
tests/measurement_test.py; modify engine.py, relevant codecs/perceptual loops,
cache.py and scheduler integration. Inspect actual codec entrypoints before changing.
**Interfaces:** `TrialBudget.admit(recipe_id: str) -> TrialPermit` reserves atomically;
permit records an attempt at codec entry and releases unused reservations.
`measure_jobs(jobs: Sequence[MeasurementJob], *, engine, budget, callbacks)
-> MeasurementBatch`; MeasurementJob carries source identity and explicit recipes.
No write_mode on this public estimator interface. Reuse current resource scheduler.

- [ ] RED: concurrent workers cannot exceed a cap of 3 actual encodes; injected AUTO
  candidates, perceptual search, retries and failed encodes each consume attempts;
  cache hits consume zero; cancelling unused reservations releases them.
- [ ] RED: monotonic deadline prevents new admission; running native call drains;
  peak resource reservation remains bounded; failed cleanup remains visible. Same
  image recipes may share a decode but validation/alpha/metadata/lossless verification
  stay active. No estimate publishes transformed bytes to source/previews.
- [ ] Implement first with bounded subsets through existing engine, then the shared
  source job runner. Trial results persist immediately through existing cache. Keep
  measurement metrics identity explicit: size-only results must never satisfy required
  perceptual scores; existing scores may satisfy weaker size-only requests.
- [ ] GREEN: real generated JPEG/PNG/WebP fixtures produce identical bytes/policy
  outcomes to equivalent existing recipe calls; bounded doubles prove caps/cancel.
  Record measured timing before claiming decode reuse improves performance.

### Task 7: Estimation controller, resumption and clean shared output

**Files:** New estimation.py, tests/estimation_test.py; modify both adapters, reporting
modules and estimation_ui_test.py. Add plan store/controller failure-injection tests.
**Interfaces:** `run_estimation(plan, *, engine, invocation_budget, on_progress)
-> EstimationResult`; `EstimationProgress` immutable sequenced event in estimation_models.py.
Single coordinator owns plan/report state. Cache values satisfy preselected jobs, never
determine who is selected for confirmation.

- [ ] RED: pilot -> frozen confirmation executes only requested pairs; recipe quotas
  differ without forcing a full matrix. Caps/image exhaustion, missing group coverage,
  cache-only runs and incomplete confirmation have correct stopping reasons.
- [ ] RED: resume at same population/settings continues exact stored selection and
  coefficients; new invocation allowances are additional and cumulative history is
  intact. Changed settings/runtime/filter/population reject with rebuild guidance.
  Abrupt stop after trial cache commit can recover the result without a new encode.
- [ ] Implement fixed-design controller and shared plan/estimate entrypoints. Serialize
  same-plan writers; independent plans obey per-run budgets, no global reservation claim.
  Store last complete statistical result separately from provisional observations.
  Until Task8 delivers repeated-stopping support, explicit accuracy targets reject
  before work with a capability message; do not silently use approximate intervals to
  implement that promised control. Default fixed-mode estimates remain usable.
- [ ] Extend existing panels/Markdown with phase/recipe, exact trial/cache counts,
  remaining budgets, snapshot age, intervals/gaps and stopping reason. Stable latest
  estimate remains visible during pending batches. Never print a growing line per trial.
- [ ] GREEN: 80/120/160-column CJK/long-path/control-character, TTY/non-TTY, cancellation,
  unknown uncertainty and JSON tests preserve Task2 baselines. Run affected full suites.
- [ ] Manual gate: user reviews real Windows resize/colour/live progress and saved
  Markdown. Fix formatting regressions before proceeding; report if acceptance pending.

## Subproject E: advanced estimation, separately reviewable

### Task 8: Certified repeated stopping for bounded retained-original estimates

**Files:** New sequential_estimation.py, tests/sequential_estimation_test.py;
extend controller/plan/report facts and CLI accuracy validation.
**Interfaces:** `next_round(plan, history) -> ConfirmationDesign` freezes remaining
population, quotas/predictor; `bounded_interval(plan, design, results) -> RecipeInterval`.
RecipeInterval stores family alpha, recipe/round index, bound method and assumptions.

- [ ] RED: implement independent arithmetic oracle for design.md delta/range/formula;
  full remainder census exact; n=0/missing/failed batch has no certified interval;
  signed allow-larger plus accuracy target rejects before work. Later recipe registration
  must not reset/spend an already consumed alpha budget.
- [ ] Implement conservative no-replacement Hoeffding plus declared alpha spending,
  using known per-file savings bounds. Completed rounds condition on all prior measured
  values; no pooling with fixed normal intervals. Preserve already valid intervals when
  a later batch is interrupted. Stop at target or caps, whichever occurs first.
- [ ] Validate against exact small-population enumeration and seeded repeated-stop
  simulations with heterogeneous recipes, adverse outliers and adaptive allocation.
  Record simultaneous coverage, not only marginal per-row coverage; statistical claims
  require independent formula/design review and no observed assumption violations.
- [ ] GREEN: fixed estimator remains available/labelled approximate; certified mode
  reports wide intervals honestly. No claim this bound reaches accuracy cheaply.

### Task 9: Optional quality exploration without fabricated confidence

**Files:** New quality_curves.py, tests/quality_curves_test.py; operation builders,
controller and report facts. Add `-g/--quality-range LOW HIGH` only for plan/estimate,
mutually exclusive with explicit quality list; lossy only.
**Interfaces:** `choose_quality_anchors(recipe_family, observations) -> tuple[int,...]`;
`interpolate_quality(observations, quality: int) -> InterpolatedEstimate`.
Initial anchors LOW, integer midpoint and HIGH; deduplicate. Add anchors where held-out
errors exceed 1 percentage point of source bytes, subject to the same encode caps.

- [ ] RED: nonlinear curves trigger added measurements; endpoints are measured;
  out-of-range prediction rejects; lossless remains separate; apparent nonmonotonic
  observations are not silently overwritten by a forced curve.
- [ ] Implement bounded per-codec interpolation and holdout checks. Never attach exact
  statistical intervals to interpolated rows. Confirming an exact quality makes a new
  registered recipe/plan rather than reusing a cherry-picked holdout as confirmation.
- [ ] GREEN: output distinguishes measured/interpolated/unresolved at all widths and
  in Markdown/JSON. Exact-list estimation never invokes this path implicitly.

### Task 10: Evidence, docs and final acceptance

**Files:** Add tests/estimation_benchmark_test.py or module-local benchmark script;
both READMEs, help registry, package versions/dependency floors, this plan's status and
checklist, relevant module handoffs. No unrelated docs overhaul.

- [ ] Generate a modest multi-folder mixed JPEG/PNG/WebP corpus locally; exhaustively
  encode selected exact recipes as ground truth. Compare many seeded plan runs against
  totals; record new encodes, errors, coverage and runtime/cost. Include equal-sized
  images with different detail and large/skewed files. Never use B:\Hent implicitly.
- [ ] Compare legacy algorithm workload mathematically/on fixtures (not old CLI compatibility)
  with new recipe-pair schedule; no universal speed/accuracy percentage acceptance claim.
- [ ] Run common full affected suites, static checks, installed help/version checks and
  final diff/status. Real-image tests retain existing codec availability skips explicitly.
- [ ] Finish argument decision ledger/help examples, schema/stop/resume documentation,
  snapshot limitations and quality-vs-size explanation. Check no old aliases are advertised.
- [ ] Preserve delivered UI baselines; complete Windows manual gate or state precisely
  that it remains pending. Reader-quality review remains required before lossy application.
- [ ] Request independent whole-change review under the selected execution method;
  fix evidence-backed issues, update handoffs. Commit/push/merge only if directly authorized.

## Planning self-review and execution handoff

Design coverage: workspace Task1; CLI Task3; inventory/plan Task4; fixed statistics Task5;
real encode limits Task6; resumption/UI Task7; sequential accuracy Task8; range estimates
Task9; empirical validation/docs Task10. Review Focus cases map to explicit RED checks.
No code implementation or tests executed by creating this plan. Draft decisions/defaults
are concrete for review, not claims of optimality. Written review and execution-method
selection remain pending; recommend native execution because shared interfaces and staged
statistical gates benefit from one implementer, with independent review at completion.
