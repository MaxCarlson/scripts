# Status

2026-10-17 Task 7 follow-up: EXIF container normalization and terminal observation state fix.
Resolved false-positive metadata rejection where JPEG EXIF container prefix (`b'Exif\x00\x00'`) differed from raw TIFF WebP/AVIF headers, causing WebP and AVIF to report `ValueError: Encoder did not preserve exif metadata` on images like `205.jpg`.
Fixed `run_estimation` completion checks: replaced `not obs.complete` with terminal observation verification (`obs.state in ('measured', 'retained_by_policy', 'failed')`), preventing failed trials (such as lossless JPEG under Pillow) from halting the estimation controller at `pilot_incomplete` in an infinite re-queue loop. Prescribed pilot and confirmation stages now cleanly advance to statistical estimation once all trials reach terminal states. All 537 tests passed.

2026-10-17 Task 7 follow-up: Live terminal UI upgrade & progress callback pipeline.
Fixed progress freeze where batch trial evaluations emitted no intermediate callbacks, leaving the UI static at `Sources: 0/N`. Added per-job and per-observation callbacks to `measure_jobs`, with `StageTracker` accumulating real-time recipe stats, rolling throughput, and `Last completed` trial details.
Upgraded `EstimationProgressUI` to match the `inventory` and `CompresserDashboard` visual standards: dual progress bars (`Stage:` and `Overall:` budget), rolling rate / ETA, live stats line, and a boxed table (`MEASURED RECIPES & PROJECTED SAVINGS (LIVE)`) displaying evaluated recipes, trial counts, sampled bytes, retained bytes, savings %, and projected whole-library savings (`Est. Lib`) bounded within 80/120/160 columns. All 537 tests passed.

2026-10-17 Task 7 checkpoint: Fixed-design estimation controller, plan resume, adapters, and reports/UI
implemented and validated on `compression-inventory-estimation-20261017`.
Added `run_estimation` and `execute_estimate_operation` in `modules/compresser/compresser/estimation.py`.
Added `plan_execution_lock` non-blocking byte-0 file lock per plan in `plan_store.py` to serialize
concurrent workers on the same plan. Resumption maintains stored selections and coefficients without
re-encoding existing observations; observations and provisional states are persisted atomically per batch.
Explicit accuracy requests (`--accuracy-pp`) reject cleanly before work pending Task 8 certification.
`EstimationProgressUI` renders bounded multi-line `LiveBlock` progress without line-per-trial terminal growth,
and `ReportSession.estimate` publishes structured Markdown reports and console summaries.
CLI operations wired in `compresser/cli.py` and `mangadl/compress.py`.

Validation: 86 focused tests passed (including estimation_test.py, estimation_ui_test.py, cli_test.py,
trial_budget_test.py, measurement_test.py, mangadl/tests/compress_test.py).
Full compresser suite: 499 passed, 1 skipped. MangaDL suite: exit 0. scripts-help: 55 passed.
Ruff lint and Black 120 format passed. Help entrypoints verified (`mangadl compress estimate -h`,
`compresser estimate -h`). Manual Windows visual gate recorded pending user review.

2026-10-17 Task 6 checkpoint: Actual encode accounting and image-recipe measurement
implemented and validated on `compression-inventory-estimation-20261017`.
Added `TrialBudget`, `TrialPermit`, `trial_entry` across Pillow WebP, JPEG, PNG, AVIF,
external CLI, and engine AUTO/candidacy paths. Cache hits consume zero encodes; unused
reservations release cleanly; deadlines prevent new admissions while active native calls drain.
`measure_jobs` shares source decodes across recipes per image, preserves size guards, alpha/metadata
handling, and lossless pixel verification. MemoryScheduler and bounded ThreadPoolExecutor
obey concurrency and memory limits.

Validation: 17 focused Task 6 tests passed (10 in trial_budget_test.py, 7 in measurement_test.py).
Full compresser suite: 499 passed, 1 skipped. MangaDL suite: exit 0. scripts-help: 55 passed.
Ruff lint passed; format checked.

