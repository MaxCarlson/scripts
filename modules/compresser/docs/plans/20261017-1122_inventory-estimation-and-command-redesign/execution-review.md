# Execution review and model handoff

2026-10-17. This is an execution supplement to design.md, cli.md and plan.md.
The decisions below resolve ambiguities in those documents. Implementation is paused
at the user's request for this review; the original implementation objective remains.

## Model assignment and required stops

The stronger implementation/review tier below means Sol Medium (or a stronger model
selected by the user). Do not interpret Luna High as satisfying these stop gates.

| Work | Suggested model | Required boundary |
| --- | --- | --- |
| Task 1 workspace/ownership | Luna High | Finish the open ownership and Python compatibility checks below. Escalate if existing downloader ownership would change. |
| Task 2 preserved fixtures; docs/help edits | Luna Medium | Preserve the existing renderer; no visual acceptance claims from snapshots. |
| Task 3 shared CLI/adapters | Luna High | Use one normalized contract; escalate any proposed weakening of apply/recovery safeguards. |
| Task 4 population/plan persistence | Luna High | Escalate population identity, lock granularity or sampling changes beyond the rules below. |
| Task 5 statistical implementation | Stronger model | Stop before starting Task 5. This review specifies the arithmetic, but is not independent review of its future implementation. |
| Task 6 encode accounting/scheduler | Luna High | Follow every raw codec entry; stop if the hard cap cannot be demonstrated under concurrency and nested searches. |
| Task 7 controller/resume/UI | Luna High | Stronger review of crash/resume and incomplete-batch handling before statistical results are accepted; retain the Windows user gate. |
| Task 8 certified sequential stopping | Stronger model | Stop before starting Task 8; independent mathematical and implementation review required before any certification claim. |
| Task 9 exploratory quality curves | Luna High | No confidence claims; escalate changes to sample selection or recipe registration. |
| Task 10 benchmark/docs | Luna High for measurements; Medium for prose | Stronger whole-change review before declaring the complete design delivered. |

High is the recommended default for continuation. Medium is appropriate for bounded
fixture/doc tasks, not ownership, scheduling or statistics. Passing tests cannot prove
model equivalence; these boundaries are intended to expose mistakes before delivery.
When a stop is reached, update STATUS/handoff, state the precise reason a stronger
model is needed, and yield. Do not spawn a stronger agent to bypass the user's switch
preference, and do not silently reduce scope or statistical promises.

## 1. Population, grouping and random design — Tasks 3–5

- A usable population requires a completed matching snapshot, unique canonical source
  identities, fingerprints and known nonnegative byte sizes. Refuse inference when
  membership/bytes are incomplete; print an inventory-refresh hint. A file-depth
  snapshot may contain unreadable headers: retain those selected identities and their
  weights; failures are unresolved, not replacement draws.
- Freeze groups from metadata alone. Format is extension at file depth, actual format
  at header depth; keep known ineligible classes separate. Within each format/class,
  use exponent `floor(log2(max(1, bytes)))`, split its observed exponent span into at
  most four equal-width integer-exponent intervals, and omit empty intervals. Repeatedly
  merge the lowest-size group with fewer than eight members with its next neighbor;
  merge a deficient final group into its previous neighbor. Stop at one group or when
  all groups have at least eight members. Persist this grouping revision.
- Order each group's identities by SHA-256 over canonical JSON of
  `[ordering_revision, seed, group_id, relative_source_identity]`, with source identity
  as a deterministic tie-breaker. Hash ordering is the reproducible pseudorandom
  sampling convention, not a cryptographic proof of statistical randomization.
- Fixed mode has one metadata-selected shared pilot (at most 64 distinct sources and
  within the initial image allowance). Assign one per group in stable group order,
  then a second where possible, then round-robin to capacity. All requested recipes
  may measure this pilot; do not require galleries. Uncovered groups remain explicit.
- Freeze confirmation quotas and identities once, after the prescribed pilot finishes.
  A conservative unique-image bound is shared pilot size plus the SUM of confirmation
  quotas across recipes. Partition that remaining design allowance among recipes in
  stable order, round-robin, and allocate within each recipe using the rule below.
  This avoids assuming cheap image overlap or accidentally promising a full matrix.
- Each recipe's confirmation is a prefix of each group's remaining order, excluding
  the shared pilot. Future confirmation outcomes, cache availability and completion
  speed must not influence its quotas, members, predictor or early stopping. Never
  prune a random draw because it overlaps poorly with another recipe's draw.
