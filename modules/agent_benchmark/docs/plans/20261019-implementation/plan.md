# agent_benchmark implementation plan

**Goal:** Independently score local coding workers, preserving first-attempt evidence, then compare coordinator workflows in a later milestone.
**Architecture:** Thin evaluator around installed opencode-mcp 3.0.0 / OpenCode; benchmark_core exclusively owns RunInfo, TrialResult, MetricValue, persistence, aggregation and reports. Sequential implementation in this worktree, with explicit manual model handoffs.
**Tech stack:** Python >=3.12, pytest, existing OpenCode/MCP interfaces.
**Spec:** User-supplied consolidated plan and final termination/cleanup amendment, 2026-10-19. Amendment wins. No local-agent delegation, per subsequent user instruction.
**Execution:** Inline by current implementing agent. Small tested local commits authorized by the user's handoff protocol; no push or merge.

## Verified repository findings

- Worktree C:/Users/mcarls/src/scripts-agent-benchmark; branch agent/agent-benchmark; base 46768a8d. Initially clean. Other agent owns ../scripts-benchmark-core.
- local_agent_bridge 3.0.0 configures runtime/profiles; it is not a Python job client. cli.py pins opencode-mcp@3.0.0. Reuse supported execution APIs, do not wrap the model loader as an execution client.
- Installed OpenCode 1.19.3; lms CLI commit dcefd5a; Python 3.12.10. MCP setup reported server unreachable. No inference dispatched. Do not claim a real-run milestone.
- Installed opencode-mcp dist/jobs.js: start persists job/session/message IDs before prompt_async; observe correlates assistant parentID; completed tool steps alone do not end a turn.
- cancel() sets cached status cancelled immediately after POST /session/{id}/abort. Terminal job records are cached. Thus job_get/check cancellation status cannot prove execution termination.
- Supported fresh surfaces: OpenCode GET /session/status and GET /session/{id}/message (or fresh session-correlated bridge observations). Adapter must corroborate idle + finished matching turn + no running tools. Missing messages, errors, uncorrelated or stale evidence mean unresolved. Session cancellation is session-wide; one fresh session per repetition.
- Worker/reviewer roles are tool permission profiles, not OS security sandboxes. Verifiers stay outside worker workspace; run against frozen S1 in a separate unprivileged process. Trusted offline tasks only, deny background child spawning in task instructions.
- Shared result contract absent at branch base. Do not invent stand-ins. Incorporate Gemini's tested Gate 1 SHA only when explicitly identified as tested.
- Ordinary tests use pytest and suffix *_test.py. Keep temporary roots under this module. No MCP Python client installed in current venv; choose minimal supported MCP transport during Phase 1c, not a new bridge.

## Model allocation and handoff boundaries

Switching means the agent implementing this repository, never local worker delegation. Models work sequentially; record tested commit, exact interfaces, checks, constraints and next action in docs/HANDOFF.md before each switch. User performs manual switch. No automated router. No expensive routine implementation after a package is sufficiently specified.

| Package | Objective / deliverables | Dependencies / interfaces | Model / reasoning | Acceptance and switch down | Switch back condition |
|---|---|---|---|---|---|
| 0 / 1a | Reconnaissance, lifecycle safety, fresh workspace and cleanup guards | Async LifecycleBridge cancel/observe; frozen handles and decisions, no core types | Codex 6.1 Sol Medium; architecture | Mocked observation vs cancellation, bounded deadlines, unresolved dispatch halt, retained diagnostics, owned cleanup retries; then handoff | Cancellation semantics or ownership ambiguity |
| 1b | Equivalent small grep fixture and hidden verifier, not yet imported Aider content | task.json, instruction.md, seed/, verifier/; contract below | Gemini Flash; deterministic implementation | Seed fails; reference solution passes; protected paths and verifier timeout tested; handoff to Sol | Verifier isolation or contract change needed |
| 1c | Supported bridge adapter, S0/S1 evidence, first canonical result and real worker run | Tested benchmark_core Gate 1 SHA; reachable runtime; lifecycle from 1a and fixture 1b | Codex 6.1 Sol Medium; integration | Real worker S0/S1, failed S1 remains failed after S3 repair; exactly one TrialResult; then handoff | Unknown submission, async/tool lifecycle ambiguity |
| 2a | Six more tasks for initial seven-task suite, pinned source revisions/licenses | Stable manifest/verifier contract established in 1c | Gemini Flash; fixtures/tests/docs | Known-good/bad solution tests, missing-input behavior, reviewer no-shell; handoff | Task cannot be independently scored |
| 2b | Scope and worker-report auditing | Frozen S0/S1, known report schema | 6-Luna-High; moderate implementation | Added/deleted/protected file checks, inaccurate changed_paths, false success tests; handoff | Cross-module attribution or ambiguous evidence |
| 3 | Serial repetitions, variant metadata, measured telemetry, core reports | Actual session/token samples and core reporting API | 6-Luna-High; schema-driven | Fresh sessions/workspaces, one result/repetition, unavailable never zero, no overlapping counter sum; repeated real-model report | Runtime telemetry schema mismatch or unattributable counters |
| 4 | Forth/refactor/permission-resume; version freeze; difficult lifecycle failures | Stable seven-task suite and explicit permission input contract | Sol Medium for integration, Flash for fixtures | Full ten tasks, controlled permission resumption, amendment regression suite | Return from cheaper work before high-risk async integration |
| M2 | Coordinator-direct/delegated paired runs | Stable M1; supported coordinator control and attributable measurements | Codex 6.1 Sol Medium; architecture | Paired same seeds/tasks; S1 frozen before repairs, workflow_final_success separate, unavailable coordinator tokens explicit | Unresolved attribution remains Sol work |