2026-10-17 follow-up bug: user reported plan could not find the completed inventory
in the exact `.mangadl/<target>/` workspace. Inspection confirmed a complete header
snapshot for B:\Hent\hent1imageperpage with 66,233 images. Root cause: `load_population`
passed `owner="mangadl"` to SelectionSnapshot while MangaDL publishes under
`owner="mangadl-pages"`, producing different policy keys. The normal header-path
integration regression reproduced the failure and passed after mapping the owner.
The normal header-path integration regression reproduced the failure (RED), then
passed with the owner mapping fix (GREEN). Validation: compresser435/1 skip; MangaDL
full suite exit0; scripts-help55. Ruff and Black120 passed. Direct loader now reads
66,233 header members from the user's workspace. Retried the exact plan successfully;
saved `plan-60b15df8fb2aa29c2c22` in the user's `.mangadl` workspace with12 recipes,
caps200/750/900s and zero measurements. Compresser/MangaDL source and installed
metadata3.1.1. This creates only the requested plan and report; no source image encoded
or changed. Checkpoint push verified; pause before Task6.

2026-10-17 user-requested bounded follow-up (3.1.0): plan/estimate now accept
`-m both`; plan/estimate/compare accept `-f all`. This registers supported
AUTO/WebP/JPEG/AVIF/PNG recipes once, with PNG lossless only and AVIF lossy only,
under one immutable plan and shared budget. `keep` remains explicit. Saved-plan
schema and numerical estimators are unchanged; estimate execution is still pending.
See amended cli.md/execution-review.md for the updated capability contract.

RED: nine new argument cases and the MangaDL inventory/plan/resume test rejected
the missing options. GREEN: compresser435 passed/1 skipped; full MangaDL suite
exit0; scripts-help55 passed. Commands (repository virtualenv, module cwd):
`python -m pytest -p no:cacheprovider --basetemp .pytest_tmp_root/combined-full tests -q --tb=short`
for each of compresser and MangaDL, with module source paths in PYTHONPATH.
Help: `python -m pytest -p no:cacheprovider --basetemp modules/scripts_help/.pytest_tmp_root/combined-full modules/scripts_help/tests -q --tb=short`.
Ruff passed changed CLI/tests; Black120 checked arguments.py and arguments_test.py.
The installed `mangadl.exe compress plan -I ./ -d ./hent1imageperpage/ -f all
-m both -q 85 70 -s 200 -T 750 -M 15m -J` succeeded against a generated inventory:
12 recipes, lossless+lossy, caps200 images/750 attempts/900 seconds.

Local editable metadata refreshed with `pip install --no-deps --no-build-isolation
-e ./modules/compresser -e ./modules/mangadl`; source/metadata3.1.0 agree.
Pip emitted existing invalid-distribution warnings but completed successfully.
Parent status excludes inaccessible pscripts. Unrelated untracked bridge work is
preserved. Commit/push authorized; pause again after publishing this follow-up,
without beginning Task6 or touching production images.

2026-10-17 Sol Medium checkpoint: Task5 implemented and validated on
`compression-inventory-estimation-20261017` in `C:\Users\mcarls\src\scripts`.
Compresser3.0.0 uses saved-plan schema2: schema1 plans require rebuilding. This breaking
version reflects corrections to incomplete frozen-population and executable-field
identity contracts discovered before statistical implementation. New exact-recipe
observations distinguish retention policies; confirmation models/quotas freeze once
and repeat plan creation preserves measured history.

The fixed estimator counts known pilot outcomes once, applies a pilot-only centered
predictor plus confirmation residual correction and finite-population variance, and
returns one RecipeEstimate per registered recipe. Missing/failed/unselected/stale or
duplicate prescribed observations cannot yield a complete interval. Intervals are
marginal approximate fixed normal intervals; they have no repeated-look guarantee.
The estimate CLI remains explicitly unavailable until Tasks6/7 supply bounded measurement
and orchestration. See task5-handoff.md for the exact next-stage contracts.

Task5 validation: full compresser424 passed/1 skipped; help55 passed; independent Fraction
oracles and deterministic 400-seed simulations completed. Ruff and Black120 passed on
the changed Python files; whitespace check passed. Simulation bias was +4.82/-33.11 bytes,
with observed approximate interval coverage92%/86.25% for the two synthetic recipes.
Those figures are descriptive, not nominal-coverage acceptance or certification.
Detailed results: task5-numerical-validation.json. The full MangaDL regression suite
also passed. No codecs or production sources were used in the numerical simulations.

