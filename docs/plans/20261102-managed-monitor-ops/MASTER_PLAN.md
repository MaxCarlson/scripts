# Master Plan — Self-Managing LLM Monitor and Agent Benchmark

**Plan ID:** `20261102-managed-monitor-benchmark`  
**Date:** 2026-11-02  
**Repository:** [`MaxCarlson/scripts`](https://github.com/MaxCarlson/scripts)  
**Scope:** `modules/llm_monitor/`, `modules/agent_benchmark/`, limited reusable infrastructure in `modules/web_ui_tools/` and `modules/runmux/`, tests, operator documentation, and agent policy.  
**Status:** Planning deliverable only; no repository writes, service changes, inference runs, commits, or merges performed.  
**Last inspected GitHub main tree:** file search indexed at `234ae0a38721a1d0620044fb0c863a7269a39da3` (2026-11-02). Read-only connector inspection does **not** establish current local worktree state or whether an external agent has finished.

## Executive decision

Implement **one coordinated, phased initiative** that makes an authenticated, correctly configured, ready-to-use Monitor discoverable and safely manageable by Agent Benchmark. Preserve the existing `agent-bench suite` planning/execution split, Monitor gateway/recording guarantees, and browser access-code authentication. Invest in CLI and protocol correctness ahead of longer agent prompts.

**Architecture:** (1) reconcile currently active Monitor-stop work; (2) adopt Runmux's verified lifecycle patterns, not a new blind PID killer; (3) create a tightly permissioned, same-user **local control channel** for issuing short-lived, instance-bound, *read-only* Monitor API capabilities; (4) add a pure diagnostic engine with contextual failure classifications; (5) add bounded, opt-in local-service recovery to suite preflight; (6) qualify incident regressions and roll out concise agent policy. Keep host-facing API origin and Docker/container-facing gateway routing separate.

**Critical authorization boundaries:** `agent-bench suite plan` and `doctor` remain non-mutating by default; `-r/--recover-local` is explicit consent for a narrowly scoped managed-Monitor start (never Docker, LM Studio, or inference); `-x/--execute` remains the *only* inference-dispatch authorization. Restart/stop require direct operator invocation and verified ownership. No localhost authentication bypass and no fallback around Monitor when mandatory.

## Verified current repository evidence vs assumptions

The following are confirmed by read-only GitHub inspection on 2026-11-02; they are **not live host validation**:

| Component | Observed baseline | Consequence |
|---|---|---|
| `modules/llm_monitor/llm_monitor/cli.py` | `llm-monitor web` is currently a single foreground command accepting `-p`, `-e`, `--gateway`, `-R`, `-d`, etc.; its `main` calls `run_web(...)`. | A start/status/stop/restart subcommand migration needs backwards-compatibility tests and integration with any existing stop-command branch. |
| `modules/llm_monitor/llm_monitor/web.py` | `run_web` creates a startup code, server, recorder and gateway, then prints `"is listening"` **before** `server.run()`. | Readiness banner and service discovery are currently misleading under delayed/failing bind. |
| `modules/web_ui_tools/src/web_ui_tools/app.py` | `/auth/login` accepts JSON `{ "code": "..." }`, creates an HttpOnly, SameSite=Strict cookie; protected `/api/*` routes check session and same Origin/Host. | Do not weaken browser controls; avoid replaying login codes or exposing persistent cookies in benchmark artifacts. |
| `modules/agent_benchmark/agent_benchmark/suite_cli.py` | `suite list/plan/run/status/resume/report/archive` exist. `-F/--llm-friendly` already exists on many subcommands; `-x/--execute` gates inference. | Add `suite doctor` without changing existing flags. `doctor -F` can mean `--full` **only within doctor**, with explicit help to avoid confusion. |
| `modules/agent_benchmark/agent_benchmark/suite_monitor.py` | Preflight queries authenticated `/api/inference/v1/models`, `/status`, `/recording/status`, `/requests`; credentials can come from env or a `monitor_session.env` file. | Replace human-managed cookie bootstrap, retain compatibility temporarily, remove unsafe discovery only after migration and tests. |
| `modules/agent_benchmark/agent_benchmark/suite.py` | Immutable suite manifests, persistent checkpoint, background worker and monitor per-task checks already exist; `-x` is required to run/resume. | Extend rather than rewrite orchestration; preserve provenance and completed trials. |
| `modules/runmux/src/runmux/server_lifecycle.py` and its status ledger | Owner-scoped descriptor, PID+create-time validation, HMAC health/shutdown, replay defense, prebound socket, verified readiness, safe alien-listener handling. | Reuse established design boundaries and isolated helpers if practical; do not introduce unrelated process-termination logic. |
| Recent GitHub history | PR #20 integrates OpenCode v2; PR #16 describes monitor integration; latest searched commits include Monitor content/recorder fixes. | Active development is moving rapidly. Rebase on verified checkpoints; inspect open assignments and worktrees before editing. |

**Unverified:** whether the separately assigned `llm-monitor web stop` work is completed, merged, tested, or still in progress; whether local Windows/WSL/Docker/LM Studio services are running; the installed package versions and effective branch/worktree; behavior of any unpushed changes. The *Phase 00* gate resolves these before implementation.

## Non-goals

No automatic model loading, benchmark inference or scoring; no Docker installation/restart; no permission elevation or agent-sandbox escape; no unsolicited restart of a live Monitor with mismatched recording mode; no change to Harbor dataset revision, task ordering, adapter selection, OpenCode v2 qualified routing, or execution flags; no exposure of startup codes/tokens in `-F`/JSON/logs/manifests; no takeover of arbitrary localhost listeners; no production SQLite schema migration unless demonstrably required and backward-compatible. No work on Runmux supervised *user processes* or its browser UI.

## Target command surface (proposed; phase gate may preserve aliases)

```powershell
llm-monitor web start -p 8789 --gateway -R content -n
llm-monitor web status -p 8789 -f json
llm-monitor web stop -p 8789
llm-monitor web restart -p 8789 --gateway -R content -n
agent-bench suite doctor -F -f json
agent-bench suite plan -c aider-python-10 -a opencode-v2 -m openai/EXACT_MODEL -L -R content -F
agent-bench suite plan -c aider-python-10 -a opencode-v2 -m openai/EXACT_MODEL -L -R content -r
agent-bench suite run -c aider-python-10 -a opencode-v2 -m openai/EXACT_MODEL -L -R content -r -x
```

`EXACT_MODEL` is a placeholder, not a known model identifier. CLI documentation will provide both short and long forms of **new** options. `web stop`/`restart` act only after signature/ownership checks; explicit `-p` selects a host/port managed identity, not a PID. `suite doctor -F` is a proposal for `-F/--full` diagnostics and must not alter `-F/--llm-friendly` semantics on existing subcommands. Prefer `-f/--format {text,json}` as doctor-local output. Whether the active stop-command work has chosen slightly different command spellings must be reconciled before breaking interfaces.

### Target managed flow

```text
suite plan / run / resume
  -> classify host vs sandbox, selected gateway URL vs host management URL
  -> discover exact managed Monitor instance (descriptor + process creation time + HMAC challenge)
  -> optional authorized start if absent and configuration policy permits
  -> acquire ephemeral, scoped credential via same-user local control channel
  -> validate Host/Origin, model inventory, adapter API format, capture, recording mode, durability health
  -> emit sanitized preflight receipt with exact instance ID and config fingerprint
  -> plan returns without inference; run/resume dispatches only under -x
  -> revalidate before each task and after each task; preserve evidence on degradation
```

### Identity and readiness contract

* Bind managed identity to **OS user SID/UID, host, loopback port, opaque instance ID, exact process ID + create time, executable identity, and immutable configuration fingerprint**. Parent/child interpreter processes are *one* logical managed service if the verified listener instance matches; a separate listener needs its own valid identity.
* Write descriptors atomically under protected user-owned state, reject junctions/symlinks/reparse points, fail closed on uncertain permissions. Never treat descriptor existence alone as proof of liveness.
* Use a challenge-response against the exact bound service and verify signature/instance identity; a port probe alone is insufficient. Start status remains `starting` until the socket is bound **and** application lifespan, local control, and health checks report ready. No startup code in machine-readable output.
* Configuration is explicit: provider endpoint, gateway enablement/upstream, recording mode and database location, resolved host/container mapping; fingerprint must exclude secrets and volatile fields. On mismatch, report field-level diff; do not silently mutate running service.
* A managed `stop` requests graceful service shutdown with bounded drain, WAL/SQLite durability verification where applicable, and preservation of descriptor/evidence when shutdown cannot be proved. Never kill an unidentified PID, and never kill Docker, LM Studio, or independently supervised inference workers.

### Authentication design decision

**Recommended:** local-control credential issuance with explicit same-user OS access control and an application-scoped short-lived bearer token accepted **only** by an allowlisted read-only Monitor API set (`models`, `status`, `recording/status`, `requests`, specific recording/telemetry/history evidence endpoints). A Monitor-local token verifier retains tokens in memory, binds them to `instance_id`, scope, TTL, and optionally client/benchmark run correlation, and validates under a distinct auth mechanism from browser cookies. All API calls continue to check trusted Host/Origin and reject cross-origin traffic; no `127.0.0.1` blanket exemption. Refresh through the channel on 401 *at most once* after identity revalidation. Agent never handles cookies or login codes.

**Windows transport:** native named pipe with explicit current-user SID allowlist ACL, deny network logon/remote clients, bounded message framing, no pickle/deserialization, verified server identity, and replay-resistant request protocol. A bare `multiprocessing.connection.Listener(AF_PIPE)` does **not** by itself meet this ACL requirement. **POSIX:** owner-mode `0700` parent directory and `0600` Unix-domain socket (plus peer credentials where available). If the authorized host context has no access to this channel, classify `EXECUTION_CONTEXT_RESTRICTED`; do not fall back to unauthenticated web requests or permission bypasses. WSL2 Linux identity is not automatically equivalent to Windows host SID; a separately audited host-side adapter would be a future extension, not an implicit bridge.

**Alternative (if integration cost exceeds budget):** supervised process launch may pass an in-memory session to a child benchmark process, but only as an intermediate *same-process* workflow. It does not solve independent runs, reauthentication or supervisor restarts. Never persist session cookie in `monitor_session.env` for new workflows; plan compatibility and a documented cleanup/migration for existing users.

### Stable structured diagnostics (`monitor-preflight-v1`)

All diagnostics use deterministic, bounded fields with redacted errors and no secrets. Distinguish **absent**, **healthy**, **unhealthy**, **unreachable from this context**, **permission denied**, **authentication missing/expired**, and **configuration mismatch**. `unknown` is not equivalent to `down`. Example *schema shape*, not verified live output:

```json
{
  "schema_version": "monitor-preflight-v1",
  "status": "blocked",
  "execution_context": {"kind": "sandbox_restricted", "confidence": "observed", "evidence": ["LOCAL_SOCKET_PERMISSION_DENIED"]},
  "components": {
    "monitor": {"state": "unreachable", "error_code": "MONITOR_CONTROL_UNREACHABLE", "retryable": false},
    "docker": {"state": "permission_denied", "error_code": "DOCKER_PIPE_ACCESS_DENIED"},
    "lm_studio": {"state": "unverified", "error_code": "LOCAL_SOCKET_RESTRICTED"}
  },
  "recommended_action": "USE_APPROVED_HOST_CONTEXT",
  "recovery": {"attempted": false, "actions": []},
  "inference_dispatched": false
}
```

`confidence` reflects *what was observed*; do not label host health from sandbox-only evidence. Include monotonic elapsed timings, probe names, selected runtime/OS, provenance redaction, stable error code, and a concise operator action. Store no credentials or request content in diagnostics. Output contracts and typed error catalog are defined in Phases 03–04.

## Phase execution and dependency matrix

| Phase | Priority | Primary purpose | Dependency | Completion gate |
|---|---|---|---|---|
| **00 — Baseline & integration gate** | P0 | Check active assignments, exact branch/worktree, current CLI and security contracts; decide adoption of stop work | None | Agreed baseline and non-overlap ledger; no unverified assumption promoted to fact |
| **01 — Managed lifecycle** | P0 | Exact service identity, prebind/readiness, status/start/restart/safe stop | 00 and stop agent completed/clearly isolated | Safe ownership and startup/shutdown tests |
| **02 — Local control & auth bootstrap** | P0 | Protected pipe/socket, scoped ephemeral local API credential; browser auth intact | 01 | No manual login code/cookie under approved host; negative security tests |
| **03 — Doctor & structured errors** | P0/P1 | One-command environment diagnostics, host/context distinction and JSON schema | 00, ideally 01/02 for richer data | Diagnostic matrix and sanitized stable error vocabulary |
| **04 — Recoverable suite preflight** | P1 | Bounded state machine, explicit local recovery, checkpoint provenance | 01–03 | `plan` remains inference-free, `run/resume` require `-x` |
| **05 — Incident regression & reliability qualification** | P1 | Integration, concurrency, credentials, crash/SQLite, Windows host/WSL container scenarios | 01–04 | Matrix passes or platform limits explicitly evidenced |
| **06 — Agent instructions, release & integration** | P2 | Minimal policies, help/README, migration, review/merge handoff | 05 | Reviewed, merged when authorized, rollback documented |

**Team topology:** Single primary implementer in dependency order for Phases 01–04 is preferred to avoid cross-module clashes; isolated test/documentation ownership can run in parallel only after contracts freeze. Phase 00 must *not* duplicate or interrupt the stop-command agent. Phase 05 can parallelize per-disjoint test subtree, with one integrator owning shared files.

## Execution policy and Git coordination

1. **Before any mutation** capture `git status`, `git worktree list --porcelain`, branch tracking refs, active PRs/agent checkpoints, latest validated SHA, untracked evidence, dependencies, and state of the in-flight stop work. Favor finishing/integrating existing work first.
2. **Branch from validated checkpoint**, not blindly from `main`. Do not overwrite ongoing branches or touch live worktrees belonging to an active agent. If stop work remains active, Phase 01 waits; Phase 03 pure design/tests may proceed on isolated files only if dependency and non-overlap are proven.
3. Treat Git sandbox failures as environmental; document a known-safe host Git strategy (or separate published checkpoint), avoid repeated identical failed operations, do not delete lock files or use `--force` without ownership evidence.
4. Keep phase-specific status in `STATUS.md` and machine-readable validation receipts with commit SHA, commands, exit codes, OS/Python, logs and skipped checks. Commit coherent milestones; do not merge unless explicitly authorized.
5. Live integration is **host side**. Container-local networking must use the established `host.docker.internal` endpoint only when validated; localhost inside a container is not the Windows host. No automatic fix via service restart for `ACCESS_DENIED`.
6. Never run full ten-task Harbor suite during implementation. Allow only deterministic fake tests and a preauthorized bounded single-task live smoke when required to prove recording; reserve scoring runs for explicit user consent and `-x`.

## Acceptance criteria (system-wide)

1. Repeated `web start` for the same managed endpoint reports the **same verified instance**, does not spawn a second server, and shows actual readiness only after the listening socket and application startup are complete.
2. Foreign listener, PID recycling, descriptor manipulation or unresolved Windows process parent/child identity cannot cause termination or credential disclosure. `stop`/`restart` fail closed where provenance is uncertain.
3. Approved same-user CLI obtains fresh **scoped** authorization without startup code, browser login or manual session cookie; separate restricted contexts yield an accurate blocker, not an authentication bypass.
4. Existing browser login behavior and strict origin/host checks remain intact, and an arbitrary loopback HTTP client without the local capability remains unauthorized for protected API endpoints.
5. `suite doctor -F -f json` distinguishes access denied, connection refused, timeout, unauthorized, invalid JSON, wrong origin, incompatible API format, wrong model/recording configuration, recorder unhealthy, and true absent Monitor. Its schema and exit statuses are documented.
6. With `-r`, a missing *managed* Monitor may be started exactly once if configuration matches approved explicit profile; credentials may refresh once; no unauthorized restart or config change. Without `-r`, `plan` remains read-only. `-x` alone does not authorize incidental host mutations outside the explicitly documented run contract.
7. No inference is dispatched by `doctor`, `plan`, auth bootstrap or recovery. Every new suite task still checks recorder health before dispatch and persists evidence of failures without falsely marking a trial scored.
8. No secrets, login codes, cookies, local auth bearer tokens, request content or provider credentials appear in diagnostics JSON, stdout, logs, subprocess arguments, checkpoints or archive metadata.
9. CI unit/integration tests and Windows host tests pass as applicable; WSL2/Docker cases have fixture tests and host validation evidence (or clearly labeled unverified limits). No previously qualified OpenCode v2 routing, recording durability, run checkpoint or Runmux behavior regresses.

## Rollback and migration

New management and local-control features are additive/opt-in; avoid changing existing `llm-monitor web [flags]` until compatibility is tested. Rollback disables local control + auto recovery while leaving foreground Monitor and current suite preflight operational. Preserve old run manifests verbatim; never retroactively reframe prior checkpoints as authenticated using the new mechanism. Introduce a configuration/schema version for descriptors and local tokens. Reject incompatible future descriptors safely; do not erase originals. Transition old `LLM_MONITOR_SESSION_COOKIE` and `monitor_session.env` support through a time-limited, opt-in deprecation window with warnings; perform no unsolicited deletion of user files. A `web stop` timeout retains state/evidence and clearly reports uncertainty. Database shutdown uses graceful recorder drain/checkpoint, no deletion/truncation of WAL or telemetry.

## Deliverables and handoffs

- `phases/PHASE_00_BASELINE.md` through `phases/PHASE_06_ROLLOUT.md`: independent implementer handoffs, with recommended model/effort, scope, steps, tests, completion evidence, and upstream gates.
- `CONTRACTS.md`: proposed CLI, status/error taxonomy, control protocol, state machine, and data schemas to freeze before implementation.
- `VALIDATION_MATRIX.md`: incident-to-regression map, execution commands, release gates, and evidence template.
- `SOURCE_NOTES.md`: repository inspection links, reference architecture, external primary-source guidance, freshness and uncertainty.
- `README.md`: archive index and adoption sequence.

## Current next step

**Do Phase 00 only** after checking the actual working checkout and active agents. Do not start a second worker on `llm-monitor web stop`; once it is completed/validated, adopt its implementation and continue with Phase 01 on the validated integration branch. The most cost-effective primary follow-up is one implementer executing Phases 01–04 sequentially, checkpointing at each verified gate, not four independently competing workers.