Use Sol High only if an actual unresolved architectural/integration problem warrants escalation; it is not the default. Luna may implement 1b if fixture requirements outgrow Flash. Do not switch mid-investigation.

## Global constraints

- No modifications to benchmark_core, local_agent_bridge or unrelated modules. No local worker dispatch for development assistance.
- No provisional RunInfo/TrialResult/MetricValue or competing serialization/reporting engine.
- M1 scoring worker_first_attempt_full_success; M2 workflow_final_success with separate immutable worker score. One TrialResult per repetition.
- Monotonic durations; wall_ms ends after first verification. Later retry/repair costs separate. GPU trials serial, warm by default, run requires -x/--execute.
- Default cancellation/confirmation grace 10 seconds, configurable finite positive value; retain effective value in eventual run metadata and per-trial details.
- Abort acknowledgement alone is insufficient. Unresolved potentially active work stops further dispatch and preserves evidence/workspace/IDs. No shared service kills or PID-by-name logic.
- Filesystem cleanup is separate from evaluation; never overwrite a verified pass/fail with a cleanup error. Fresh workspace every trial.

## Review focus

1. Cached cancelled status masquerading as fresh termination evidence: 1a tests reject it.
2. Transport hangs or exceptions consuming confirmation budget: 1a tests bound cancellation and observation together.
3. Symlink/junction or mismatched workspace deletion: 1a tests refuse escape/mismatch; adapter never has process-kill capability.
4. S1 changing during verification/repair: 1c captures only after confirmed end; immutable evidence plus critical S1-fail/S3-pass regression.
5. Missing telemetry falsely converted to zero or double-counted: package 3 schema tests.

## Task 1a: bounded lifecycle foundation (current slice)

Files: agent_benchmark/lifecycle.py, tests/lifecycle_test.py; pyproject.toml and README.md. No CLI yet.
Interfaces: WorkerHandle(job_id, session_id, message_id, workspace); Observation(job_status, session_state, turn_finished, tools_running, correlated, diagnostic); LifecycleBridge.cancel(handle), observe(handle), both async; confirm_termination(..., grace_seconds=10, poll_seconds=0.1) -> TerminationDecision. Adapter observations MUST be fresh remote evidence, matching the exact session/message and all tools. Job status alone is diagnostic. Failed adapter observations are unresolved.
Workspace interfaces: DispatchGuard.allocate(root) -> OwnedWorkspace, record(decision); cleanup_workspace(workspace, decision, attempts=3, retry_seconds=0.05) -> CleanupOutcome. Guard latches unresolved decisions; no override in this release. Allocation creates a unique empty directory. Cleanup requires exact path ownership and confirmed termination, rejects links/escape, retries only lock-like errors; no process operations or evaluation writes.
- [x] Write failure-path tests first, run RED (missing module initially; review custom-transport regressions subsequently failed 2/2 before fix).
- [x] Implement smallest lifecycle and owned-workspace helpers; run GREEN (26 passed, 1 skipped).
- [x] Run module pytest and ruff; native read-only reviewer found custom adapter exception gap, fixed with RED/GREEN tests. Commit only owned paths.
- [x] Record first handoff to Flash (6-Luna-High also suitable) in docs/HANDOFF.md; stop here, even if core lands meanwhile.

