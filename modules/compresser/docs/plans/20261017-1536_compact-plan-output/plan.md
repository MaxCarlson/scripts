# Compact Compression Plan Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the default verbose plan dump with the approved readable summary.

**Architecture:** Add a pure plan-summary composer/renderer beside the existing full
report composer. ReportSession saves the full report first, then selects compact,
verbose or JSON presentation; existing immutable plan data and other operations are
unaffected.

**Tech Stack:** Python>=3.10, dataclasses, existing TermDash tables/wrapping, pytest.

**Spec:** [design.md](design.md), including the user-approved mock and edge rules.

## Global Constraints

- Compresser/MangaDL3.2.0 is the planned feature version (current baseline3.1.1).
- MangaDL requires compresser>=3.2.0. No dependencies or CLI flags are added.
- No saved-plan schema, recipe identity, quota, numerical, budget-admission or estimation execution changes.
- At widths40/80/120/160, preserve values and paths through wrapping, without overflow or ellipses.
- JSON retains its existing keys and full plan; `-J` remains pure JSON stdout.
- Production Hent inventory/plans/images are not execution fixtures.
- Windows visual review at80/120/160 columns remains a manual acceptance gate.
- Work in the original scripts checkout on the existing feature branch as requested;
  preserve unrelated bridge work and the current unrelated help-registry diff.
- Verified feature checkpoints have standing commit/push authorization; no merge.
  Preserve the pause before the broader estimator Task6 after this presentation work.

## Review Focus

1. Perceptual-only and mixed-setting plans must not become misleading lossless rows (Task1).
2. Small caps, unequal quotas and coverage gaps must show actual allocations (Task1).
3. Narrow terminals, long filtered targets and redirected output must retain readable complete values (Task1/2).
4. Cache reuse/AUTO candidates must not turn a heuristic warning into a claimed encode forecast (Task1).
5. Publication failures and verbose/JSON routing must not duplicate artifacts or announce a nonexistent saved report (Task2).

## File map

| Path (repository-relative) | Responsibility |
| --- | --- |
| New `modules/compresser/compresser/plan_reporting.py` | Pure summary facts and compact terminal renderer |
| New `modules/compresser/tests/plan_reporting_test.py` | Fixture plans, summary and width/color tests |
| `modules/compresser/compresser/reporting.py` | Correct labels in the detailed plan report |
| `modules/compresser/compresser/report_session.py` | Plan-only display routing and artifact footer ownership |
| `modules/compresser/tests/operation_reports_test.py` | CLI report lifecycle and artifact failure tests |
| `modules/mangadl/tests/compress_test.py` | MangaDL normal-header inventory/plan integration |
| Both modules' pyproject.toml, exposed __version__, MangaDL root shim | Feature version/dependency synchronization |
| `modules/scripts_help/scripts_help/registry/registry.py` | Only compresser/MangaDL version entries; preserve unrelated edits |
| Both README.md, compresser docs/HANDOFF.md and docs/plans/HANDOFF.md; this STATUS/checklist | Usage, verification, remaining manual gate |

Paths below are repository-relative; commands use the repository virtualenv.

### Task 1: Compose and render the compact summary

**Files:** Create plan_reporting.py and plan_reporting_test.py listed above.

**Interfaces:**
- Consumes frozen `EstimationPlan`, `RecipeSpec`, `RecipeQuota`, `StratumPlan` from
  `compresser.estimation_models`; existing TermDash wrapping/tables/colors.
- Produces frozen `PlanSummary` with fields `title: str`, `overview: tuple[str,...]`,
  `headers: tuple[str,...]`, `rows: tuple[tuple[str,...],...]`,
  `annotations: tuple[str,...]`, `warnings: tuple[str,...]`, `plan_id: str`.
- `build_plan_summary(plan: EstimationPlan, *, population_count: int,
  now: datetime | None = None) -> PlanSummary`; default now is timezone-aware UTC.
