# agent_benchmark handoff — Phase 1d non-inference acceptance checkpoint

## Current acceptance — 2026-10-19

User-authorized non-inference acceptance on HEAD 90b0e552 passed real OpenCode 1.19.3 directory/worktree/project validation and two persisted empty-session bindings. Distinct projects: cd6e7662a4835e98004521cdcbf6a4c05ca6f2c7 and 81c49b24fc18e7a94a4984c08291cb099e688983. Eight incorrect-binding checks rejected; no inference. Both sessions were confirmed empty/idle/childless, deleted, and returned 404 afterward. Prepared workspaces and byte-identical S0/S1 archives remain for review. Shared pending state absent and unchanged; all 59 historical files unchanged.

Evidence: reports/20261019T141839Z-phase1d-api-af4085b5/ACCEPTANCE.md, acceptance.json, config-inspection.json and validation-summary.json. Focused regressions: 49 passed; acceptance-only mocked empty-session faults: 3 passed (lost response, malformed response, persisted mismatch, cleanup and fresh-process state). No production implementation changes or new commit in this acceptance; only current documentation and new untracked evidence.

Configuration inspection found identical effective configurations and global agent-file provenance across trials. Generated system-prompt inheritance remains UNVERIFIED because no prompt was submitted. Global ~/.claude/CLAUDE.md remains a candidate dependency; runtime local-worker permissions explicitly allow shared Temp/opencode/*. Logical isolation does not remove that permission or alter strict scope policy. No services were reconfigured. The complete prepared-session MCP inference path requires separate live-worker authorization. Stop here; no Qwen trial or suite expansion.

## Workspace / commits

- C:/Users/mcarls/src/scripts-agent-benchmark; branch agent/agent-benchmark. Local commits only.
- Baseline 4b445d44: canonical Markdown missing-telemetry correction. P1 fixes 3560770b and a16d6194 preserved, along with Gemini's 91d9d26b scope audit.
- 8a94f580: independent trial-local Git repositories and unique root commits, source snapshot filtering and protected Git mutation audit. Package 1.1.0; task/verifier suite 0.1.1 unchanged.
- 15efb1dc72eca0a7ef2f28e261b85cb49ab6bb61: header-only routing, exact project/root-commit validation, validated empty-session creation before MCP inference, project-bound reconciliation/cleanup and provenance.
- Complete corrected core history through a1856215 remains integrated; no benchmark_core source changes in Phase 1d.

## Prior offline implementation checkpoint

Phase 1d is implemented and validated offline only. No live worker or live local API probe was run in this phase. No shared services or historical artifacts were changed. Stop for review and separately authorized non-inference API verification; do not start suite expansion or another model run.

Preserved live evidence:
- reports/20261019T114143Z-dfd3bbc9: one canonical timed_out result; hidden verifier passed. Later read-only scope re-audit detects 1 external violation; original snapshot-only count stays unchanged.
- reports/20261019T124653Z-87d660d8: one canonical failed result for 1 external scope violation; 22 hidden checks passed; worker duration 48.641 seconds. Four mutation events and five unverifiable shell operations remain distinct. ACCEPTANCE.md and acceptance-audit.json retain details.
- All 59 historical files retain digest 4560c4d9b3b0c3a8d0865f57d3e0d6e9a043e46054ce10507e8645d179baa3fb. Keep reports/ untracked and preserve both worker workspaces until user review. Neither run validates Phase 1d.

## Phase 1d interfaces and guarantees

- git_workspace.initialize_git -> GitIdentity; prepare_workspace returns it before S0. A UUID-bearing root commit ensures distinct IDs even with identical seeds and workspace basenames. Git environment/config/templates/hooks cannot redirect initialization; no remotes or host Git config writes. Real Git tests establish local root uniqueness and byte-identical task snapshots.
- preflight(..., project_id=expected_root_commit) validates model/role, GET /path directory+worktree, and GET /project/current vcs=git, worktree and exact expected project ID. It rejects global, other projects, ancestor/relative/missing directories before session creation.
- prepare_session creates one empty session via HTTP, verifies its persisted directory/projectID/ID and empty/idle state. The supported MCP sessionId argument binds the one subsequent opencode_fire submission to that session. Creation and inference are never retried. Failure to validate prevents inference; uncertain prompt submission still blocks later invocations.
- Direct HTTP uses x-opencode-directory only, matching both pinned OpenCode routers. Unit tests verify headers and absence of query conflicts. Real endpoint behavior remains unprobed in this phase.
- WorkerHandle.project_id is populated for new trials and retained in lifecycle/details. Fresh observation/cancellation rejects project rebinding. Cleanup loads/checks the recorded project; older pre-isolation evidence remains readable through its legacy path/session checks.
- Root .git bookkeeping is pruned from task-content snapshots; nested .git-named paths remain observable. Explicit worker .git writes are known violations, not automatically compliant. Shell uncertainty/scoring is unchanged. Windows read-only Git files are writable/deletable only inside owned .git after confirmed termination; shared processes are never managed.
- Canonical provenance: RunInfo benchmark_version/isolation_policy, runtime git/project/session, lifecycle Git identity/handle, session-preflight evidence, and TrialResult.details.project_id. Policy `isolated-git-project-v1` distinguishes this environment from prior runs. Do not pool old/new environments implicitly.
- Global OpenCode instructions/configuration/permissions remain; project isolation is not OS sandboxing. The benchmark lock does not exclude unrelated shared-service clients.

## Interfaces and corrections to preserve

- `DispatchGuard.submission_started` is set immediately before dispatch in `attempt.run_attempt`; runner reservation release uses this independent fact, never receipt emptiness. It remains true throughout an attempt. Empty/malformed receipts, transport failures, or lost receipts after possible submission keep pending.json and block later processes/output directories. Known receipt fields are merged with the initial uncertainty marker.
- Lifecycle ownership is journaled before secondary dispatch.json evidence, retaining job/session/message IDs if that secondary write fails. Total storage failure still cannot guarantee evidence persistence; the pre-existing durable pending reservation must remain blocking.
- `evidence.verify` requires both exit zero and a fresh completion.json receipt with matching nonce, status passed and a positive integer checks_completed. It passes AGENT_BENCH_COMPLETION_PATH and AGENT_BENCH_VERIFICATION_NONCE through the child environment. New verifiers must write that receipt only after all assertions pass. Diagnostic stdout, including a printed PASS, is not completion evidence.
- py-grep-smoke catches BaseException specifically at submitted-module import and submitted-function call boundaries, classifying SystemExit/KeyboardInterrupt as incorrect implementation. Abrupt os._exit(0) yields infrastructure_error for missing completion evidence; it cannot pass. This remains trusted-fixture process isolation, not a sandbox against deliberate receipt forgery or arbitrary hostile code.
- Smoke suite version is now 0.1.1 because the verifier contract changed. Historical 0.1.0 artifacts stay unchanged. Default task budget remains 60 seconds; cancellation grace remains 10 seconds. Do not pool different suite versions implicitly.
- `ScopeAudit.to_dict()` retains separate snapshot_violations/transcript_violations and adds compliance: compliant, violated, or uncertain. Relative tool working directories resolve against worker workspace. Failed/non-completed mutations are uncertain because partial writes are possible. Missing/malformed transcripts are uncertain. OpenCode StructuredOutput is a completion-report tool, not opaque filesystem execution.
- `results.trial_from_attempt` continues to use frozen S1 only. Known scope violations fail a verifier-passing attempt, but never overwrite earlier infrastructure_error or expired task timed_out. With only unverifiable scope operations or missing scope audit, a verifier-passing attempt becomes unscored; worker_first_pass and scope_compliance remain unavailable. Known verifier failures remain failed even when scope is uncertain. Known violations set scope_compliance=0. Violation counts are known detections, not a claim of exhaustive coverage.
- Failed S1/corrected S3 canonical persistence regression still passes. Cleanup never changes scores and still requires fresh exact session/turn/tool reconciliation within a bounded deadline. No shared-process termination or general scheduler exists.
- benchmark_core exclusively owns RunInfo, TrialResult, MetricValue, persistence, statistics and reporting. No core source changes in this pass. Tokens/tool telemetry remain unavailable when not collected.

## Validation and known limitations

175 agent tests passed; 2 Windows symlink-privilege skips. Core: 83 passed. Ruff clean. Configured core Mypy clean (9 files); new Git helper Mypy clean. Exact commands and RED/GREEN coverage are in docs/plans/20261019-implementation/phase1d.md.

Optional full agent Mypy reports 22 existing diagnostics (Windows fcntl stubs, dynamic core wrapper exports, legacy parser/CLI annotations); a baseline shadow-file check at 4b445d44 reports 27. Agent-wide typing is not clean. No unrelated typing refactor was included.

The proposed scratch policy and functional/scoring decomposition remain unimplemented by explicit Phase 1d scope. Strict scope uncertainty still prevents a full-success score. Current task/grace defaults remain 60/10 seconds.

## Next action / model handoff

Sol Medium should retain ownership through a separately authorized non-inference API probe. See the Phase 1d plan's probe matrix: fresh control/committed directories, header-routed /path and /project/current, and explicitly authorized empty-session POST/GET validation without any inference. Runtime schema deviations return to Sol; do not weaken checks to make a probe pass. A later live-worker run needs separate authorization.

After that checkpoint, Gemini Flash may handle routine fixtures only when the user directs it; Luna High may handle bounded audits. No local development-agent delegation or model router. Preserve P1 safety, S1 attribution, canonical contracts and reports/. Do not implement scratch/scoring changes or suite expansion without another instruction.