## Task 1b: precise next-agent package (independent of core)

Files: tasks/py-grep-smoke/{task.json,instruction.md,seed/grep.py,verifier/check.py}, tests/fixture_test.py.
Use an original small grep-equivalent fixture (label smoke, not canonical imported py-grep). Worker implements grep(pattern: str, lines: list[str], ignore_case: bool=False) -> list[str], substring match, stable order, no regex. Seed raises NotImplementedError. Only grep.py editable; instruction/public tests protected. Default task budget 60 seconds. Manifest fields: task_id, suite_version, category, allowed_paths, forbidden_paths, time_budget_seconds, verifier. Paths are relative, no .. or absolute names. Verifier is coordinator-only and invoked as Python check.py FROZEN_WORKSPACE, exit 0 pass, 1 wrong solution, 2 verifier infrastructure error. Use deterministic stdlib tests, subprocess timeout, no runtime install. Verify empty strings, Unicode, case option, duplicates and order with a known-good test-only solution. No production reference answer, no generic fixture loader needed yet. No runtime/MCP calls, no result models, no changes to lifecycle without returning to Sol.
- [x] Seed fails, known-good passes; infrastructure and timeout failures distinguished.
- [x] Pin original fixture identity/version; no false upstream attribution. Source-import/licensing work belongs to 2a.
- [x] Commit, record handoff; stop for Sol integration and tested core Gate 1 SHA.

## Task 1c: end-to-end gate (return to Sol)

- [x] Obtain the complete corrected benchmark_core branch final tested SHA and validation from the user. Incorporate that exact complete branch, run focused tests; import canonical types. Do not integrate the earlier Gate 1 commit alone or an unapproved branch tip. Never inspect/edit another agent worktree.
- [x] Add supported MCP SDK adapter, fire without sessionId, preserve IDs/unknown submission and avoid resubmission. Fresh HTTP reconciliation bypasses terminal cache. Installed 3.0.0 schema/source and SDK signatures checked; transport tests use constructed schema-shaped fixtures, not captured live-session samples. Live validation pending.
- [x] Add bounded attempt observation distinct from cancellation grace, durable identifiers and unresolved diagnostics. Effective budgets in lifecycle evidence; canonical RunInfo metadata wiring pending core gate.
- [x] Add exclusive byte-exact S0/S1 snapshots/hashes, patch evidence, actual changed-path audit and disposable verification copy. Raw receipt/session and separate report evidence retained. Caller supplies evidence directory; canonical core evidence layout wiring pending gate.
- [x] Build exactly one canonical TrialResult per repetition; missing metrics unavailable. Prove S1 incorrect then S3 corrected leaves worker_first_pass false and status failed.
- [x] Add read-only plan and guarded run/status/cleanup CLI with paired short/long arguments; associated help-catalog entry required by repository CLI conventions added narrowly.
- [ ] Run real local model only when runtime reachable and explicitly executed; no loader configuration/service changes. Inspect actual roles/tool limits. No real run claimed if blocked.
- [ ] Freeze task/verifier contract after first real task; commit and hand off to Flash/Luna.

## Remaining acceptance packages

2a: Add book-store, multifile bug, small feature, missing input, review-only, timeout-continue; keep programming/behavior/bridge reporting separate. Import Aider revisions and original license notices; read task-specific license chain. Primary sources: https://github.com/Aider-AI/polyglot-benchmark (Exercism-derived), https://github.com/Aider-AI/refactor-benchmark, https://github.com/harbor-framework/harbor (task/verifier separation only, no dependency).
2b: Audit frozen filesystem against manifest; independent checks beat worker claims. Truthful blocked outcome only passes intentional-blocker tasks. Hidden verifier failures cannot become passes from self-report.
3: Selected tasks/variants, repetitions, ordering seed, runtime/model/context/reasoning configuration, tokens and tool telemetry. Canonical persistence/reports only; all-scored and success-only durations, missing data visible. Run actual repeated variants before M1 claim.
4: Full ten-task suite plus permission-resume, versions/revisions frozen, all amendment regressions including no workspace reuse after unresolved task. No process supervisor or GPU scheduler.
M2: Start grep/multifile/small-feature paired workflows, worker retry S2/coordinator repair S3 optional, compact evidence for each, later-stage costs separate. Explicitly document unavailable coordinator control or token attribution; no invented savings.


