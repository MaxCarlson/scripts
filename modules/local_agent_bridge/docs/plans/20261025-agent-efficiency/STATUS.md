# Local Coding-Agent Efficiency — Status

**Last updated:** 2026-10-29
**Overall state:** Implementation phase complete; P0–P6, matched benchmark fixtures, B0/B2/B3 profiles, and the fail-closed intervention comparison contract are ready for integration. Live validation and performance evaluation remain pending separate authorization and runtime evidence.
**Verified baseline:** remote `main` merge commit `92c5f068fe2d0c8c99ca4a14991388b1819a3764`
**Performance branch:** `codex/local-agent-efficiency-20261025`
**Canonical plan:** `./plan.md`
**Execution handoff:** `./HANDOFF.md`

## Milestone tracker

- [x] P0 — Baseline and repository reconciliation
- [x] P1 — Worker instructions and task-envelope acceptance (satisfied by existing v3.3.0 implementation)
- [x] P2 — Bounded lexical retrieval core and CLI
- [x] P3 — OpenCode retrieval-tool integration (offline implementation; no live worker evaluation)
- [x] P4 — Durable task checkpoints
- [x] P5 — Structural outlines and repository maps
- [x] P6 — Compaction-aware recovery
- [ ] P7 — Advanced retrieval evaluation
- [ ] Controlled benchmark comparisons
- [ ] Final documentation and regression validation

## P0 reconciliation

- GitHub connector confirmed remote `main` at `92c5f068fe2d0c8c99ca4a14991388b1819a3764`, merge subject `Merge branch 'codex/local-agent-bridge-reliability-20261025'`; local branch/worktree was created from that exact commit. Local Git `origin/main` was stale at `b2ef5fb`; `git ls-remote` could not run because Git Bash/SSH failed with `NtCreateDirectoryObject ... 0xC0000022`.
- Baseline package is `local-agent-bridge` 3.3.0, Python `>=3.11`; dependencies remain `tomlkit` and `resource-metrics`. The additive retrieval implementation should use the standard library and optional `rg`, without a new mandatory dependency. Version bump will be required with the feature.
- `local_agent_bridge` owns retrieval/context preparation. `agent_benchmark` owns execution evidence, default-deny tool profiles, scope enforcement, and independent validation. `benchmark_core` owns canonical comparisons; `llm_monitor` owns live observability. No cross-module runtime dependency is justified for P2.
- Existing setup planner/installer owns only declared profile resources and preserves receipts/rollback. P2 will add no installer-owned production files or configuration writes.
- The prior production Codex CLI `opencode_worker` discovery blocker remains unverified and unresolved. No live Codex probe, OpenCode service request, LM Studio request, inference, model load, or benchmark trial was made.

## P1 reconciliation

P1 is **satisfied by existing implementation**; no prompt rewrite or B1 variant is warranted. The canonical worker prompt already directs search-first file/symbol discovery, offset/limit excerpts, focused tests, progress checkpoints, and concise evidence-based results. The task envelope already carries candidate paths/symbols, tests, base revision, allowed work, constraints, checks, and structured return evidence. Existing resource tests assert these contracts. Reliability guarantees and worker/reviewer permissions remain intact.

## Baseline validation

All commands were offline and run against the verified v3.3.0 source tree; temporary pytest files stayed in the module-local `.pytest_tmp_root`.

- In the reliability branch at `76d0f474`, complete `local_agent_bridge` suite: 92 passed, 1 skipped, 2 failed. Both failures were shell-hook tests failing before bridge assertions because Git Bash could not create an MSYS named object (`NtCreateDirectoryObject`, `0xC0000022`).
- In the performance worktree at `92c5f068`, `python -m pytest -c pyproject.toml tests -q --basetemp .pytest_tmp_root/perf-baseline-no-msys --tb=short --deselect tests/audit_test.py::test_shell_hook_preserves_paths_with_spaces --deselect tests/audit_test.py::test_shell_mode_comes_from_receipt_modes_only` — 92 passed, 1 skipped, 2 deselected.
- In the performance worktree, `python -m pytest -c pyproject.toml tests/tool_profile_test.py tests/comparison_conditions_test.py tests/evidence_test.py -q --tb=short` — 55 passed, 1 skipped. No live worker or benchmark trial was started.
- A broader attempt including `agent_benchmark/tests/bridge_test.py` made no further output after 13 dots and was interrupted; this is not counted as a pass. Narrow benchmark safeguards tests above passed.
- A GitHub-hosted remote query verified the merged commit. Direct SSH remote lookup is blocked by the current Windows sandbox; no fetch or remote mutation occurred.

## P2 implementation decisions

- Add a `code` command group with `locate`, `search`, and `context` operations and machine-readable JSON; keep existing `setup`, `model`, `opencode`, and `run` behavior intact.
- Provide reusable read-only retrieval APIs for path discovery, literal/explicit-regex search, and exact line-range context. Bound candidate files, matches, lines, per-line bytes, and serialized response bytes; report truncation and errors explicitly.
- Use Git's tracked/untracked nonignored path list in repositories, with deterministic fallback scanning outside Git. Use `rg` when present through an argument list (never a shell); provide a bounded standard-library fallback when absent.
- Canonicalize all requested paths under the workspace and refuse escapes through symlinks/junctions. Explicit file arguments may access ignored or untracked files only when the caller names them.
- No mandatory dependencies, indexing service, vector store, prompt edit, permission change, or installer change.

## Release A implementation evidence

P2 is implemented in `local_agent_bridge.retrieval` and exposed as the additive `local-agent code locate|search|context` command group. The reusable functions are `locate`, `search`, and `context`; their versioned JSON payload schema is `local-agent-retrieval-v1`. Discovery includes Git tracked and nonignored untracked files, explicit paths can include ignored files, literal search is default, regex is opt-in, and missing `rg`/Git have bounded standard-library paths. All operations are read-only and enforce workspace containment, bounded candidate/file/scan/line/result/output limits, exact line provenance, and explicit error/truncation metadata.

P1 remains satisfied by v3.3.0. No worker prompt rewrite or B1 instruction variant was introduced. The package version and `__version__` were advanced together to 3.4.0 for the additive feature; there are no new mandatory dependencies or permission/setup changes.

Changed implementation files:

- `local_agent_bridge/retrieval/__init__.py`
- `local_agent_bridge/retrieval/core.py`
- `local_agent_bridge/commands.py`
- `tests/retrieval_test.py`
- `tests/commands_test.py` (version assertion)
- `pyproject.toml`, `local_agent_bridge/__init__.py` (3.4.0)
- `README.md`
- `scripts_help/scripts_help/registry/registry.py`

Offline validation in the performance worktree at the verified baseline commit:

- Focused retrieval tests: **22 passed** using `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if 'local_agent_bridge' not in getattr(x, '__module__', '')]; sys.path.insert(0, 'modules/local_agent_bridge'); import pytest; raise SystemExit(pytest.main(['modules/local_agent_bridge/tests/retrieval_test.py', '-q', '--basetemp=modules/local_agent_bridge/.pytest-retrieval-tmp']))"`. The import-finder adjustment selects the worktree source instead of an ambient editable install of v3.1.0; the in-worktree pytest temp path avoids a Windows sandbox denial under `%LOCALAPPDATA%\Temp`.
- Full bridge suite: **115 passed, 1 skipped, 1 deselected** with the same import-finder adjustment and `--basetemp=modules/local_agent_bridge/.pytest-suite-final-tmp`; the deselected case is the known Git Bash/MSYS `test_shell_mode_comes_from_receipt_modes_only` failure (`Python was not found` through the Windows app-execution alias). Earlier full-suite baseline also had `test_shell_hook_preserves_paths_with_spaces` fail before bridge assertions due the sandbox's MSYS named-object error. The other baseline case passed on this run.
- `ruff check modules/local_agent_bridge/local_agent_bridge/retrieval modules/local_agent_bridge/tests/retrieval_test.py modules/local_agent_bridge/local_agent_bridge/commands.py`: **All checks passed**.
- Manual read-only CLI checks: Git locate returned `local_agent_bridge/commands.py`; targeted literal search returned `local_agent_bridge/commands.py:37`; context returned exact lines 37–38. All returned `status=ok`, `truncated=false`, and explicit `discovery`/engine metadata where applicable. An initial broad search over the 200-file default cap correctly returned partial/truncated with no early match; README examples now demonstrate using `--path` and explain `--max-files`.
- No model, inference, OpenCode server, setup mutation, or live benchmark operation was performed.

