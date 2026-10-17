# Task5 numerical checkpoint and Task6 integration contract

Active checkout: `C:\Users\mcarls\src\scripts`, feature branch
`compression-inventory-estimation-20261017`. User authorizes commit/push at functioning
checkpoints. Do not merge. The old detached worktree and named planning stash remain
safety copies; edit the original checkout.
User requests a pause after this functioning Task5 checkpoint. Do not start Task6 until
the user resumes work.

## Frozen design and observation contracts

- `EstimationPlan` schema2 stores the entire `members` tuple and every stratum's full
  `ordered_member_ids`, plus explicit shared `pilot_member_ids`. `selected_member_ids`
  is the initial resource-cap prefix, not the set of all future per-recipe confirmation
  jobs. Use the frozen confirmation's `selected_ids` for those jobs.
- Grouping/order revision2 follows execution-review.md exactly: equal-width exponent
  intervals, lowest deficient group merged upward, canonical JSON hash ordering.
  Plans with missing byte sizes/fingerprints are refused. Schema1 requires rebuild.
- `RecipeObservation` is a frozen typed result: member/recipe IDs, fingerprint, runtime,
  input/retained bytes, elapsed seconds and one of measured/retained_by_policy/failed/
  not_started/interrupted. Only the first two supply savings. Policy-retained means
  retained bytes equal input bytes. Failures have no retained-byte result.
- Recipe identity includes actual keep-if-larger versus allow-larger policy. Do not
  relabel a cached observation from a different retention policy.
- `allocate_confirmation(plan, pilot_results)` requires the entire prescribed pilot
  to reach terminal states; failed pilot members remain unresolved. It returns a
  `ConfirmationDesign` with per-recipe/stratum remaining membership, frozen selected
  prefixes, centered predictor, allocation weight/source and estimator revision.
- Persist it using `freeze_confirmation` BEFORE any confirmation measurement. It is
  write-once; repeated `save_plan` preserves existing confirmation and measurements.
- `estimate_fixed` returns a tuple of RecipeEstimate in registered recipe order. It
  revalidates the design against the frozen pilot and rejects mismatched observations.
  Partial selected batches cannot be interpreted as smaller successful draws.
- Predictors center both x and y around integer origins. Use `predict`/`residual`;
  do not reconstruct an uncentered intercept for numerical evaluation. A census sums
  integer savings exactly. Fixed intervals remain explicitly approximate.

## Completed evidence

RED/GREEN covered missing full-population fields, reviewed band/hash rules, detached
digest tampering, pilot64 cap, retained-policy identity, finite correction, pilot-only
prediction, large integer offsets, signed growth, missing/failed/stale/duplicate draws,
write-once persisted models and preservation of prior observations.

Fraction enumeration checked every confirmation subset conditional on each tiny pilot,
including deliberately incorrect predictors. The benchmark ran400 seeds per synthetic
recipe: mean bias+4.82/-33.11 bytes; coverage92%/86.25%. The JSON artifact records RMSE,
errors and incomplete counts. These are descriptive results, not a coverage guarantee.

Final validation used the repository virtualenv with each owning module on PYTHONPATH:
`pytest -p no:cacheprovider --basetemp .pytest_tmp_root/task5-full tests -q --tb=short`
from compresser (424 passed/1 skipped) and MangaDL (exit0). Scripts-help used the same
flags with its owning-module temp root (55 passed). Black120/single-worker, Ruff and
`git diff --check` passed. Reproduce simulations with
`PYTHONPATH=. python tests/estimation_benchmark.py` from compresser.

## Next work and stop gates

Task6 (Luna High): propagate an invocation-local raw-encode budget through AUTO,
perceptual callbacks and retries, then emit only fully validated RecipeObservations.
The statistical core opens no codecs, source files, caches or live target trees.
Task7: freeze-before-measure/cache-before-journal ordering, per-plan execution lock,
selected-source revalidation, complete-result snapshots, active-invocation allowances
versus cumulative history, and crash/resume review by Sol Medium. Do not accept a partial
perceptual search as a complete cache measurement. Task8 requires Sol mathematical and
implementation review before certification. Windows visual/reader acceptance and final
package setup remain pending. The public estimate command is not delivered yet.

Integration follow-up for Task7: resolve inventory selection explicitly when loading a
saved plan. Load the plan first and request its saved depth/filter scope, rather than
letting an unrelated file-depth inventory override an existing header plan. For new
plans, select the newest completed matching snapshot; add tests for both inventory
depths existing in either creation order. The current loader prefers file snapshots.
