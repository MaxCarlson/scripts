# Compression Workspace and Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one compression workspace and automatic Markdown summaries, with readable responsive comparisons and usable small-sample target extrapolations.

**Architecture:** Pure workspace resolution and immutable report facts are shared by both CLI adapters. A new explicit format-ratio extrapolator supplements, not replaces, the existing statistical estimate. TermDash renders responsive console panels; a separate Markdown renderer and atomic publisher consume the same report.

**Tech Stack:** Existing Python3.12 venv, dataclasses, pathlib, SQLite, TermDash, cross_platform locks, pytest; no new external dependencies.

**Spec:** [design.md](design.md). Baseline64b33d1 on `compression-ui-color-and-stats-20261017`.

## Global Constraints

- Shared behavior between compresser and MangaDL; preserve MangaDL page/source/partial safeguards.
- Do not implement previously paused Plan03 P8 CLI overhaul, pilot/confirmation sampling or codec/scheduling changes.
- Existing encoding, sampling selection, resource policy and write interlocks remain unchanged.
- Small samples do not suppress model-based extrapolations; never present them as statistically guaranteed projections.
- Existing JSON keys/semantics remain; new fields are additive and stdout stays machine-parseable.
- Binary MiB/GiB; no imperceptibility or bit-for-bit-file lossless claims.
- Target guard precedes short workspace publication locks; no SQLite handles cross worker threads.
- No implicit migration/copy of SQLite or downloader state; no production B:\Hent operations.
- Full affected tests and scoped commits per usable checkpoint; push only under applicable direct authority; no automatic merge.
- Next major versions at workspace delivery; synchronize exposed versions, dependencies/help registry and reinstall wrappers.

## Review Focus

1. Same leaf name at different targets, linked workspaces and concurrent first runs must not share/overwrite unrelated state (Task1).
2. Skewed sizes, failed encodes and absent formats must produce byte-weighted, explicitly qualified extrapolations, not inflated ratios (Task2).
3. Narrow terminals, Unicode/control characters and non-TTY stdout must preserve complete values without malformed ANSI or overwide grids (Task3).
4. Disk-full/cancellation/concurrent publication must preserve parseable historical reports and report source-write status truthfully (Task4).
5. Inventory-only/file-depth and JSON/preview early-return paths must save the correct operation report without opening an unwanted trial cache or losing failures (Task5).

## File ownership

- `compresser/workspace.py`: resolved paths, manifest identity and short publication ownership.
- `compresser/extrapolation.py`: model-based target impact and coverage aggregation.
- `compresser/report_models.py`: typed immutable context/coverage/results/issues/diagnostics.
- `compresser/reporting.py`: section composition, highlights and shared formatting facts.
- `compresser/markdown_report.py`: Markdown rendering/publication.
- `compresser/ui.py`: live dashboard retained; report facade delegates rather than growing more print logic.
- `termdash/table.py`: opt-in reusable panel/wrapped table rendering; old API unchanged.
- `compresser/cli.py`, `sampling.py`, `inventory.py`, `cache.py`, `preview.py` and
  `mangadl/cli_core.py`, `compress.py`: only required integration points.

Paths above are relative to their existing package roots under `modules/`. No broad refactor.

## Common checks per checkpoint

Run focused TaskN tests RED before implementation, then GREEN. Run the full affected
module suites below before committing; no live external service/production input:

```powershell
.venv/Scripts/python.exe -m pytest modules/compresser/tests -q -p no:cacheprovider --basetemp=modules/compresser/.pytest_tmp_root/reports-N --tb=short
.venv/Scripts/python.exe -m pytest modules/mangadl/tests -o addopts= -q -p no:cacheprovider --tb=short
.venv/Scripts/python.exe -m pytest modules/scripts_help/tests -q -p no:cacheprovider --basetemp=modules/scripts_help/.pytest_tmp_root/reports-N --tb=short
```

When TermDash changes also run its entire suite with module-local basetemp. Black120,
Ruff changed Python and `git diff --check` must pass. Test commands may require normal
filesystem permissions for existing preview hardlink fixtures; distinguish sandbox
denial from source failures. Stage explicit task files only. Preserve unrelated edits.