- `render_plan_summary(summary: PlanSummary, *, report_path: str | Path | None,
  width: int, color: bool) -> str`. Footer includes the plan ID, optional report
  path, then the exact planning-only note. No filesystem access or terminal probing.

- [x] **Step1: Write failing fact tests in plan_reporting_test.py.** Build synthetic
  frozen plans with 12 literal recipes, 11 strata, shared pilot62 and matching
  per-recipe quotas62, caps200/750/900, fixed now2h6m after completion. Assert five
  rows with headers `('Format','Lossless','Lossy qualities')` and values from the
  spec's mock; count66,233 can be passed independently of fixture population size.
  Assert actual pilot62, measurement warning744, no design/population/recipe hashes.
  Parameterize warning thresholds: nominal79/100=no warning,80/100=warning.
  No AUTO recipe => no AUTO warning sentence. Larger2000 cap => no tight warning.
- [x] **Step2: Add edge tests.** Perceptual WebP0.990 adds a target column and no
  lossless claim; lossless-only and lossy-only plans omit unrequested modes correctly.
  Distinct encoder/effort variants remain identifiable in annotations rather than
  disappearing into one row. Filtered selections, accuracy goal2pp, allow-larger,
  file-depth/unverified and uncovered-group warnings remain visible. Unequal quotas
  use their true sum; pilot4 with ceiling64 must say4. Future completion => age0.
  Include rendering cases at40/80/120/160 columns, colorFalse/True, and a long
  target/filter/report path. Assert visible line widths, complete values after
  wrapping and no ANSI when disabled. At120 columns the approved12-recipe case
  is <=35 lines with one5-row table, no panels/hashes/context/quota/strata headings.
- [x] **Step3: Run RED from modules/compresser.**
  `../../.venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp .pytest_tmp_root/compact-red tests/plan_reporting_test.py -q --tb=short`
  with `PYTHONPATH=.`. Expect missing module/functions until implemented.
- [x] **Step4: Implement the summary functions.** Derive all facts from plan fields;
  group registered recipes by format in order, retain distinct settings, and use the
  exact copy/rules in design.md. Duration formatting uses minutes/hours rather than
  raw seconds; no separate persistent model or schema. Warning threshold is0.80.
- [x] **Step5: Run GREEN and inspect the rendered mock.** Rerun the Step3 command
  with basetemp `.pytest_tmp_root/compact-green`; all fact/edge/render cases pass.
  Use TermDash visible length for the Step2 width assertions.
- [x] **Step6: Review the pure output against the mock, then commit the new composer
  and tests only:** `git add -- modules/compresser/compresser/plan_reporting.py modules/compresser/tests/plan_reporting_test.py`;
  `git diff --cached --check`; `git commit -m "feat(compresser): compose compact plan summaries"`.

### Task 2: Route plan CLI output and preserve detailed artifacts

**Files:** report_session.py, reporting.py, operation_reports_test.py, MangaDL
compress_test.py and the release/documentation paths in the file map.

**Interfaces:**
- Consumes Task1's `build_plan_summary` and `render_plan_summary`.
- Retains `ReportSession.plan(self, plan, *, population_count)` return contract:
  `(CompressionReport, dict)` and full `self.save(report)` publication.
- Retains `build_plan_report(plan, *, population_count: int,
  context: ReportContext) -> CompressionReport` and existing JSON keys.
- Default plan branch renders with saved `artifacts['latest']`, terminal width and
  `stdout_color_enabled()`; verbose branch uses the existing detailed renderer;
  JSON branch prints no compact report. Other operations retain their routes.

- [x] **Step1: Write failing lifecycle tests in operation_reports_test.py.** Run
  inventory->plan using synthetic images for both adapters; capture stdout/stderr.
  Normal output contains the compact five-row recipe summary and exactly one report
  path; no `Report saved:`/`Latest report:` duplicate footer, hashes or final COMPLETED
  banner. `-v` retains identities/strata/quotas. `-J` stdout parses as one JSON object
  with original operation/plan/report/report_artifacts structure and both saved paths.
  Assert archived Markdown still contains all identities, group quotas and settings.