Known environment note: on this machine pytest's default temp root is denied by the sandbox, and the ambient editable finder shadows the worktree package. Validations therefore used a module-local `--basetemp` and explicitly removed that finder. Two test temp directories are ignored test artifacts.

## P3 implementation evidence

The pinned OpenCode v1.19.3 contract was verified in its tagged source before implementing the adapter. The tool-definition type accepts a description, JSON-schema-compatible args, and an `execute(args, context)` function; tool context exposes the session's `directory`. The v1.19.3 tool registry discovers `*.js`/`*.ts` files in tool directories and maps default exports to the file basename, so the implementation uses the smaller file-based custom-tool surface rather than a plugin lifecycle hook. References: [pinned plugin tool type](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/plugin/src/tool.ts), [pinned tool registry](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/tool/registry.ts).

`resources/opencode-tools` provides `code_locate` and `code_context`, plus a shared helper. Both invoke the existing `local-agent code` CLI using `child_process.spawnSync` with an argv array, `shell: false`, the OpenCode session directory, a 10-second timeout, and a bounded output buffer. The setup planner can opt in with `local-agent setup plan --code-retrieval -o retrieval-plan.json`, review, then apply with `local-agent setup apply -i retrieval-plan.json`; `--no-code-retrieval` plans retirement. Three files are individually receipt-managed under the user's OpenCode `tools` directory, preserving unrelated tools and configuration. Default setup behavior is unchanged. Setup tests cover opt-in, saved-plan replay, persistence across routine plans, and clean disable/removal.

`agent_benchmark` now accepts `retrieval-files-v1` as a separate task profile. It prepares a `benchmark-retrieval` role with a `* = deny` reset and allows only the existing file tools plus `code_locate` and `code_context`; it retains the existing no-shell/no-MCP/no-web contract and exact prompt/effective-permission fingerprinting. The comparison condition already records each task's exact profile. Offline preflight tests verify the role and permission list without submitting a session.

Static tool-definition sizing serialized the two name/description/JSON-schema records to **852 UTF-8 bytes total** (`code_locate`: 347; `code_context`: 505). This measures the adapter definition payload shape, not exact tokenizer tokens or OpenCode's full provider request. No live session or controlled worker comparison was run, so no retrieval or coding-quality improvement is claimed.

P3 offline validation:

- Full bridge suite after P3: **118 passed, 1 skipped, 1 deselected**; same known Windows Git Bash Python app-execution-alias case was deselected. The remaining baseline MSYS shell-hook failure was not deselected and passed this run.
- Benchmark profile/comparison/evidence/attempt tests plus retrieval-role mocked bridge preflight: **82 passed, 1 skipped**.
- Node adapter argv contract, setup install/disable, saved-plan replay, and P2 tests are included in the bridge suite.
- Targeted `ruff check` across all changed Python code: **All checks passed**; `git diff --check` passed.
- No model request, inference, OpenCode server request, global profile/config write, live worker evaluation, or benchmark trial was performed.

## P4 checkpoint implementation

The pre-implementation audit found that v3.3.0 recovery guidance preserves coordinator-owned session/job/message identities and forbids uncertain resubmission, while `agent_memory` stores long-lived semantic notes and `development_ledger` stores project plan/stage/validation history. Neither is an authoritative store for task objective, authorized scope, exact source hashes, pending checks, blockers, and next action. P4 therefore adds a distinct worker task-state checkpoint without duplicating job lifecycle status.

`local_agent_bridge.context.checkpoint` now provides `save_checkpoint`, `load_checkpoint`, and `recovery_packet`. The versioned schema is capped at 256 KiB; saves use atomic replace and keep data outside the canonical Git worktree by default (`~/.local/share/local-agent/checkpoints`, overrideable with `LOCAL_AGENT_CHECKPOINT_ROOT` or `--state-dir`). It records only hashes/ranges for confirmed UTF-8 text references, enforces path containment and source-size limits, validates project/workspace identity, and flags changed or unavailable revisions/source evidence as stale. Recovery preserves session, job, initiating message, provider/model, and worker-agent identity; it never dispatches or resubmits a job.

The additive CLI is `local-agent checkpoint save|show|recover`. Save accepts a bounded JSON task envelope; show returns the stored state; recover adds stale-evidence and no-resubmission guidance. README examples document the workflow.

P4 focused offline validation:

- Red phase: the Git-worktree containment and unavailable-revision tests failed against the initial implementation for the expected reasons.
- Focused green command: `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if 'local_agent_bridge' not in getattr(x, '__module__', '')]; sys.path.insert(0, 'modules/local_agent_bridge'); import pytest; raise SystemExit(pytest.main(['modules/local_agent_bridge/tests/checkpoint_test.py', 'modules/local_agent_bridge/tests/commands_test.py::test_checkpoint_cli_save_show_and_recover_are_local_and_stale_aware', 'modules/local_agent_bridge/tests/commands_test.py::test_setup_retrieval_opt_in_is_saved_and_can_be_disabled', '-q', '--basetemp=C:/Windows/Temp/local-agent-p4-checks']))` — **12 passed, 1 skipped** (symlink creation unavailable on this host).
- A focused run inside the Git worktree initially failed the new external-state invariant because pytest placed fixtures inside the repository; rerunning under `C:/Windows/Temp` respected the invariant. The test runner's default temp directory is within a broader `C:/Users/mcarls` Git worktree on this host.

P4 validation is complete:

- Full bridge suite: **129 passed, 2 skipped, 1 deselected** using `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if 'local_agent_bridge' not in getattr(x, '__module__', '')]; sys.path.insert(0, 'modules/local_agent_bridge'); import pytest; raise SystemExit(pytest.main(['modules/local_agent_bridge/tests', '-q', '-rs', '--basetemp=C:/Windows/Temp/local-agent-p4-full-rs', '--tb=short', '--deselect=modules/local_agent_bridge/tests/audit_test.py::test_shell_mode_comes_from_receipt_modes_only']))`. The deselected test is the previously documented Git Bash/MSYS Windows app-execution-alias failure; the other baseline MSYS shell-hook test passed. Skips: checkpoint source symlink creation is unavailable and setup file symlinks require Windows privilege.
- Focused checkpoint/CLI/setup tests: **12 passed, 1 skipped**. The skipped case is symlink creation unavailable on this host.
- `ruff check modules/local_agent_bridge/local_agent_bridge/context/checkpoint.py modules/local_agent_bridge/local_agent_bridge/commands.py modules/local_agent_bridge/tests/checkpoint_test.py modules/local_agent_bridge/tests/commands_test.py`: **All checks passed**.
- `local-agent checkpoint --help` lists `save`, `show`, and `recover`; the checkpoint CLI test exercises save/show/recover and stale-source detection. `git diff --check` passed.
- Changed files: `README.md`; `docs/plans/20261025-agent-efficiency/{HANDOFF.md,STATUS.md}`; `local_agent_bridge/commands.py`; new `local_agent_bridge/context/{__init__.py,checkpoint.py}`; `tests/commands_test.py`; new `tests/checkpoint_test.py`.
- No inference, model request, OpenCode server operation, or live benchmark was performed.

## P5 structural retrieval

P5 adds `local_agent_bridge.retrieval.symbols` for exact Python AST outlines (imports, classes, functions, methods, signatures, line ranges, and raw source SHA-256) and `repository_map` for task-ranked symbols. New additive CLI actions are `local-agent code symbols` and `local-agent code map`. Both reuse the existing Git-aware discovery, workspace containment, and response budgeting. Maps prioritize path-relevant Python files, rank qualified names/signatures by task-word overlap, and are deterministic for a fixed workspace/query.

Every map is rebuilt from current source; there is no persistent cache to invalidate. Source hashes make result identity explicit. Python file count, per-file bytes, total scan bytes, symbol count, result count, serialized bytes, and a conservative token upper-bound are capped. `--max-tokens` caps serialized UTF-8 bytes; it is a tokenizer-independent worst-case upper-bound proxy, not a provider tokenizer measurement. Non-Python work continues through the lexical API. Structural results remain optional; no representative controlled task comparison has yet established an improvement over lexical-only retrieval.

P5 validation:

