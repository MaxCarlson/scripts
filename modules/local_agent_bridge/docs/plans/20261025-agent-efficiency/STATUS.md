# Local Coding-Agent Efficiency — Status

**Last updated:** 2026-10-25
**Overall state:** P0/P1 reconciled; Release A and P3–P6 implemented and offline-verified; B3 structural tool/profile wiring is implemented and offline-verified; controlled evaluation remains pending authorization
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