- A larger NEW plan with the same seed/population preserves rank prefixes, but need
  not preserve pilot/confirmation roles or coefficients. Resume completes the SAME
  frozen fixed design. Larger invocation allowances do not top up a completed fixed
  sample or reinterpret its interval. Refinement needs a new plan, or Task 8 rounds.

## 2. Fixed estimator arithmetic — Task 5, stronger-model checkpoint

For each recipe/group, let P be the prescribed observed pilot; U its remaining
population of size N; C the frozen simple random confirmation sample of size n.
Use signed `y = input_bytes - retained_bytes`. With predictor `m_i = a + b*x_i`
frozen from P, the group contribution and estimated variance are:

```text
T_hat = sum(y over P) + a*N + b*sum(x over U) + N*mean(y-m over C)
V_hat = N**2 * (1 - n/N) * sample_variance(y-m over C) / n
```

The unpredicted first implementation uses a=b=0. Sum group totals and variances;
report `T_hat +/- 1.959963984540054 * sqrt(sum(V_hat))` as a marginal approximate
fixed-design interval. These approximate intervals have no family or repeated-look
guarantee. Report ratios using total saved bytes / total inventoried bytes, never
the mean of per-image percentages. Zero total input bytes has undefined percentage.

Use ordinary least squares on pilot (x,y) only when at least three valid pilot
observations have distinct x; otherwise b=0 and a=mean(pilot y), or a=0 if absent.
Use centered arithmetic to avoid cancellation; reject nonfinite coefficients.
Prediction is not clipped to observed savings. A wrong predictor does not remove
the confirmation residual correction. Pilot observations are known once, not also
expanded by a population weight.

Planning allocation uses weight `N * s / sqrt(c)`, with `s=max(observed pilot
savings standard deviation, 0.05*mean input bytes, 1 byte)` and `c=max(mean measured
pilot seconds, .001 seconds)`. Missing measurements use metadata variation/cost proxies
labelled as planning assumptions only. First allocate coverage floors of two (or
census if N=1) where the allowance permits, in stable group order; then distribute
remaining quota proportionally by largest remainder, reapplying capacity limits.
Insufficient floor coverage is a reported gap, not permission to increase the cap.

If N=0, use the known pilot total exactly. If n=N and all observations succeeded,
use a census total with zero variance. If n=0<N, contribution is unresolved. If
n=1<N, a descriptive point may be shown but variance/interval is unknown. Missing,
failed, duplicate or mismatched prescribed observations invalidate that recipe's
complete interval. Never recompute n from the fastest successful subset.

Required independent oracles: enumerate every size-n confirmation subset of tiny
unequal-size populations conditional on each pilot; expectation must equal truth
even with deliberately wrong frozen predictors. Check the finite correction and
signed growth separately. Simulation coverage of normal intervals is descriptive,
not an acceptance threshold or proof of nominal coverage on all populations.

## 3. Raw encode entry and result states — Tasks 6–7

Current evidence: engine._encode_verified calls codec.encode once, while
perceptual.find_optimal_quality invokes its encode callback for every quality.
Charging once at the engine wrapper would undercount those native encodes.

- Acquire/consume permits at every actual candidate Image.save/external encoder launch,
  including perceptual callbacks, AUTO children, retries and failing native attempts.
  Validation/decode opens do not consume an encode. No process-global mutable budget;
  thread jobs carry the invocation budget explicitly or through propagated context.
- Atomically maintain `attempted + reserved <= max_trials`. A reservation is consumed
  immediately before native entry, with a deadline/cancellation recheck; release it
  if entry never happens. Entered attempts stay charged after failure/cancellation.
- Budget denial is a distinct control outcome, not a normal encoder failure or a
  successful retained-original result. An interrupted perceptual search cannot cache
  a complete recipe measurement from its best candidate so far.
- Persist only fully validated recipe outcomes as reusable measurements. Use explicit
  states: measured, retained_by_policy, failed, not_started, interrupted. Only complete
  measured/policy outcomes with matching fingerprints/runtime/metric requirements
  satisfy statistical observations. Unknown failures remain unresolved in the first
  estimator; do not silently assign y=0 to make a bound available.
- Image allowance counts distinct sources admitted in THIS invocation, including
  cache-only jobs; trial allowance counts new native attempts. Cumulative sources,
  attempts and cache hits are separate persisted history fields. Known observations
  loaded solely to compute a previous result are not newly admitted source jobs.