- Focused structural tests: **11 passed**. They cover AST provenance, import/class/function/method outlines, malformed and binary source errors, fresh hashes, Git ignored paths, relevance ranking, result/file/output bounds, unsafe paths, CLI JSON output, and handling Git-listed non-Python entries.
- Full bridge suite: **140 passed, 2 skipped, 1 deselected** using the P4 full-suite command with `--basetemp=C:/Windows/Temp/local-agent-p5-final`. The symlink skips are `checkpoint_test.py` (symlink creation unavailable) and `setup_test.py` (Windows privilege required); the deselected Git Bash/MSYS app-execution-alias test is the known environment failure.
- Targeted Ruff across `retrieval/structure.py`, retrieval exports, `commands.py`, and `structure_test.py`: **All checks passed**. `git diff --check` passed.
- Manual bounded measurement on this worktree: `repository_map("checkpoint recovery session next action", max_files=80, max_results=40, max_tokens=3000)` returned 5 ranked symbols, partial/truncated, in **617.31 ms**, with **7,320,819 bytes** peak Python traced allocation and a **2,678-byte** serialized upper bound. Top-ranked results included `context/checkpoint.py:236 save_checkpoint` (score 14) and `context/checkpoint.py:352 recovery_packet` (score 10). A separate 4 KiB AST outline returned 25 of 33 symbols with source path/hash and explicit internal truncation. These are single-run implementation measurements, not a lexical baseline comparison or proof of coding-quality improvement.
- No inference, model request, OpenCode server operation, or live benchmark was performed.

Changed files: `README.md`; `commands.py`; `retrieval/__init__.py`; new `retrieval/structure.py`; new `tests/structure_test.py`.

## P6 compaction-aware recovery

