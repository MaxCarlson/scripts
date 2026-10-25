# Local Coding-Agent Efficiency — Status

**Last updated:** 2026-10-25
**Overall state:** P0/P1 reconciled; Release A complete; P3 optional OpenCode adapter and auditable benchmark profile implemented and offline-verified; P4 review is next
**Verified baseline:** remote `main` merge commit `92c5f068fe2d0c8c99ca4a14991388b1819a3764`
**Performance branch:** `codex/local-agent-efficiency-20261025`
**Canonical plan:** `./plan.md`
**Execution handoff:** `./HANDOFF.md`

## Milestone tracker

- [x] P0 — Baseline and repository reconciliation
- [x] P1 — Worker instructions and task-envelope acceptance (satisfied by existing v3.3.0 implementation)
- [x] P2 — Bounded lexical retrieval core and CLI
- [x] P3 — OpenCode retrieval-tool integration (offline implementation; no live worker evaluation)
- [ ] P4 — Durable task checkpoints
- [ ] P5 — Structural outlines and repository maps
- [ ] P6 — Compaction-aware recovery
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

## Next action

Begin P4 with a read-only audit of v3.3.0 session/job recovery rules, `agent_memory`, `development_ledger`, and related persistence. Decide whether a project-scoped checkpoint adds authoritative task state that those components cannot preserve before implementing any new store. Keep checkpoint recovery from resubmitting uncertain work. Controlled evaluation of B0/B2 and actual tokenizer/context overhead remains pending separate live-evaluation authorization; current evidence is implementation and offline correctness only.