### Task 1: Safe one-folder workspace and compatibility

**Files:** Create `modules/compresser/compresser/workspace.py`,
`modules/compresser/tests/workspace_test.py`; modify `inventory.py`, `cache.py`,
`sampling.py`, both CLI adapters/builders and their inventory/preview argument tests.

**Interfaces:** `resolve_workspace(target: Path, parent: Path | None, *, owner: str,
legacy_inventory: Path | None = None) -> CompressionWorkspace` is pure;
`initialize_workspace(workspace: CompressionWorkspace) -> None` validates/creates
under short locks. Frozen CompressionWorkspace exposes root, inventory_file,
trial_cache_file, reports_dir, previews_dir, target and owner. `args._workspace`
is resolved once; existing inventory/cache helpers consume it, retaining library
call compatibility for callers without CLI workspace context.

- [ ] RED tests `test_directory_I_names_target_workspace`, `test_default_is_external_sibling`,
  `test_standalone_file_target_uses_stem`, `test_legacy_sqlite_path_preserved_and_warned`:
  target `base/book`, parent `base/state` => `base/state/book-mangadl`, inventory
  `book-mangadl-inventory.sqlite3`, trials `book-mangadl-trials.sqlite3`; no files from pure resolution.
- [ ] RED `test_nonempty_unowned_or_foreign_manifest_rejected`,
  `test_linked_inside_source_and_database_alias_rejected`,
  `test_two_concurrent_initializers_revalidate_owner`: no overwrites, symlink/reparse
  rejection where supported, same-target reuse succeeds, different-target fails.
- [ ] Implement signatures and spec naming/manifest/legacy contract. `-I/--workspace`
  is canonical; hidden `--inventory-file` warns, old explicit paths remain usable.
  Do not remove -K/-O/-X. Resolve optional bare -O to workspace previews; never generate
  previews unless -O is supplied. Validate before output creation.
- [ ] GREEN focused workspace and both CLI inventory/cache/preview tests, then common checks.
  Update versions to next majors (source currently0.34.0/1.60.0 =>1.0.0/2.0.0 if unchanged),
  deps/registry and workspace usage docs. Full uninstall/reinstall affected wrappers;
  verify `compresser -V`, `mangadl -V`, both help surfaces, no unrelated CLI change.
- [ ] Scoped commit: `feat(compression): consolidate analysis artifacts in target workspaces`.
  Publish checkpoint only under authorized workflow, then Task2.

### Task 2: Explicit format-weighted extrapolation and coverage

**Files:** Create `compresser/extrapolation.py`, `tests/extrapolation_test.py`;
modify `models.py`, `cli.py:run_comparison`, `sampling.py` coverage summary;
MangaDL/standalone JSON comparison serialization and focused tests.

**Interfaces:** `extrapolate_target(population: Sequence[ImageMetadata], selected:
Sequence[ImageMetadata], results: Sequence[ImageResult], *, complete: bool) -> dict`
returns schema1/method format_ratio_v1, estimated|calculated|partial status, target
and observed bytes, retained/saved/reduction, per-format ratios and fallback bytes/share,
warnings and successful/failed counts. `ComparisonRow.extrapolation` additive dict;
`ComparisonRow.issues` complete reason->count and `ComparisonRow.settings` typed/plain
strategy facts. No raw retained image list on ComparisonRow. Old estimate untouched.

- [ ] RED `test_byte_ratio_not_mean_percentage`: JPEG samples (100->50,900->900)
  yield5%, not25%; JPEG population10,000 bytes saves500. PNG population2,000 with
  sample200->100 saves1,000; total1,500/12,000=12.5%, retained10,500.
- [ ] RED `test_unsampled_format_uses_marked_overall_ratio`: JPEG population1,000,
  sample100->50; WebP population1,000 unsampled =>1,000 total saved, fallback1,000
  target bytes/50%. Incomplete gallery coverage must not suppress output.