## Phase 1c execution update (2026-10-19)

The user explicitly gates core integration on their final corrected SHA and validation, still pending. Independent work proceeds first: evidence.py (task loading, byte snapshots, disposable verifier copy), bridge.py (official MCP SDK 1.30.x client, pinned cached bridge, fresh raw HTTP session/message reads), then attempt.py (execution evidence only, no replacement canonical result types). No live worker run or inference dispatch is authorized as development assistance. Any actual benchmark validation must be separately and explicitly executed and accurately reported.

Interface decisions: OpenCodeBridge.dispatch returns WorkerHandle; preflight verifies explicit connected lmstudio model/role without auto-start; observe corroborates session identity/directory, submitted user message, final assistant and tool status via raw HTTP. SDK transport uses OPENCODE_AUTO_SERVE=false and offline opencode-mcp@3.0.0. Snapshot is a frozen in-memory byte mapping plus exclusive archived directory; verification uses a disposable copy and checks archived hash before/after. Scope is measured from actual checkpoint paths. Directory isolation remains a trusted-fixture safeguard, not an OS sandbox.

Current independent component tests: 57 passed, 2 symlink-privilege skips; Ruff passed. New SDK dependency installed in active repository venv; unrelated pre-existing invalid-distribution pip warnings observed, no cleanup attempted. Initial un-elevated baseline hit sibling-worktree write denial; elevated focused run passed 37/1 baseline.


Independent flow update: attempt.run_attempt produces only frozen AttemptEvidence references (workspace, termination decision, snapshots, verification, scope facts and monotonic durations). It does not emit/serialize benchmark results or determine canonical status. Canonical adapter must map actual task-budget expiration separately from HTTP timeout/infrastructure failure, preserve uncertainty without verifier/S1, and never improve worker-first-attempt outcome after S3 repair. Worker workspace is retained by default. Core CLI/status/cleanup must inspect durable unresolved journals across invocations before dispatch; the existing DispatchGuard is batch-local. Evidence journaling failure still latches the in-memory guard before exception escapes. An uncooperative blocking transport is forbidden by the bridge protocol; actual transport cancellation remains a live validation item.

2026-10-19 checkpoint: 69 passed, 2 Windows symlink-privilege skips; Ruff clean. Read-only runtime readiness timed out (ConnectTimeout); no MCP worker/model invocation. No core branch integration performed. Stop and request user's final corrected core SHA + validation.


## Integrated Phase 1c checkpoint (2026-10-19)

User authorization supersedes earlier integration gate: merged full core history through exactly a1856215 via 072683f1, then fixed only reproduced import shadowing (f973ee67). Canonical pipeline/CLI at 5d9637b0; required narrow help registration at 2cfd66fd. Module version 1.0.0 for new console entry; core compatibility fix version 0.1.1. Built task now lives in agent_benchmark/tasks/py-grep-smoke (same fixture bytes, bundled package data), not the old module-root tasks/ directory.

Resource state uses one OS-held command lock and one durable unresolved receipt, not a scheduler/process manager. Default state location is stable across output directories; separate invocations must share it. Cleanup confirms fresh matching remote termination before removal and never alters canonical scores. Pre-dispatch preparation failures cannot strand active-worker blocking. Runtime-close cleanup errors are retained separately without rewriting a verified score. Exact workspace identity is checked before cleanup.

104 agent tests passed, 2 Windows symlink-privilege skips; 80 core tests passed, Ruff/Mypy clean; both wheel imports/bundled plan and installed console entry passed. Canonical failed-S1 / repaired-S3 reload regression passed. No actual worker execution was performed; running runtime, model ID and explicit execution authorization remain the live gate. Source-backed terminal semantics documented in docs/TERMINATION.md. Keep early gate notes above as execution history; STATUS.md and HANDOFF.md describe the current state.

Ruling: user request to implement the planned CLI includes its required associated help registration under REPO_LLM_INSTRUCTIONS.md; only one catalog entry and the owning module's synchronized version metadata were changed. No unrelated shared behavior changed. Ruling: source-proven terminal StructuredOutput with retained tool-calls is allowed only with matched requested schema and completed StructuredOutput part, plus idle session/completed timestamp/no unfinished tools; ambiguous structured data remains unconfirmed. Cost if wrong: conservative unresolved state blocks live acceptance rather than risking cleanup.