User authorizes verified checkpoint commits and feature-branch pushes. Execution pauses
after publication at the user's explicit request. On resume, Task6 may use Luna High. Task7 crash/resume review and
Task8 certified sequential inference still require Sol Medium; Windows visual acceptance,
final setup/version metadata refresh and whole-change review remain pending.

Earlier execution history follows; the checkpoint above is current.

2026-10-17 execution update: Tasks 1 through 4 are implemented on branch
`compression-inventory-estimation-20261017`. The original checkout at
`C:\Users\mcarls\src\scripts` now has this branch checked out and contains the current
Tasks 3/4 changes. A detached copy remains at
`.worktrees/compression-inventory-estimation-20261017` as a safety copy. Earlier local
planning edits are preserved in the named Git stash
`preserve pre-feature planning edits before feature checkout`. The first stage was
already pushed; Tasks 3/4 are authorized for commit and push after verification. No
production operations occurred.

User requested a stronger-model design pass before switching to Luna Medium/High.
That pass is recorded in [execution-review.md](execution-review.md), including exact
sampling/arithmetic/budget/resume rules and mandatory escalation checkpoints. Recommended
continuation is Luna High; stop before Tasks5/8 and request stronger model. Task7
crash/resume review and final review also need stronger-model signoff.

Stronger-model independent work: hardened artifact-container ownership with Windows
reparse, hardlink, malformed identity and concurrent-control tests; uses the existing
Python>=3.10 link primitive. Added independent Fraction/Decimal numerical oracles for
Tasks5/8 (5 tests pass). They do not deliver the production estimator. Combined focused
ownership/reference tests29 pass.

Stage validation: full compresser356 passed/1 skipped; MangaDL317 passed; the focused
UI fixture suite12 passed. Ruff check passed for all 14 changed/new Python paths and
`git diff --check` passed. Black formatting was applied to those Python paths; a later
Black check stalled in its Windows worker process and was interrupted. Earlier stronger
pass had Black120 passing before the final test-only fixture addition. The README now
documents target-named workspaces and rejects file-valued `-I`; old SQLite-path examples
were corrected. The Windows resize/color/manual reader gate remains pending.

Task 3 replaces the public flat CLI with shared operation subcommands, frozen normalized
options, clean-break argument rejection, MangaDL adapter routing and updated help/docs.
Task 4 removes profile-driven sampling advice and adds deterministic bounded plans,
immutable recipe/population identities, atomic plan persistence, mismatch checks, and
shared text/Markdown/JSON plan reporting. Plan creation reads existing inventory only;
it does not open source images, codecs or the trial database.

Validation: compresser402 passed/1 skipped; MangaDL full suite passed; scripts-help55
passed; Ruff and `git diff --check` passed. Focused persistent-plan checks12 passed,
including atomic interruption, serialized updates, hardlink rejection, recipe/seed/budget/
runtime mismatch and changed-population refusal. Windows resize/color and reader review
remain pending.

Next: commit and push Tasks 3/4 as authorized. Then stop before Task 5 and ask the user
to switch back to Sol Medium for the fixed-design numerical estimator. Task 7 resume/crash
review, Task 8 sequential certification, the Windows visual gate and final whole-change
review remain stronger-model/manual gates.

Historical planning status follows; superseded by the update above.

2026-10-17: Planning documents created against 8cdc7fe on
compression-ui-color-and-stats-20261017. Design/CLI/implementation plan self-reviewed;
awaiting user written review and choice of native versus subagent-driven execution.
User requests a clean breaking replacement, no compatibility layer, and explicitly
requires preserving the polished real-time/report UI. No implementation or tests run.

Decisions: separate inventory from plan; new .mangadl/<target> workspace; operation CLI;
bounded exact-recipe estimator first; certified adaptive accuracy and quality curves
separate checkpoints. No automatic migration/deletion or production operations.

Supersedes unimplemented historical Plan03 P8 and repair Task6 design for this scope;
historical completed work remains evidence, not permission to execute old tasks.
Previous workspace/report delivery is complete; its manual terminal/reader checks
remain outstanding and are not cleared by this planning task.

Next: user reviews design.md, cli.md and plan.md; amend decisions, then execute only
after review/authorization. First implementation checkpoint is workspace layout plus
UI baseline, followed by shared CLI replacement. Do not start estimator code prematurely.