- [ ] RED tests failed trial(100->error) contributes100 denominator/0saved;
  all-failed =>zero scenario/no-success status; cached vs uncached identical impacts;
  JPG/JPEG grouping, empty/zero bytes no invented ratio, duplicate/foreign results
  rejected, partial census never `calculated`, complete census exact retained bytes.
- [ ] RED signed growth allow-larger(100->120) =>-20saved/120retained; complete
  count/byte coverage and per-format sampled-byte columns agree with selected metadata.
- [ ] Implement pure aggregation and collect compact facts before batch results leave
  scope. Preserve existing selection/design-estimate APIs. Attach additive extrapolation
  to JSON, retaining existing estimate/confidence fields and distinguishing methods.
- [ ] GREEN focused and common suites. Docs explain model assumption/fallback, no
  precision guarantee, failed-original policy and full-inventory snapshot scope.
- [ ] Scoped commit `feat(compresser): estimate target savings from format-specific sample ratios`.

### Task 3: One report model and responsive comparison presentation

**Files:** Create `compresser/report_models.py`, `reporting.py`, tests
`reporting_test.py`; modify `ui.py`, `recommendations_test.py`, `ui_test.py`;
extend `modules/termdash/table.py` and `tests/table_test.py` opt-in API.

**Interfaces:** `build_comparison_report(rows: Sequence[ComparisonRow], *, context:
ReportContext) -> CompressionReport`; `render_console_report(report:
CompressionReport, *, width: int, color: bool, verbose: bool = False) -> str`.
ReportContext holds target/workspace, population+sampling summary, snapshot, actual
CLI/strategy settings, resource/cache facts and operation status. CompressionReport
contains versioned sections with stable IDs and immutable values, not precolored text.
TermDash `render_table_panels(headers, rows, *, identity_columns, alignments=None,
max_width: int) -> list[str]` preserves full cells and opt-in behavior.

- [ ] RED width40/60/80/100/120/160 cases: every strategy/value/header remains present;
  repeat ID/strategy in split panels, identical row order; visible line width<=budget;
  tiny widths use labeled records. ANSI+CJK+combining characters align; newline/control
  injection escaped. Existing render_table tests unchanged.
- [ ] RED report consistency: one extrapolation result determines all tables/highlights;
 49unchanged+1failure cannot showpositive savings; all-failed excluded; partial failures
  labeled. No incompatible hero-vs-unavailable recommendations, old quality badges,
  duplicated warnings or numeric prose outside appropriate tables.
- [ ] RED stdout nonTTY/stderrTTY, NO_COLOR, TERM=dumb =>no ANSI; enabled color semantic
  red errors/yellow warnings/green savings/blue-cyan identities. Labels work without color.
- [ ] RED cached-only/mixed rates labeled trial throughput, never encoder-speed winner;
  explicit zero-duration rate not fabricated. Trace current engine rate if zero, add
  focused regression for any actual construction bug without altering scheduling.
- [ ] Implement spec section order/units/coverage, contextual calculated vs estimated
  headers. Remove unsupported imperceptibility and bit-for-bit claims. Print detailed
  phase/raw-candidate diagnostics only under -v; retain all facts for Markdown.
  Use wrapper facade for existing print_comparison_matrix calls, no duplicate print paths.
- [ ] GREEN focused, full TermDash and common suites. Commit `feat(compression): render aligned coverage and impact report panels`.

### Task 4: Markdown rendering and durable publication

**Files:** Create `compresser/markdown_report.py`, `tests/markdown_report_test.py`;
use Task1 workspace and Task3 report types. Extend workspace publication tests.

**Interfaces:** `render_markdown_report(report: CompressionReport) -> str`;
`publish_markdown_report(workspace: CompressionWorkspace, report: CompressionReport)
-> ReportArtifacts`, a frozen result with archive_path/latest_path. Report filename
UTC timestamp+unique runID+operation; schema/method/status recorded in content.