- Fresh process budgets start at controller entry; they do not resurrect old permits.
  Native work drains after admission stops. Keep current memory/source safeguards.

## 4. Resume and persistence — Tasks 4 and 7

- Separate immutable plan identity (population/scanner/grouping, owner/filters, recipe
  policy/runtime/metric identities, seed/order revision and initial design policy)
  from mutable journal generation, completed observations and invocation allowances.
  Preserve the immutable initial budget as provenance, not a cumulative run limit.
- Parser omission is distinct from an explicit default: with `-r ID`, load stored
  settings, then compare only explicitly supplied recipe/scope/seed options. Never
  invent a new default WebP recipe and compare it to an omitted resume option.
- One OS-backed per-plan lock covers read/validate/update/execute. Independent plan
  IDs may proceed; do not hold a workspace-wide publication lock for a whole run.
  Atomic JSON replace alone does not serialize writers. Validate plan IDs before
  path resolution; reject links/hardlinks at plan, lock and publication boundaries.
- Durable order: freeze design in plan BEFORE measurement; commit validated trial to
  existing cache BEFORE journaling its observation. After a crash between those two,
  a selected job can recover a compatible cache value. A cache search cannot select
  a new statistical member. Cache off has no crash-recovery guarantee for unjournaled work.
- Persist last complete result separately from incomplete current-stage observations.
  Recheck selected fingerprints before cache use and at stage transitions. Do not hash
  live files to recreate a saved population during plan-only execution.

## 5. Sequential bounds — Task 8, stronger-model checkpoint

The intended conservative fixed-round bound follows the without-replacement Hoeffding
inequality in Bardenet/Maillard, Proposition 1.2:
https://arxiv.org/pdf/1309.4029 . Two tails give
`N*W*sqrt(log(2/delta)/(2*n))`. Alpha spending plus a union bound is the proposed
sequential construction here; do not claim implementation of the tighter confidence
sequences in https://arxiv.org/abs/2006.04347 .

- Condition on ALL prior history. Freeze the known observations, remaining membership,
  predictor, quotas and residual bounds before a fresh uniform draw. Do not reuse a
  revealed rank order to choose a new round after observing correlated outcomes.
  Use domain-separated per-recipe/per-round randomization; sample from the actual
  remaining population. The stronger implementation review must check this filtration.
- The count N is the population remaining BEFORE the current draw, and the point
  center is known totals + prediction total over that population + N*mean residual.
  Use bounds over that WHOLE remaining population, never just observed residuals:
  L=min(-m_i), U=max(x_i-m_i), W=U-L under `0<=y_i<=x_i`. Group metadata or exact
  affine extrema must justify those bounds. Census is exact; failed/partial draws
  are not completed rounds. Record alpha allocation before measurements.
- Stable one-based recipe k and committed round r spend
  `delta=.05*2**(-k)*2**(-r)/H`; resume/interruption never resets the indices.
  Summing over groups, recipes and rounds spends at most .05. Recipes remain fixed
  for one plan. All completed intervals target the SAME original population total.
- Intersect valid intervals with each other and the physical [0,total_input_bytes]
  bound; empty intersection is an explicit diagnostic, not zero uncertainty. Accuracy
  is reached only when the full interval width is at most
  `2*(accuracy_pp/100)*total_input_bytes` for EVERY requested exact recipe. Do not
  claim the displayed point is the midpoint if it is not; show interval bounds.
- Before drawing, enforce the conservative sum-of-quotas bound against remaining
  distinct-image allowance; do not choose draws based on overlap. Incomplete rounds
  resume the same members and r. A valid earlier interval remains valid while pending.
- Refuse signed allow-larger certification, nonpositive percentage denominators,
  unresolved observations, and unsupported recipe randomness. Require arithmetic
  enumeration, adversarial sequential simulation and independent review; observed
  simulation coverage is not a mathematical proof.

## 6. CLI and quality exploration clarifications — Tasks 3 and 9

- Preserve all explicit-option provenance. Reject explicit q with lossless/perceptual;
  reject explicit perceptual target outside perceptual mode. Compare both uses q for
  its lossy recipes only. Preview's fixed lossless baseline is not an ignored -m.