Pinned OpenCode v1.19.3 source verification confirms the plugin hook type `experimental.session.compacting` receives `{sessionID}` and mutable `{context: string[], prompt?: string}`; OpenCode invokes it before compaction and appends `context` to its default summary prompt. The adapter does not override the prompt or `experimental.compaction.autocontinue`. The same pinned source confirms plugin auto-discovery under configured `plugin(s)` directories; setup installs to the existing user OpenCode config directory using the existing receipt planner. References: [plugin hook type](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/plugin/src/index.ts#L290-L317), [compaction invocation](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/session/compaction.ts#L346-L365), [plugin file discovery](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/config/plugin.ts#L16-L27), [configured directory discovery](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/config/config.ts#L441-L444).

P6 implementation adds `recover_session` and `local-agent checkpoint recover-session SESSION_ID`, which selects the latest checkpoint carrying that exact session identity and recomputes revision/source freshness. The optional `local_agent_checkpoint.js` hook uses direct `execFile` argv (no shell), session project directory, a 5-second timeout, and a 4 KiB maximum injected context. Missing local-agent/checkpoint state is a no-op; the context preserves job/message identity and explicitly forbids resubmission. Setup exposes receipt-managed `--checkpoint-compaction` / `--no-checkpoint-compaction`, off by default; it does not write shared config or change tool permissions.

P6 validation:

- Focused offline P6 suite: **6 passed** across session lookup/source revalidation, missing session state, CLI JSON, saved-plan replay, receipt install/preservation/removal, and Node dynamic plugin import/hook argument/context bounds.
- Full bridge suite: **146 passed, 2 skipped, 1 deselected** using `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if 'local_agent_bridge' not in getattr(x, '__module__', '')]; sys.path.insert(0, 'modules/local_agent_bridge'); import pytest; raise SystemExit(pytest.main(['modules/local_agent_bridge/tests', '-q', '-rs', '--basetemp=C:/Windows/Temp/local-agent-p6-full', '--tb=short', '--deselect=modules/local_agent_bridge/tests/audit_test.py::test_shell_mode_comes_from_receipt_modes_only']))`. Skips: checkpoint symlink creation unavailable; setup file symlinks require Windows privilege. The deselected test is the previously documented Git Bash/MSYS Windows app-execution-alias failure.
- `ruff check modules/local_agent_bridge/local_agent_bridge/context/checkpoint.py modules/local_agent_bridge/local_agent_bridge/commands.py modules/local_agent_bridge/local_agent_bridge/setup/planner.py modules/local_agent_bridge/local_agent_bridge/setup/installer.py modules/local_agent_bridge/tests/checkpoint_test.py modules/local_agent_bridge/tests/commands_test.py modules/local_agent_bridge/tests/setup_test.py modules/local_agent_bridge/tests/opencode_tools_test.py`: **All checks passed**. `git diff --check` passed. CLI help lists `recover-session`. The package-data rule `resources/**/*` includes the new plugin asset.
- OpenCode source and plugin API were checked against the pinned v1.19.3 source links above. Node dynamic import verifies the CommonJS module's default export shape, but no actual OpenCode server session was started; installed runtime loading remains unverified.
- Changed files: `README.md`; this plan's `HANDOFF.md` and `STATUS.md`; `commands.py`; `context/checkpoint.py`; `setup/{installer.py,planner.py}`; new `resources/opencode-plugins/local_agent_checkpoint.js`; `tests/{checkpoint_test.py,commands_test.py,opencode_tools_test.py,setup_test.py}`.
- No inference, local-model request, OpenCode server operation, or live benchmark occurred. Controlled B0/B2/B3/B4 comparisons remain unmeasured; no efficiency gain is claimed.

## Next action

P6 implementation and offline validation were completed and pushed. B3 structural tool/profile wiring is now the active stage; see the validation and next-action details below. Do not add frameworks or speculative compaction behavior absent a measured retrieval limitation. Controlled efficiency evaluation remains separately authorized.

## B3 structural retrieval profile wiring — offline implementation complete

Stage commit: `0f1f3f1bcd7a6b6fcb0845dd8257263bca0a8403`, pushed to `origin/codex/local-agent-efficiency-20261025`.

The optional structural retrieval tools are receipt-managed separately from the lexical pair. `local-agent setup plan --structural-retrieval` enables `code_symbols` and `code_map` and includes their lexical dependencies; both groups can be retired with `--no-structural-retrieval --no-code-retrieval`. The OpenCode adapters reuse the existing `local-agent code` commands and `runLocalAgent` helper with direct argv, no shell, active-workspace directory, per-command JSON limits, and a 16 KiB adapter output cap.

`agent_benchmark` recognizes `retrieval-structural-v1` as its distinct B3 condition and prepares a `benchmark-structural` role with default deny plus safe file tools and exactly `code_locate`, `code_context`, `code_symbols`, and `code_map`. Bridge preflight rejects shell grants and missing structural tools before session submission. Prompt/profile identity and effective permissions are retained in trial evidence. B0 remains the verified reliability v3.3.0 baseline; no B3 performance or quality gain is claimed.

Validation:

- Local-agent bridge full suite: **149 passed, 2 skipped, 1 deselected** in 16.53s. The skips require unavailable Windows symlink privileges; the deselected test is the known Git Bash/MSYS app-execution-alias case. Command: `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if 'local_agent_bridge' not in getattr(x, '__module__', '')]; sys.path.insert(0, 'modules/local_agent_bridge'); import pytest; raise SystemExit(pytest.main(['modules/local_agent_bridge/tests', '-q', '-rs', '--basetemp=C:/Windows/Temp/local-agent-b3-final', '--tb=short', '--deselect=modules/local_agent_bridge/tests/audit_test.py::test_shell_mode_comes_from_receipt_modes_only']))"`.
- Benchmark tests directly covering profile, bridge, attempts, evidence, and comparison conditions: **117 passed, 1 skipped**; the skip is Windows symlink privilege. Command: `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if not any(name in getattr(x, '__module__', '') for name in ('local_agent_bridge', 'agent_benchmark'))]; sys.path[:0] = ['modules/agent_benchmark', 'modules/local_agent_bridge']; import pytest; raise SystemExit(pytest.main(['modules/agent_benchmark/tests/tool_profile_test.py', 'modules/agent_benchmark/tests/bridge_test.py', 'modules/agent_benchmark/tests/attempt_test.py', 'modules/agent_benchmark/tests/evidence_test.py', 'modules/agent_benchmark/tests/comparison_conditions_test.py', '-q', '-rs', '--basetemp=C:/Windows/Temp/agent-benchmark-b3-focused-final', '--tb=short']))"`.
- Remaining benchmark unit suite, excluding `diagnostic_test.py` and `runner_test.py` because these exercise installed OpenCode/MCP runtime integration on this host: **327 passed, 3 skipped**; all three skips are Windows symlink privileges. Exact command: `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if not any(name in getattr(x, '__module__', '') for name in ('local_agent_bridge', 'agent_benchmark'))]; sys.path[:0] = ['modules/agent_benchmark', 'modules/local_agent_bridge']; import pytest; raise SystemExit(pytest.main(['modules/agent_benchmark/tests', '--ignore=modules/agent_benchmark/tests/diagnostic_test.py', '--ignore=modules/agent_benchmark/tests/runner_test.py', '-q', '-rs', '--basetemp=C:/Windows/Temp/agent-benchmark-b3-unit-final', '--tb=short']))"`.
- The first broad benchmark run exposed and then verified the fix for a regression where file-only and lexical-only profiles were incorrectly required to have structural tools. `validate_file_agent` now enforces only the exact profile's required tools. Broad diagnostic/runner tests were not rerun because they launch subprocesses that contact the already-running OpenCode/MCP path; their first captured outputs showed refusal before model transition/dispatch. The integration behavior is therefore not verified here.
- `ruff check` across all changed Python files: **All checks passed**. `git diff --check`: **passed**.
- Static serialized module-export JSON for `[ {name, description, args}, ... ]` measured **442 UTF-8 bytes** for the two structural tool definitions together and **1,157 bytes** for all four lexical plus structural definitions. This is definition-shape byte sizing, not tokenizer tokens or the complete provider request.
- Setup, saved-plan replay, adapter argv/output bounds, structural profile identity and default-deny checks are included in the suites above. No model request, inference, OpenCode server operation, or live benchmark was performed. Controlled B0/B2/B3/B4 comparisons remain unmeasured; no efficiency gain is claimed.

## Validation phase — 2026-10-29

### Verified repository and scope

- Worktree: `C:\Users\mcarls\.codex\worktrees\d253\scripts`.
- Branch: `codex/local-agent-efficiency-20261025`; HEAD and upstream: `ba58ad0d91d7344e72e24a63d277eba7a270d52f` (`Record B3 structural retrieval completion`). Baseline: `92c5f068fe2d0c8c99ca4a14991388b1819a3764`.
- The branch is unchanged from `origin/codex/local-agent-efficiency-20261025` at HEAD. No commit, push, merge, rebase, reset, or cleanup was performed.
- Working changes at handoff: `HANDOFF-VALIDATION.md` (new); `modules/local_agent_bridge/local_agent_bridge/retrieval/{core.py,structure.py}`; `modules/local_agent_bridge/tests/{retrieval_test.py,structure_test.py}`; `modules/agent_benchmark/agent_benchmark/runner.py`; `modules/agent_benchmark/tests/runner_test.py`. These implementation/test edits were already present when validation resumed; this pass reviewed and verified them.
- Installed source versions: `local-agent-bridge` 3.4.0 and `agent-benchmark` 1.17.0. The source tree implements P0–P6: bounded lexical retrieval/CLI, optional OpenCode tools and default-deny benchmark profiles, durable checkpoints, Python AST symbols/maps, optional checkpoint-aware compaction, and a distinct `retrieval-structural-v1` profile. P1 remains satisfied by the v3.3.0 worker/task-envelope guidance; no prompt rewrite/B1 variant was introduced.
- Setup integration remains optional and receipt-managed. The benchmark roles reset permissions to `* = deny` and grant only the exact file/retrieval tools for the selected profile. No permissions were broadened.

### Independent review and fixes

A read-only independent review of `92c5f068..ba58ad0d` identified two Important findings; both now have regression tests and fixes in the current worktree:

1. **Regex CPU bound — fixed.** `modules/local_agent_bridge/local_agent_bridge/retrieval/core.py:24-26, 371-438, 556-560` previously let explicit regex mode evaluate backtracking patterns in-process without a time limit. It now caps query length at 4096 characters and evaluates regex in an isolated Python subprocess with a 2-second timeout, bounded input files/bytes, and explicit `regex_timeout` partial-result metadata. Tests cover worker argv/input, timeout, and a catastrophic-backtracking expression (`tests/retrieval_test.py:87-119`). This is an execution-time bound, not a regex-language restriction.
2. **Structural truncation metadata — fixed.** `modules/local_agent_bridge/local_agent_bridge/retrieval/structure.py:63-117, 141-164, 219-236` previously capped per-file definitions at `MAX_SYMBOLS_PER_FILE` without reporting that loss. `_definitions` now returns a truncation flag; `symbols` and `repository_map` propagate it to response metadata. Tests cover both APIs (`tests/structure_test.py`, symbol-cap cases).

The reviewer found no other Critical/Important defect in path containment, retrieval provenance/budgets, JS argv/no-shell adapters, setup ownership, checkpoint project/source identity, no-auto-resubmit recovery, default-deny benchmark profiles, or scope-audit design. That review was static; runtime installation/discovery is not thereby proven.

### Pinned OpenCode contract check

Read the tagged OpenCode 1.19.3 primary sources online. `ToolContext` includes the current `directory`, tool definitions use `description`, schema `args`, and `execute(args, context)`, and the registry discovers JS/TS files under tool directories and names default exports after the file. The pinned compaction hook accepts `{sessionID}` and `{context: string[], prompt?: string}`. This matches the file-based retrieval tools and optional checkpoint hook in the branch. Sources: [1.19.3 tool API](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/plugin/src/tool.ts), [custom tool discovery](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/tool/registry.ts), [compaction hook type](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/plugin/src/index.ts#L1405-L1424). This establishes source compatibility only; no OpenCode process was started in this validation pass.

### Offline validation reproduced after fixes

Environment: Windows PowerShell in the isolated worktree. Commands use the worktree module source (excluding ambient editable import finders) and a temporary directory under `C:/Windows/Temp`.

- Full bridge tests:
  `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if 'local_agent_bridge' not in getattr(x, '__module__', '')]; sys.path.insert(0, 'modules/local_agent_bridge'); import pytest; raise SystemExit(pytest.main(['modules/local_agent_bridge/tests', '-q', '-rs', '--basetemp=C:/Windows/Temp/local-agent-validation-final', '--tb=short', '--deselect=modules/local_agent_bridge/tests/audit_test.py::test_shell_mode_comes_from_receipt_modes_only']))"`
  Result: **155 passed, 2 skipped, 1 deselected** in 16.57s. The skips require Windows symlink creation/privilege. The deselected shell-mode test has the previously recorded Git Bash/MSYS app-execution-alias failure.
- Mocked/offline benchmark reconciliation tests:
  `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if not any(name in getattr(x, '__module__', '') for name in ('local_agent_bridge', 'agent_benchmark'))]; sys.path[:0] = ['modules/agent_benchmark', 'modules/local_agent_bridge']; import pytest; raise SystemExit(pytest.main(['modules/agent_benchmark/tests/runner_test.py::test_pending_reconciliation_failure_names_unresolved_worker', 'modules/agent_benchmark/tests/runner_test.py::test_real_adapter_project_gate_and_canonical_provenance_offline', '-q', '-rs', '--basetemp=C:/Windows/Temp/agent-benchmark-validation-focused', '--tb=short']))"`
  Result: **4 passed** in 2.37s; connector traffic was mocked.
- `ruff check modules/local_agent_bridge/local_agent_bridge/retrieval/core.py modules/local_agent_bridge/local_agent_bridge/retrieval/structure.py modules/local_agent_bridge/tests/retrieval_test.py modules/local_agent_bridge/tests/structure_test.py modules/agent_benchmark/agent_benchmark/runner.py modules/agent_benchmark/tests/runner_test.py` — **All checks passed**.
- `git diff --check` — **passed**. Git printed only LF-to-CRLF working-copy notices for four Python files.

The earlier selected benchmark groups (117 + 327 test executions, six skips across those groups and the then-149-test bridge run) were reproduced before these validation fixes; 117 is included in the 327 group, so 593 is not a unique-test count. The current broader benchmark suite was not rerun. A broad diagnostic/runner attempt reaches local OpenCode/MCP through subprocess recovery, and an automatic review rejected a subsequent broad command before tests started for that same service-contact risk. Do not count that rejected command as a test result. The narrow mocked regression tests above passed.

### OpenCode/MCP diagnosis

- `agent_benchmark/diagnostic.py:202` calls `reconcile_pending` before reserving/submitting its smoke trial. `agent_benchmark/runner.py:74-...` may contact the connected OpenCode bridge to reconcile exact pending session/job identity and confirm termination; this is necessary recovery behavior, not a model submission. Restart/refusal tests in `tests/diagnostic_test.py:143` and `tests/runner_test.py:53,177` launch subprocesses and therefore can contact the already-running local OpenCode/MCP endpoint even when the test's intended assertion is about safe refusal.
- The earlier broad attempt observed an OpenCode/MCP refusal before any new model transition or worker dispatch. This validation pass did not repeat that runtime contact. The attempted broad selection was blocked by automatic review before execution. A further test-fixture issue was that import-finder filtering in a parent Python process does not apply to subprocesses, which can select an ambient installed package rather than the worktree source.
- The unresolved-worker error now explicitly says the dispatch “remains unresolved”; a focused mocked connector regression test verifies that the pending receipt is preserved and names the unresolved state. This resolves the offline error-contract assertion only.
- **Classification:** mocked/offline reconciliation behavior resolved and tested; actual MCP initialization, pending-session reconciliation, and runtime tool discovery remain environment-dependent and unverified. No live worker or model request was made.

### B0/B2/B3 protocol and readiness

- **B0:** reliability v3.3.0 source baseline (`92c5f068...`) and `file-tools-v1`.
- **B2:** current bounded lexical retrieval implementation and `retrieval-files-v1` (`code_locate`, `code_context`).
- **B3:** B2 source plus `retrieval-structural-v1` (`code_symbols`, `code_map`). The optional tool definitions serialize to 442 UTF-8 bytes for the structural pair and 1,157 bytes for all four retrieval tools. These are JSON definition bytes, not tokenizer counts or provider payload measurements.
- Pin the same Qwen 27B Q4_K_M model identity, LM Studio/OpenCode versions, context, output limit, instructions, task seeds/prompts, hidden verifiers, scope policy, and 120-second task/15-second grace budget across conditions. Repository documentation describes the candidate as Q4_K_M with 32,768 context and 8,192 output; runtime identity and effective request settings have not been verified. Proposed harness versions are `agent-benchmark` 1.17.0, `local-agent-bridge` 3.4.0, and OpenCode 1.19.3. Record the resolved LM Studio modelKey/quantization, software SHAs, prompt hash, exact profile/permissions hash, runtime identity, context settings, and host state in each trial; stop if any differ. Do not load a model, alter limits, or transition models as part of validation.
- The current built-in task set contains only `py-grep-smoke` (`category: smoke`, `file-tools-v1`). It does not cover the requested bug-fix, repository-investigation, multi-file-change, and test-writing categories. **Gate B is not ready** until four fixed task fixtures plus trusted hidden verifiers exist and are checked into the trial source.
- There is also a comparison-contract blocker. `comparison_conditions.py:13-26` fingerprints each full task directory and stores its tool profile. `benchmark_core/compare.py:200-206` requires exact contract equality and suppresses numeric deltas when profiles differ. Therefore B0/B2/B3 cannot be compared by silently holding contracts equal or by treating a profile mismatch as noise. Add an explicit, predeclared intervention contract that permits only the intended tool-profile change while still enforcing same tasks/verifiers, model/runtime, context, scope, and budgets; then add offline tests proving allowed and disallowed differences. Until that exists, benchmark artifacts can be collected per profile but the canonical comparator will intentionally refuse a direct efficacy comparison.
- Once those two readiness items are resolved, use four matched categories, three repetitions per condition (36 worker dispatches total), and 12 task/repetition blocks; randomize the B0/B2/B3 order within blocks using seed `20261029`, balancing the six possible orders twice. Use `canonical-120s`, 15-second grace, 10-second bridge request timeout, 10-second verifier timeout, context 32,768, `--no-allow-model-transitions`, and a maximum 2-hour wall-clock gate. Stop on model/profile/context mismatch, any scope violation, an unresolved job, preflight refusal, memory ceiling, or 2-hour limit. Never retry an invalid/uncertain dispatch; retain it as invalid with evidence and stop if termination is uncertain.
- Record correctness/hidden verifier status, scope compliance, wall time, tool calls/failures, source reads and repeated reads, returned source bytes, input/output tokens, compaction count, and memory/GPU telemetry when available. Missing telemetry is null/unavailable, never zero. Invalid preflight/run attempts are excluded from efficacy summaries but retained and counted separately. Promotion remains subject to no correctness/scope regression and plan targets of at least 15% lower median wall time and 25% fewer repeated source reads across categories; no improvement is claimed until then.

### Separate authorization proposals

**Gate A — one live runtime smoke, not B0/B2/B3 approval.** Proposed command from the module environment (run only after the user separately authorizes it and read-only preflight confirms the exact model identity):

```powershell
python -m agent_benchmark smoke -x -m qwen38_23GB -p lmstudio -a local-worker -u http://127.0.0.1:4096 -q 10 -o .\reports\integration-acceptance\local-agent-efficiency-gate-a
```

Uses the shared default dispatch-state directory, one diagnostic task/one possible worker dispatch, 60-second task budget, 10-second cancellation/confirmation grace, and 10-second per-request timeout; no retries, model load, setting change, or transition. The runtime modelKey must resolve exactly to the intended Qwen 27B Q4_K_M before dispatch. This smoke does not independently prove the provider's effective context/output payload, and its current harness exposes no hard cap on the number of underlying model completion turns; the bound is one task dispatch and the fixed 60-second observation budget. Stop before dispatch on any identity/config mismatch, active unresolved job, OpenCode/MCP refusal, scope uncertainty, or miner contention. No Gate A operation has been performed.

**Gate B — 36-run controlled B0/B2/B3 evaluation.** This is separate approval from Gate A and is **not yet ready for execution**. Once fixtures and the declared comparison-contract support above are complete, use the existing `agent-bench experiment run` per condition, with `-x`, the same exact modelKey, four category fixtures, `-r 3`, `-b canonical-120s`, `-c 32768`, `--no-allow-model-transitions`, a fixed random seed of `20261029`, and condition-specific output directories. The precise executable command lines must be generated from the checked-in task paths and final intervention-contract interface at that later readiness gate; do not guess or launch a placeholder command. Maximum 36 dispatches and 2 hours total; 120-second task budget plus 15-second grace; stop conditions and invalid-attempt handling are as specified above. Gate A approval does not approve Gate B.

### Continuation point

Next, keep all validation work in this isolated branch and preserve the current uncommitted changes. The first implementation action is to add the four matched benchmark fixtures/verifiers and design/test the explicit intervention comparison contract with `benchmark_core`; rerun safe offline tests. Only after those gates pass should the exact Gate B command set be prepared for separate user authorization. Then request separate authorization for Gate A if runtime smoke remains useful. No inference, model load/reload, OpenCode session, benchmark trial, commit, or push was performed in this validation pass.

## Benchmark preparation phase — 2026-10-29

### Implementation

- Repository/worktree/branch remain `C:\Users\mcarls\.codex\worktrees\d253\scripts`, `codex/local-agent-efficiency-20261025`; HEAD remains `ba58ad0d91d7344e72e24a63d277eba7a270d52f`. No branch operation or commit/push occurred; validation-phase uncommitted work was preserved.
- Reused the task loader, isolated Git workspaces, hidden verifier runner, scope audit, `ExperimentScheduler`, and `benchmark_core.compare_runs`. No framework, service, or runtime dependency was added.
- Added four fixed offline fixtures: `py-repository-investigation`, `py-focused-bug-fix`, `py-multifile-change`, `py-test-development`. Their manifests have narrow allowed paths, 120-second task budgets, and independent hidden verifiers. Each test starts from identical seed bytes across B0/B2/B3; tests verify seed rejection/reference solution acceptance and temporary-directory isolation.
- Added additive `experiment run --tool-profile {file-tools-v1,retrieval-files-v1,retrieval-structural-v1}`. B0/B2/B3 now share the `benchmark-files` role, identical role prompt and identical task prompt; only the default-deny allowed tool surface changes. Existing single-run commands and permission/scope behavior are unchanged.
- `benchmark_core.compare_runs` remains exact-match by default. New opt-in `declared-tool-intervention-v1` permits only exact B0/B2/B3 execution profile, allowed tool list, and permission digest differences. It still requires equal task and verifier digests, suite fingerprints, worker role and prompt hash, exact LM Studio identity/quantization, and complete matched model settings. Missing or mismatched provenance returns an explicit refusal reason and suppresses all metric deltas.
- Package versions: `benchmark_core 0.2.0`, `agent_benchmark 1.18.0`. No dependency added.

### Reproducible experiment

- Added `modules/agent_benchmark/experiments/local_agent_efficiency_b0_b2_b3.json` and dry-run-first `local_agent_efficiency.py`. The seed-`20261029` schedule shuffles 12 task/repetition blocks and uses each of the six B0/B2/B3 orders twice, for 36 one-dispatch calls. Each call uses one fixture, one repetition, exact profile, `canonical-120s` (120-second task + 15-second grace), context 32768, RAM ceiling 95%, no model transitions. The launcher has a 7200-second outer cap, stops at first failed/nonzero attempt, and never retries.
- Executed the default dry-run only (no `--execute`): **36 commands, 12 blocks, all six condition orders, `execute=false`**. It resolved all four fixture paths. No run or worker was dispatched.
- Primary outcomes: hidden verifier correctness, scope compliance, elapsed time, failure/timeout/invalid outcome. Raw invalid attempts remain evidence and are excluded from efficacy summaries; the schedule stops rather than retrying. Secondary read counts, repeated reads, tool calls, retrieved bytes, tokens, compactions and resource data remain null/unavailable if runtime telemetry omits them, never zero-filled.

### Offline validation

Environment: Windows PowerShell, Python 3.12. Source imports were directed to this worktree. These tests use local fixtures and mocked bridge transport; runtime-facing diagnostic/runner tests were excluded because they can contact OpenCode/MCP.

- Focused agent-benchmark selection: **125 passed, 1 skipped** (Windows symlink privilege). Exact command:
  `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if not any(name in getattr(x, '__module__', '') for name in ('local_agent_bridge', 'agent_benchmark', 'benchmark_core'))]; sys.path[:0] = ['modules/agent_benchmark', 'modules/local_agent_bridge', 'modules/benchmark_core']; import pytest; raise SystemExit(pytest.main(['modules/agent_benchmark/tests/efficiency_fixtures_test.py', 'modules/agent_benchmark/tests/efficiency_experiment_test.py', 'modules/agent_benchmark/tests/tool_profile_test.py', 'modules/agent_benchmark/tests/comparison_conditions_test.py', 'modules/agent_benchmark/tests/bridge_test.py', 'modules/agent_benchmark/tests/attempt_test.py', 'modules/agent_benchmark/tests/evidence_test.py', '-q', '-rs', '--basetemp=C:/Windows/Temp/efficiency-release-offline-v3', '--tb=short']))"`
- Full pure `benchmark_core` suite: **116 passed, 1 skipped** (historical report directory absent). Command from `modules/benchmark_core`:
  `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if 'benchmark_core' not in getattr(x, '__module__', '')]; sys.path.insert(0, '.'); import pytest; raise SystemExit(pytest.main(['tests', '-q', '-o', 'addopts=', '-rs', '--basetemp=.pytest_tmp_root/efficiency-benchmark-core-v3', '--tb=short']))"`
- Focused intervention comparison regressions: **2 passed**, covering B0/B2/B3 acceptance; refusal for missing settings/provenance, model/settings/task/verifier/prompt/tool mismatch; and retained strict default. Command from `modules/benchmark_core`:
  `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if 'benchmark_core' not in getattr(x, '__module__', '')]; sys.path.insert(0, '.'); import pytest; raise SystemExit(pytest.main(['tests/compare_test.py::test_compare_runs_allows_only_a_declared_tool_surface_intervention', 'tests/compare_test.py::test_compare_runs_rejects_undeclared_intervention_mismatches', '-q', '--basetemp=.pytest_tmp_root/efficiency-intervention-v8', '--tb=short']))"`
- `ruff check` on the changed Python source/tests: **All checks passed**. `git diff --check`: **passed**; only LF-to-CRLF working-copy notices.

### Historical readiness before final evidence audit — superseded below

- **Gate A: Blocked.** Exact LM Studio model key and effective 32768 context/8192 output have not been verified; do not guess the legacy OpenCode alias as a model key. Harness bounds one dispatch and a 60-second task/cancel window but cannot hard-cap all underlying completion turns. Pinned OpenCode 1.19.3's `agent.steps` appends a max-step instruction while leaving tools enabled, so it is not a hard provider-call cap. Title/summary/compaction may also call the model. No model inventory query, model request, or smoke was run.
- **Gate B: Blocked.** Fixtures, profile selection, schedule and the opt-in comparison contract pass offline tests. The current runtime evidence producer does not record effective output cap, temperature, top-p, reasoning, or provider-options fingerprint. The comparator therefore correctly rejects real cross-profile comparisons. Add and test source-verified settings capture, or retain the blocker if pinned runtime cannot expose those values. Do not execute the prepared launcher yet.
- **Gate A proposed preflight/command (not run):** from `modules/agent_benchmark`, query the read-only exact model inventory with `agent-bench models list -p lmstudio -u http://127.0.0.1:1234 --format json`; set `$ModelKey` only to the exact intended downloaded LM Studio `modelKey` and matching quantization. Verify the currently configured OpenCode alias without changing it using `local-agent model verify $ModelAlias -j -c 32768 -o 8192`; stop unless the output establishes the expected alias/model mapping and both limits. Proposed one-dispatch smoke: `python -m agent_benchmark smoke -x -m $ModelKey -p lmstudio -a local-worker -u http://127.0.0.1:4096 -q 10 -o .\reports\integration-acceptance\local-agent-efficiency-gate-a -s .\reports\integration-acceptance\state`. This proposes the harness's 60-second task budget, 10-second request timeout and 10-second cancellation/confirmation grace. Stop before dispatch for model/context/output mismatch, unresolved state, preflight refusal or resource contention; never retry. The command is not authorization and must not be run until Gate A is separately approved. It still cannot cap underlying completion turns, so Gate A remains blocked even after preflight unless that hard limit is added or otherwise verified.
- **Gate B proposed command (not run):** from `modules/agent_benchmark`, first inspect with `python -B experiments/local_agent_efficiency.py --model-key $ModelKey --output-root .\reports\local-agent-efficiency\runs --state-dir .\reports\local-agent-efficiency\state`; after settings provenance is complete and Gate B is separately approved, the execution command is the same command with `--execute`. It caps at 36 trials/two hours and halts on the first nonzero attempt. Gate A approval does not authorize this command.
- No OpenCode/MCP or LM Studio service contact, model inference/load/reload, Gate A, or Gate B occurred. Online inspection was limited to tagged OpenCode 1.19.3 source.
- Changed this phase: `modules/benchmark_core/{benchmark_core/__init__.py,benchmark_core/conditions.py,benchmark_core/compare.py,pyproject.toml,README.md,tests/compare_test.py}`; `modules/agent_benchmark/{agent_benchmark/__init__.py,agent_benchmark/attempt.py,agent_benchmark/bridge.py,agent_benchmark/cli.py,agent_benchmark/comparison_conditions.py,agent_benchmark/scheduler.py,agent_benchmark/tool_profile.py,pyproject.toml,README.md,experiments/local_agent_efficiency.py,experiments/local_agent_efficiency_b0_b2_b3.json,tests/comparison_conditions_test.py,tests/efficiency_experiment_test.py,tests/efficiency_fixtures_test.py,tests/tool_profile_test.py}`; plus the four new task fixture folders. Earlier retrieval/runner edits and original `HANDOFF.md` remain preserved.
- This interim assessment is superseded by **Final inference-configuration readiness** below, which records the new configured-only evidence and the pinned runtime limitation. No hard completion-turn enforcement was added.

## Final inference-configuration readiness — 2026-10-29

### Verification and minimal evidence change

- Reconfirmed worktree `C:\Users\mcarls\.codex\worktrees\d253\scripts`, branch `codex/local-agent-efficiency-20261025`, HEAD `ba58ad0d91d7344e72e24a63d277eba7a270d52f`. Existing validation edits were preserved. No commit, push, reset, or branch change occurred.
- Extended `OpenCodeBridge.preflight` to record `configured_inference_evidence` from its existing mocked/tested `/provider` and `/agent` reads. It records the provider/model IDs, provider model context/output limits, explicitly configured agent temperature/top-p/variant, available variant names, and source paths. Missing role/model values are marked `not_explicitly_configured`; arbitrary options are omitted to avoid copying sensitive values. The evidence explicitly says it is configuration-only and that effective settings are unavailable from this preflight.
- `runtime.json` receives this observation through the existing preflight result flow. `effective_model_settings` is still absent. `benchmark_core` and its intervention contract were not weakened or changed; a comparison still refuses incomplete settings evidence.

### Required setting evidence matrix

| Required value | Existing evidence / source | What remains unverified |
|---|---|---|
| Provider and runtime model ID | Bridge records the requested provider/model and checks the configured `/provider` inventory; the benchmark scheduler resolves the LM Studio downloaded model identity. | A live LM Studio preflight is required to confirm the exact downloaded and loaded `modelKey`; `/provider` alone does not prove a currently loaded model. |
| Quantization | Scheduler's model identity is derived from the downloaded LM Studio inventory and carried into lifecycle evidence. | Must be verified against the exact live model inventory/loaded state. OpenCode's provider model ID alone does not establish quantization. |
| Context window | Scheduler records the loaded model context; new bridge evidence records `/provider/.../limit/context` as a configured catalog limit. | The comparator additionally requires the effective request context. `/provider` and the configured limit do not prove that final value. |
| Output-token limit | New bridge evidence records `/provider/.../limit/output` as a configured catalog limit. | Effective `maxOutputTokens` depends on that model limit, `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` (or the pinned default), then `chat.params` plugin mutation. The benchmark preflight does not observe those final values. |
| Temperature and top-p | New evidence records explicit `/agent` values, or marks them not explicitly configured. | OpenCode may derive model-specific defaults; `chat.params` plugins may change the final values. Those effective values are not returned by current bridge preflight. |
| Reasoning configuration | New evidence records the configured agent variant and model variant names. | Effective provider/model/agent/variant options and plugin mutations are not exposed as final request options. Arbitrary option payloads are not copied. |
| Provider-options SHA-256 | Comparator requires the hash of the effective options. | No final options object or equivalent safe fingerprint is exposed through the bridge's read-only preflight API. A hash of merely configured options would mislabel it as effective and is not substituted. |

The comparator's exact required object remains `context`, `output`, `temperature`, `top_p`, `reasoning_effort`, and `options_sha256`. The tagged OpenCode 1.19.3 request-preparation code constructs these request parameters from runtime flags, provider/model/agent configuration, variants, and then the `chat.params` plugin hook. The preflight endpoints used by this bridge return role and model catalog data, not the finalized request object. The output cap is `min(model.limit.output, outputTokenMax)` (with a default of 32,000 when the runtime flag is not overridden), before the same plugin hook can mutate prepared parameters. No live runtime request was made in this phase.

### Gate A — not ready for worker dispatch

- Existing limits: one worker submission per fresh bridge/session; smoke task observation budget 60 seconds; 10-second HTTP/MCP request timeout; 10-second cancellation/termination-confirmation grace. On timeout/error the harness attempts cancellation and confirms termination; unresolved jobs retain their durable pending state and must not be retried. The diagnostic uses an isolated task workspace and does not transition/load a model.
- There is no harness output-token cap and no hard cap on underlying completion turns. OpenCode's configured `agent.steps` adds a maximum-step prompt but leaves tools available on that step; the pinned implementation also starts title and summary work and may compact. Wall-clock timeout plus cancellation is not a hard completion-turn cap.
- Proposed read-only preflight commands (not run; service contact requires separate authorization):

  ```powershell
  $ModelKey = "<exact LM Studio modelKey from the inventory output>"
  $ModelAlias = "<existing OpenCode model alias>"
  agent-bench models list -p lmstudio -u http://127.0.0.1:1234 --format json
  local-agent model verify $ModelAlias -j -c 32768 -o 8192
  ```

  Require the exact intended downloaded/loaded model ID and quantization, configured alias mapping, and context/output expectations. These commands still do not establish final request parameters after runtime flag and plugin processing. Stop before worker dispatch if exact effective settings cannot be established; do not treat the configured evidence as a pass.
- Proposed one-dispatch command (not run):

  ```powershell
  python -m agent_benchmark smoke -x -m $ModelKey -p lmstudio -a local-worker `
    -u http://127.0.0.1:4096 -q 10 `
    -o .\reports\integration-acceptance\local-agent-efficiency-gate-a `
    -s .\reports\integration-acceptance\local-agent-efficiency-state
  ```

  Gate A is **Blocked** until the required model and effective settings can be verified before dispatch, and the user decides whether the disclosed absence of a hard completion-turn cap is acceptable for this bounded smoke. This command is a proposal only and is not authorization.

### Gate B — not ready for comparison

- The intervention-aware comparator still requires verified provider/model identity and quantization plus all six equal effective settings. Present offline evidence proves the B0/B2/B3 contract and task/verifier matching, but not effective inference settings. It correctly refuses numeric cross-condition comparison.
- The four-task × three-condition × three-repetition schedule, seed `20261029`, 36 dispatch ceiling, 120-second task / 15-second grace, and two-hour outer limit are prepared. Raw attempts must be retained; invalid/timeout/unresolved attempts are not retried or included as valid efficacy observations; any stop condition halts the schedule. Missing telemetry remains unavailable, not zero.
- Executed non-dispatching inspection command in this phase with placeholder model key `offline-preflight-placeholder`:

  ```powershell
  python -B experiments/local_agent_efficiency.py --model-key offline-preflight-placeholder `
    --output-root .\reports\local-agent-efficiency\runs-dry-check `
    --state-dir .\reports\local-agent-efficiency\state-dry-check
  ```

  Output reported `dispatches=36`, `duration_cap_seconds=7200`, `execute=false`; this was schedule inspection only and ran no subprocess command. The eventual approved run uses the same checked-in script and real verified `$ModelKey`, then adds `--execute`.

  Proposed execution command after the evidence blocker is resolved and Gate B is separately authorized: append `--execute` to the command above. The launcher stops on the first failed/nonzero attempt, permits at most 36 dispatches, and has a 7,200-second cap. Stop on identity/settings/profile mismatch, scope violation, unresolved dispatch, preflight refusal, host memory stop, or outer time cap. Gate A approval does not authorize this command.
- Gate B is **Blocked** until effective settings evidence is produced for every trial and matches across conditions. The smallest presently verified runtime interface cannot provide that evidence. A runtime hook/instrumentation change would exceed this handoff's scope and requires separate approval.

### Offline validation performed in this phase

- Test-first regression: the new configured-evidence test failed before implementation with `KeyError: configured_inference_evidence`; after implementation, the focused bridge tests passed.
- `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if not any(name in getattr(x, '__module__', '') for name in ('local_agent_bridge', 'agent_benchmark', 'benchmark_core'))]; sys.path[:0] = ['modules/agent_benchmark', 'modules/local_agent_bridge', 'modules/benchmark_core']; import pytest; result=pytest.main(['modules/agent_benchmark/tests/bridge_test.py', 'modules/agent_benchmark/tests/comparison_conditions_test.py', 'modules/agent_benchmark/tests/efficiency_experiment_test.py', '-vv', '-s', '--basetemp=modules/agent_benchmark/.pytest_tmp_root/final-evidence-44-rerun', '--tb=short']); print('RESULT', result); raise SystemExit(result)` — **44 passed**. Worktree packages were selected by removing the ambient editable finders. Bridge tests use mocked transports; the dry-run test asserts no subprocess execution.
- `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if 'benchmark_core' not in getattr(x, '__module__', '')]; sys.path.insert(0, 'modules/benchmark_core'); import pytest; result=pytest.main(['modules/benchmark_core/tests/compare_test.py', '-vv', '-s', '-o', 'addopts=', '--basetemp=modules/benchmark_core/.pytest_tmp_root/final-evidence-compare-verbose-rerun', '--tb=short']); print('RESULT', result); raise SystemExit(result)` — **6 passed**. This selection includes valid declared intervention comparisons and fail-closed mismatches.
- `ruff check modules/agent_benchmark/agent_benchmark/bridge.py modules/agent_benchmark/tests/bridge_test.py` — **All checks passed**.
- `git diff --check` — **passed**; Git emitted only existing LF-to-CRLF working-copy notices.
- No OpenCode/MCP/LM Studio service contact, model request/load, worker dispatch, Gate A, or Gate B was performed.

### Continuation decision

This interim conclusion is superseded by the source-level capture-point review below.

## Finalized-request capture review — 2026-10-29

### Finding

- Pinned OpenCode 1.19.3 has a supported `chat.params` plugin hook. `LLMRequestPrep.prepare` first merges provider/model/agent/variant options and computes temperature, top-p, and `maxOutputTokens` using runtime flags, then invokes that hook with mutable parameter values. The hook type includes `temperature`, `topP`, `topK`, `maxOutputTokens`, and `options`. A callback can observe those values only after hooks that run before it.
- The hook's model/provider input can identify the selected OpenCode provider and model. Its model object contains catalog limits, including context; that is still OpenCode-prepared metadata, not proof that the inference provider accepted those values. LM Studio's loaded identity and quantization remain separate lifecycle evidence.
- `reasoning_effort` is provider-specific and is carried through `options` when configured; the hook does not expose it as a separate normalized field. A source adapter would need provider-specific extraction and a fingerprint of the remaining finalized options.
- The current benchmark process has no supported channel for obtaining a plugin's observation. `OpenCodeBridge` persists its own `/provider` and `/agent` preflight result before calling `dispatch`; it does not install a plugin, query plugin state, or receive request parameters from OpenCode session history.

### Why no capture code was added

- OpenCode invokes plugin hooks sequentially in loaded order, but the shared service's complete plugin set/order is not controlled by `agent_benchmark`. The v1.19.3 config loader appends project, home `.opencode`, optional config-directory, and other plugin origins through multiple sources. A project-local observer cannot be assumed to be the final `chat.params` hook; a later hook could still change the values.
- A project plugin would also need a new evidence return channel (for example, a sidecar file or local IPC) and benchmark-runner wiring. A workspace file can be visible to the worker and affect scope auditing; a local receiver adds a new service boundary. Neither is an existing clean bridge integration point. Capturing an earlier hook's values or hashing arbitrary options would produce misleading or potentially sensitive evidence.
- Therefore no finalized-request evidence mechanism was implemented. The existing configured-only observation remains explicitly distinct from `effective_model_settings`, and the comparator's missing/mismatch rejection is unchanged.

### Pinned source references

- [`session/llm/request.ts` (v1.19.3)](https://raw.githubusercontent.com/anomalyco/opencode/v1.19.3/packages/opencode/src/session/llm/request.ts): parameter merge/default preparation and `chat.params` call.
- [`provider/transform.ts` (v1.19.3)](https://raw.githubusercontent.com/anomalyco/opencode/v1.19.3/packages/opencode/src/provider/transform.ts): output-token cap, model defaults, and provider-specific transform helpers.
- [`packages/plugin/src/index.ts` (v1.19.3)](https://raw.githubusercontent.com/anomalyco/opencode/v1.19.3/packages/plugin/src/index.ts): supported `chat.params` hook type and fields.
- [`plugin/index.ts` (v1.19.3)](https://raw.githubusercontent.com/anomalyco/opencode/v1.19.3/packages/opencode/src/plugin/index.ts): hook callbacks execute sequentially in loaded order.
- [`config/config.ts` (v1.19.3)](https://raw.githubusercontent.com/anomalyco/opencode/v1.19.3/packages/opencode/src/config/config.ts) and [`config/paths.ts` (v1.19.3)](https://raw.githubusercontent.com/anomalyco/opencode/v1.19.3/packages/opencode/src/config/paths.ts): plugins can be merged/discovered from project, home, optional config, and managed sources; project scope alone does not establish final hook order.

### Readiness and next decision

- **Settings capturable at the supported hook:** selected OpenCode provider/model ID; OpenCode model context metadata; prepared output cap, temperature, top-p, and full options object. If loaded last, a custom plugin could observe these finalized OpenCode-prepared values. It would not prove provider acceptance.
- **Still unavailable as trustworthy existing evidence:** guaranteed post-all-plugin values in the current shared service; a stable export path to `runtime.json`; normalized reasoning effort and safe options fingerprint; provider-observed settings; exact loaded LM Studio identity/quantization without live inventory; and the absence/value of runtime overrides unless established by a live preflight.
- **Gate A: Blocked.** Effective settings are not verified before dispatch. The existing one-dispatch/60-second/10-second request/10-second cancellation-grace limits are not a hard completion-turn cap. `agent.steps` remains a prompt hint; no turn-cap code was added.
- **Gate B: Blocked.** The comparator still lacks complete per-run effective settings and exact runtime model identity/quantization. Its fail-closed behavior remains intact.
- **Smallest alternative:** a benchmark-scoped OpenCode process with an isolated, controlled plugin set, a last-loaded capture hook, and a per-attempt evidence sink integrated into `agent_benchmark`. This requires a separate implementation decision because it adds runtime orchestration/evidence transport beyond the existing shared-server bridge. Approval for this design would not authorize starting the process, contacting services, inference, Gate A, or Gate B.
- This phase changed documentation only: `modules/local_agent_bridge/docs/plans/20261025-agent-efficiency/STATUS.md`. No model inference/load, OpenCode/MCP or LM Studio service contact, worker dispatch, Gate A/B execution, commit, or push occurred.

### Offline validation for this review

- `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if not any(name in getattr(x, '__module__', '') for name in ('local_agent_bridge', 'agent_benchmark', 'benchmark_core'))]; sys.path[:0] = ['modules/agent_benchmark', 'modules/local_agent_bridge', 'modules/benchmark_core']; import pytest; result=pytest.main(['modules/agent_benchmark/tests/bridge_test.py', 'modules/agent_benchmark/tests/comparison_conditions_test.py', 'modules/agent_benchmark/tests/efficiency_experiment_test.py', '-vv', '-s', '--basetemp=modules/agent_benchmark/.pytest_tmp_root/final-capture-review-agent', '--tb=short']); print('RESULT', result); raise SystemExit(result)` — **44 passed**. All bridge HTTP is mocked; the dry-run test verifies no subprocess dispatch.
- `python -c "import sys; sys.meta_path[:] = [x for x in sys.meta_path if 'benchmark_core' not in getattr(x, '__module__', '')]; sys.path.insert(0, 'modules/benchmark_core'); import pytest; result=pytest.main(['modules/benchmark_core/tests/compare_test.py', '-vv', '-s', '-o', 'addopts=', '--basetemp=modules/benchmark_core/.pytest_tmp_root/final-capture-review-compare', '--tb=short']); print('RESULT', result); raise SystemExit(result)` — **6 passed**, including the declared B0/B2/B3 comparison and fail-closed mismatch tests.
- `ruff check modules/agent_benchmark/agent_benchmark/bridge.py modules/agent_benchmark/tests/bridge_test.py modules/agent_benchmark/tests/comparison_conditions_test.py` — **All checks passed**.
- `git diff --check` — **passed**; only LF-to-CRLF working-copy notices were emitted.

### Implementation closeout — 2026-10-29

The implementation phase is complete. The branch contains bounded lexical and structural retrieval, optional OpenCode tools/checkpoint and compaction support, four matched benchmark fixtures, B0/B2/B3 profiles, the declared intervention comparison contract, and the dry-run-first 36-dispatch schedule. No performance improvement is claimed.

Final focused offline verification in the feature worktree:

- Benchmark fixtures, experiment schedule, profiles, comparison conditions, mocked bridge, attempt, and evidence tests: **127 passed, 1 skipped**. The skip is Windows symlink privilege unavailable. No live runtime was contacted; bridge transport is mocked and dry-run tests assert no dispatch.
- `modules/benchmark_core/tests/compare_test.py`: **6 passed**.
- Ruff on the affected agent-benchmark, benchmark-core, retrieval, and regression-test paths: **All checks passed**.
- `git diff --check`: passed before staging; only existing LF-to-CRLF notices were observed.

Accepted limitations remain: OpenCode/MCP integration and model inference have not been tested live; effective request settings and exact loaded model identity/quantization are not proven by the shared-server bridge; the comparator rejects incomplete runtime evidence; OpenCode 1.19.3 `agent.steps` is not a hard completion-turn cap. Gate A and Gate B remain blocked and unexecuted. Any live smoke or 36-dispatch benchmark requires separate authorization. No model was loaded, no service contacted, and no worker was dispatched.