- [ ] RED same fixture console/Markdown numbers, statuses, coverage/fallbacks/errors
  identical; Markdown unlimited-width tables, all diagnostic summary sections retained
  regardless of console verbose, no ANSI. Escape pipes/backticks/newlines/control chars;
  commands fenced, literal Windows paths preserved.
- [ ] RED two same-second/concurrent runs unique archives; latest contains a complete
  published report. Inject archive and latest write/rename failures, disk-full and
  permission denial; older files unchanged where publication failed, temps cleaned,
  no report path claimed on failure. Use existing atomic/retry helpers where suitable.
- [ ] Implement coordinator-only publication and short locks, source path/ownership
  revalidation. Cancellation/failed report status is explicit; no generic completed
  label. Do not capture stdout, animation, credentials or subprocess/private logs.
- [ ] GREEN focused/common suites. Commit `feat(compresser): publish automatic Markdown analysis reports`.

### Task 5: All detailed summary paths, docs and final acceptance

**Files:** Both CLI adapters/builders; `inventory_ui.py`, `file_inventory.py`,
`preview.py`, `snapshots.py` (if print facade needed); extend
`tests/cli_test.py`, `file_inventory_test.py`, `preview_test.py`,
`modules/mangadl/tests/compress_test.py`.
Both READMEs/API docs/handoffs, active status/checklist, registry/dependencies.

**Interfaces:** Task3 report builders `build_inventory_report(payload: dict, *,
context: ReportContext) -> CompressionReport`, `build_analysis_report(result:
BatchResult, *, context: ReportContext) -> CompressionReport`,
`build_preview_report(payload: dict, *, context: ReportContext) -> CompressionReport`;
all use Task4 publisher. Central adapter finalization owns status+artifact output.

- [ ] RED both CLIs: header inventory create+refresh writes report in resolved
  reports folder containing per-gallery/format counts/bytes, inspected/reused/unreadable
  totals/profile/freshness; files-only clearly unverified, no trial DB or encoder.
- [ ] RED comparison, single analysis, applied generated-fixture write, preview
  success/error/cancel early-return paths publish correct detailed summary. Preview
  artifacts stay source-external; source association/cover/partial safeguards unchanged.
- [ ] RED -J remains parseable JSON with additive artifact paths; report-write error
  stderr/exit2 on otherwise-successful operation, preserve original nonzero/130.
  Applied write+report failure says sources may already be modified. Parser failure
  creates no workspace/report. Interrupted run publishes only after owners drain.
- [ ] Integrate finalizers; consolidate duplicate snapshot/cache/sampling prints.
  Save available detailed summary facts to Markdown even with compact console. No
  recovery journal relocation; recovery unchanged. Any suggested preview command
  uses actual settings, escaped PowerShell strings and selection filters; no unsafe
  sample-based ready-to-write banner.
- [ ] Update stale docs/memory-policy wording from actual source, old->new workspace
  examples, automatic inventory and other reports, legacy paths, statistical vs
  model estimates, cache-rate interpretation and manual acceptance. Update shared
  handoffs with links; keep historical plan context and P8 pause explicit.
- [ ] Full common suites plus TermDash, Black/Ruff/diff check, installed-wrapper
  version/help and generated temporary CLI end-to-end runs; no production data.
- [ ] One fresh whole-change review using requesting-code-review; inspect full diff
  against pre-implementation base. Resolve important findings with RED/GREEN tests,
  record deferred minors. Real Windows terminal resize/color and reader-quality
  acceptance remain explicit manual gates, not claimed from StringIO fixtures.
- [ ] Scoped final commit/push under authority, clean parent status (inaccessible
  pscripts excluded and disclosed), concrete inventory/comparison/preview commands.
  No main merge. Mark implementation complete only for verified deliverables.

## Plan self-review

All design sections map to Tasks1-5; Review Focus cases are pinned above. Definitions
are shared rather than duplicated between adapters. This plan deliberately avoids
P8 argument redesign except the approved workspace semantics and optional preview
destination. No output-only confidence interval is manufactured. Generated fixtures
and failure injection cover runtime safety; visual/reader gates remain manual.