- Validate capability combinations: PNG lossless only; AVIF explicit lossy only;
  JPEG lossless requires jpegtran and original JPEG candidates (other source classes
  remain labelled ineligible); WebP supports existing modes. A requested incompatible
  combination fails as a whole, including PNG/AVIF with compare both. Do not silently
  drop formats or relabel modes. Explicit auto means one image-level policy, not an
  implicit library comparison matrix. Effort identity includes only effective settings;
  reject an explicit effort where the chosen encoder cannot use it.
- Default analyze/apply to one WebP lossless recipe, consistently with plan/estimate.
  Recovery does not use a compression workspace: reject -I rather than accepting an
  ignored flag. It retains target/JSON/no-ui/verbose and the write/token pair.
- Task 9 uses piecewise linear quality interpolation per codec/family, without forced
  monotonicity. Begin at LOW, integer midpoint, HIGH. Test integer midpoints of each
  adjacent anchor interval on the SAME frozen exploratory sample. Promote a held-out
  quality when absolute aggregate retained-byte interpolation error exceeds .01 times
  that sample's total input bytes; then test new interval midpoints in increasing order.
  No repeat of already tested qualities. Measured rows stay measured even when an
  anchor was not needed. Missing endpoints or incomplete validation are unresolved,
  never fabricated predictions. All this work obeys the same caps.
- Those holdout checks are exploratory sample diagnostics, not proof of a library-wide
  one-percentage-point error limit. Interpolated rows carry no statistical intervals;
  exact confirmation of a chosen quality uses a new registered recipe/plan.

## Current state and next action

Local main fast-forwarded to 8cdc7fe as authorized. Isolated implementation branch:
`compression-inventory-estimation-20261017`, worktree at
`C:/Users/mcarls/src/scripts/.worktrees/compression-inventory-estimation-20261017`.
The user authorized the first-stage commit and push. No installs or production
operations occurred.

Tasks 1 and 2 are complete. Stronger-model ownership follow-up is implemented:
artifact-only .mangadl
does not establish parent library ownership; reparse points, malformed/aliased manifests,
unknown controls and changes during inspection retain conservative ownership. Uses the
existing linked(lstat()) primitive, compatible with declared Python>=3.10 APIs (actual
tests run on Python3.12). READMEs describe the new layout/no-migration boundary and
use parent-directory -I examples. Version/help synchronization belongs to Task 3's
breaking CLI release checkpoint.

Independent statistical prework is implemented in tests/estimation_reference.py and
estimation_reference_test.py: exact Fraction expectation/variance enumeration and a
60-digit Decimal oracle for the raw two-tailed bound. Five oracle tests pass. These
are test-only references, not a delivered estimator or proof of future controller
sampling validity. Task5 production work still depends on Task4's population/design
contracts; Task8 additionally depends on the completed controller and Windows gate.

Task 2 has comparison, inventory and deterministic progress fixtures at 80/120/160
columns, plus layout/CJK/control tests. Latest UI fixture suite:12 passed. Existing
progress tests cover independent counters, unknown totals/errors and clean close.
No renderer changed. Windows manual review remains pending.

Evidence: initial compresser326 passed/1 skipped; workspace changes compresser
330 passed/1 skipped before latest ownership tests; focused workspace/read-ownership
18 passed; MangaDL library_guard 5 passed after ownership fix; TermDash 76 passed/1 skip;
help 55 passed after creating its missing module-local temp parent. Earlier full MangaDL
316 passed/1 failed exposed the ownership collision. Latest combined focused ownership
and oracle checks: 29 passed; Ruff/Black clean for the stronger-pass Python files.
Stage final suites: compresser356 passed/1 skipped and MangaDL317 passed. Ruff and
`git diff --check` pass. Black formatting was applied; the final `black --check` worker
stalled on Windows and was stopped. Earlier stronger pass had Black120 passing before
the progress-fixture test was added. See STATUS.md for exact stage commands/results.

Use repo Python with worktree source paths, not its original editable-install sources:

```powershell
$env:PYTHONPATH = "$PWD/modules/compresser;$PWD/modules/mangadl;$PWD/modules;$PWD/modules/scripts_help"
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/compresser/tests -q -p no:cacheprovider --basetemp=modules/compresser/.pytest_tmp_root/next-check --tb=short
```

Run suites separately (duplicate test basenames collide). Create basetemp parents when
absent. Sandbox runs hit WinError 5; approved require_escalated test runs work. Preserve
the ledger in .superpowers/sdd/plan/progress.md and all uncommitted planning edits.