- [x] **Step2: Add failure and regression checks.** Cause Markdown publication to
  raise OSError at its actual filesystem boundary: exit2, visible save error, no fake
  report path. Redirected/NO_COLOR output contains no ANSI. Add default/header-plan
  compact assertions to the existing MangaDL plan/resume test. Diagnostic report
  distinguishes configured pilot ceiling64 from actual62 and labels perceptual
  null-quality with a dash, not lossless. Existing non-plan preservation fixtures
  must remain byte-identical; do not regenerate them to accept accidental changes.
- [x] **Step3: Run RED.** From modules/compresser, with `PYTHONPATH=..;../mangadl;.`:
  `../../.venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp .pytest_tmp_root/compact-cli-red tests/operation_reports_test.py tests/plan_reporting_test.py -q --tb=short`.
  Expect old verbose/default artifact duplication until routing is changed.
- [x] **Step4: Implement plan-only routing.** Save the full report before rendering,
  use Task1's functions only for normal plan output, and bypass `self.render()`'s
  duplicate artifact printer on that branch. A publication error retains stderr and
  final failure status; pass report_path=None rather than inventing a path. Keep
  verbose and JSON artifact behavior, and every non-plan operation, intact. Correct
  detailed pilot labels and perceptual quality display in reporting.py.
- [x] **Step5: Run GREEN for Step3 and the MangaDL combined header-plan/resume test.**
  From modules/mangadl with `PYTHONPATH=..;../compresser;.`:
  `../../.venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp .pytest_tmp_root/compact-cli-green tests/compress_test.py -k combined_all_format_plan -q --tb=short`.
- [x] **Step6: Synchronize release/docs.** Set compresser/MangaDL3.2.0 in each
  pyproject/exposed version (including MangaDL root shim), dependency>=3.2.0, and
  only their help-registry entries. README documents compact default, `-v` details,
  JSON preservation, heuristic warning and actual-pilot labels. Update handoffs and
  this plan's status/checklist; estimator Task6 remains paused.
- [x] **Step7: Run module regressions and format/lint changed Python.** From each
  owning module with its PYTHONPATH above, run the full `tests` directory using
  `-p no:cacheprovider --basetemp .pytest_tmp_root/compact-full -q --tb=short`.
  Run scripts-help tests with module-owned basetemp and PYTHONPATH. Black uses
  `--workers 1 --line-length 120`; Ruff on changed Python paths. Do not reformat
  unrelated parts of large historical test files or the user-modified registry.
  Require exit0; record counts or named failures without inventing omitted counts.
- [x] **Step8: Refresh local editable metadata only after passing checks:** from root
  `.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e modules/compresser -e modules/mangadl`.
  Verify source/installed versions and installed CLI default/-v/-J against generated
  test inventories. Inspect Windows console at80/120/160 widths with color on/off;
  keep that acceptance pending if unavailable, with the exact boundary recorded.
- [ ] **Step9: Review and publish the functioning checkpoint.** Inspect path-specific
  diffs/status; stage only this task's paths and intended registry lines. Run
  `git diff --cached --check`; commit `feat(compresser): show compact planning output`;
  push the existing feature branch under standing authorization. Verify remote/local
  refs and status, excluding inaccessible pscripts and preserving unrelated work.

## Execution handoff / self-review

Native execution was previously selected and remains the recommended method: these
two tasks share one presentation interface and do not require statistical changes.
Use executing-plans after the user's review. Its final independent review applies
before calling this presentation feature complete; no subagents during planning.

Self-review completed: mock requirements map to Task1 facts/rendering and Task2
lifecycle; all five Review Focus entries have owning tests; interfaces agree.
No test execution, implementation, source edits or production operations in planning.
Resume only after the user confirms this plan captures the requested output.
