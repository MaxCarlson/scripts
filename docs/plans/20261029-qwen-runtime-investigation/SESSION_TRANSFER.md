# Qwen Runtime Investigation — Session Transfer

Inspection date: 2026-10-29. This handoff records repository and runtime observations from the current session. Host resource values are point-in-time diagnostics and may change.

## A. Executive summary and objectives

The investigation asks why local Qwen coding requests sometimes consume their entire generation allowance on reasoning without editing files, and which workflow can produce correct, independently verified code with bounded latency and recovery. The pipeline is Codex coordinator → Agent Benchmark / opencode_worker → OpenCode 1.19.3 → LM Studio 0.4.26 → Qwen3.8-27B Q4_K_M (qwen38_23GB). The intended end state is an evidence-supported local operating policy, not a leaderboard score.

**Established findings**

- The existing OpenCode model alias does not emit reasoning_effort for selected low/medium/xhigh variants. Explicit model reasoning capabilities/variants or model-level options.reasoningEffort do serialize the field. OpenCode serializes configured output limits as max_tokens.
- The exact local LM Studio GGUF accepts reasoning_effort=none; direct probes and agent histories reported zero reasoning tokens for tested none calls. This increases actionability and often shortens time to first edit, but does not ensure correct lifecycle logic.
- Default reasoning has reproduced reasoning-only exhaustion: a B1 analogue hit finish=length at a 16,384-token output ceiling with 16,384 reasoning and zero ordinary output on the final inference; a T5 default repeat hit the same failure class at 8,192 with no edit.
- low/medium/xhigh were accepted on the OpenAI-compatible route, but deterministic direct probes showed identical token accounting for those values and omitted/default. Their behavioral effect on this GGUF remains unverified.
- No numerical reasoning_budget or thinking_budget cap was enforced on the tested LM Studio OpenAI-compatible route. Each accepted value of 16 still produced 65 reasoning tokens.
- OpenCode surfaced the observed finish=length results. No bridge, response-delivery, or tool-execution defect has been established as the cause of the reasoning-only failures.

**Correctness limitation:** none prevented reported reasoning-only consumption in these samples, but B1 implementations still failed independent lifecycle assertions. One repair succeeded on fixture revision 1.0.0; matched revision 1.0.1 single-stage, checklist, and one-repair conditions all failed. The sample is too small to claim reliability or a durable repair benefit.

**Completion criterion:** demonstrate an operating profile that returns actionable work, edits the intended files, completes normally, passes independent verification, and has bounded, recorded repair/escalation behavior. No profile currently meets a reliable-success claim.

## B. Git and workspace state

- Worktree: C:\Users\mcarls\src\scripts\.worktrees\qwen-runtime-investigation-20261029
- Branch: experiment/qwen-runtime-investigation-20261029
- HEAD and latest pushed branch commit: ee773a6e55ef5beaff974e6866f44a5982a99220; local branch and origin/experiment/qwen-runtime-investigation-20261029 matched at inspection.
- Investigation base / merge-base: 268805c41fe4b3b0c1107452298a8a4a79978ad3.
- origin/main: eeb40e8468d5fb33816caa5a8ec45f20b639c4f8 (includes the LLM Monitor SSE deadline fix). This branch is 9 commits ahead and 15 behind origin/main; do not merge or rebase automatically.
- Commits on the investigation branch after its base:

  | Commit | Description |
  |---|---|
  | 9bb19500 | Add Qwen runtime investigation benchmark |
  | cf760b70 | Record Qwen T2–T4 reasoning comparison |
  | 28f9f4a6 | Record Qwen async reasoning comparison |
  | 2f118489 | Add Runmux polling lifecycle regression fixture |
  | bec5eeb0 | Record Qwen RAM and B1/T5 checkpoint |
  | 250774e3 | Checkpoint Qwen B1 repair and budget findings |
  | d1e6342a | Make Agent Benchmark RAM limits opt-in |
  | f6ca0d59 | Add reproducible instruction variants |
  | ee773a6e | Reconcile Qwen investigation checkpoint |

- At the initial current-session inspection, tracked modifications were docs/agent/README.md, docs/plans/20261029-qwen-runtime-investigation/STATUS.md, experiments/qwen_runtime_investigation/README.md, and experiments/qwen_runtime_investigation/evidence/telemetry.sqlite3.
- Uncommitted intended source/docs include experiments/qwen_runtime_investigation/request_capture_proxy.py, experiments/qwen_runtime_investigation/tests/test_request_capture_proxy.py, docs/agent/LOCAL_LLM_RUNTIME_OPERATIONS.md, the three modified documentation files above, and this transfer document. The operations guide is a copy of the previously untracked guide in the main checkout; the isolated branch README index now links to it. It is not committed yet.
- There are over 1,000 untracked files under experiments/qwen_runtime_investigation/evidence/, including direct-probe JSON, monitor histories/reports, run directories, fixtures, runtime config/data snapshots, captured request parameters, trial-local workspaces, and diagnostic logs. The evidence tree is intentionally preserved. The tracked telemetry DB and its WAL/SHM companions are not to be staged.
- Ignored artifacts include .pytest_tmp_root, Python caches, many benchmark.log files, and runtime caches/snapshots. A prior git status --ignored reported 52 ignored entries at the time of that scan; this count changes as runtime files change.
- **Keep unstaged:** evidence/telemetry.sqlite3, WAL/SHM files, benchmark.log, recorder logs, session snapshots, project-local OpenCode config/runtime state, OpenCode snapshot repositories, prompt/session records, and trial source snapshots. Do not stage the evidence tree wholesale.
- No commit or push was made in this session. An explicit allowlist may stage the operations guide/index, investigation status/readme, proxy code/tests, and transfer document. The same-worktree raw evidence remains uncommitted.
- The main checkout at C:\Users\mcarls\src\scripts is dirty and was not edited by this investigation session; preserve its unrelated work. No subagent is currently active. /root/monitor_coordination completed without editing files and reported it had no direct channel to the separate Monitor developer. Process scans found no OpenCode, LM Studio, model backend, local-agent, or benchmark process; the historical recorder is an exception discussed in section F because its output/DB continued to update while its PID was not visible.

## C. Implemented work

### Agent Benchmark tasks and harness

The investigation uses the existing agent_benchmark runner, worktree isolation, durable records, scope policy, hidden verifiers, scoring, telemetry, and reports. The six reusable coding tasks are manifest version 1.0.0 with 120-second task budgets:

| Stage | Task manifest | Purpose |
|---|---|---|
| T1 | modules/agent_benchmark/agent_benchmark/tasks/qwen-file-creation/ | New small file/function |
| T2 | .../tasks/py-focused-bug-fix/ | Focused bug repair |
| T3 | .../tasks/py-test-development/ | Add tests to existing code |
| T4 | .../tasks/qwen-session-state/ | Session lifecycle/state machine |
| T5 | .../tasks/qwen-async-behavior/ | Moderate asynchronous behavior |
| T6 | .../tasks/py-multifile-change/ | Bounded multi-file change |

An additional existing-code task is qwen-existing-code-modification. The Runmux-inspired regression challenge is qwen-runmux-polling-lifecycle, manifest revision 1.0.1, 180-second budget, allowed edit src/telemetry_polling.js, file-tools-v1 profile. It uses independent public and acceptance verifiers plus a trusted reference. The fixture is synthetic and is an analogue, not a historical Runmux source copy.

Fixture/reference/incorrect-starter verification and verifier timeout/process ownership behavior were exercised in earlier phases. The remaining proxy tests have their own environment limitation described in section G. Do not duplicate benchmark runner or score logic.

### B1 revisions, checklist, and repairs

- Revision 1.0.0 preserves the earlier worker instruction and verifier evidence. The effective file-tools-v1 tool profile has no shell, while revision 1.0.0 told the worker to run a Node test command. The worker could not run it.
- Revision 1.0.1 clarifies that visibility restored during an in-flight poll must result in exactly one immediate follow-up after settlement, and aligns the instruction with the shell-less worker by having Agent Benchmark run tests.
- evidence/b1-invariant-checklist.md contains the task-derived checklist. It is separate from hidden reference code.
- Repair starting copies are under evidence/repair-fixtures/; planning artifacts include evidence/b1-plan-stage-none.txt and .json. Preserve original S1 snapshots and first-attempt verdicts.

### Request capture and profiles

- experiments/qwen_runtime_investigation/request_capture.py runs the sanitized OpenCode mock-provider capture (already committed in the investigation history). request_parameters.json and request-forwarding-report.md are the reports.
- request_capture_proxy.py is an experimental loopback-only forwarding proxy: bind 127.0.0.1:1235, upstream 127.0.0.1:1234, allowlisted model identifiers, fixed /v1/models and /v1/chat/completions routes, trust_env=False, no access log. It writes only safe request field names and allowlisted scalar settings/counts; it does not persist prompts, credentials, tool arguments, generated text, or full request bodies.
- tests/test_request_capture_proxy.py covers allowlisted capture, streaming/tool-call byte forwarding, provider errors, client disconnect/upstream closure, and fail-closed routes/model IDs. Earlier focused runs passed all four tests and Ruff. A fresh run in this restricted environment hung before entering the first test body due Windows asyncio socket-pair startup; see section G.
- configs/ preserves distinct profiles: qwen-unconfigured-output-{8192,16384}.json, qwen-none-output-{8192,16384}.json, and low/medium/xhigh 8K profiles. Context and output are independent.
- evidence/runtime/proxy-compatibility-v2.json, proxy-error-compatibility.json, and outbound-request-parameters.jsonl record the direct/proxied probes and sanitized parameter captures. These probes were direct HTTP calls, not an OpenCode coding-agent inference.

### Memory policy, Monitor, and runbook

- d1e6342a changed Agent Benchmark's --max-ram-percent default to None and made percentage thresholds explicit opt-in. The old 90% pre-dispatch rule must not be restored. Model admission uses the observed LM Studio estimate against measured free GPU and combined host/GPU capacity; measured resource percentages remain diagnostics. No fixed 4-GiB reserve or model-size multiplier should be reintroduced without evidence. expected_model_size_bytes is diagnostic, not an admission multiplier.
- LLM Monitor recording/history/reporting has been used for persisted per-inference data. See evidence/monitor-report-*.json, monitor-history-*.json, telemetry.sqlite3, and the comparison/findings markdown files. The separate Monitor developer owns Monitor implementation; do not edit it here.
- docs/agent/LOCAL_LLM_RUNTIME_OPERATIONS.md now exists in this worktree and is linked from docs/agent/README.md. The runbook's lms, local-agent, opencode serve, and llm-monitor option spellings were checked against installed --help; representative syntax-only parser checks returned exit 0. It is staged only if explicitly included in the allowlist; it is not yet committed.

## D. Experimental findings

### Request forwarding and local API behavior

- Six mock configurations generated 11 OpenCode CLI attempts and 22 sanitized POST /v1/chat/completions requests (evidence/request-forwarding-report.md). The existing alias omitted reasoning_effort for selected low/medium/xhigh, including on tool-bearing requests. Explicit model capability/variant configurations forwarded each value. Explicit none serialized as "none". Agent-level variant: low appeared only on the no-tool request in that capture and is not a reliable worker control. Model-level options.reasoningEffort was forwarded on tool-bearing and no-tool requests.
- max_tokens matched output limits 8,192/16,384; requests streamed and exposed 10 tools in the mock worker. This establishes OpenCode serialization only.
- On the exact Qwen Q4_K_M GGUF, direct LM Studio OpenAI-compatible probes reported: omitted/low/medium/xhigh each 65 reasoning + 71 completion tokens for the same deterministic prompt, so low/medium/xhigh were accepted but had no observed effect in that probe; none produced 0 reasoning + 4 completion tokens; off and on were rejected HTTP 400. Direct findings and limitations: evidence/direct-model-findings.md, direct-runtime-snapshot.json, and direct-*.json.
- reasoning_budget:16 and thinking_budget:16 each returned HTTP 200 but still used 65 reasoning tokens (evidence/numeric-budget-probes.json). Stop retesting these fields on this same route unless a newly documented API mechanism is identified.

### Coding attempts

- T1: one default 8K and one none 8K fresh run passed. This is not a reliability estimate.
- T2 and T4: both omitted/default and explicit none fresh trials passed their independent verifier. none had zero reported reasoning and earlier first edits in these small runs. See evidence/t2-t4-comparison.md.
- T5 at 8K: the initial default and none attempts passed. In later repeats, default included a pass, a reasoning-only finish=length failure at exactly 8,192 reasoning tokens without a write, and an unscored scope failure after a malformed/missing write target. none had two passes and one correctness failure (worker was not awaitable), all with zero reported reasoning. Results and denominators are in evidence/t5-async-comparison.md, t5-repeat-attempts.md, and ram-b1-t5-checkpoint.md.
- T5 16K: default passed; matched none dispatch was rejected by the then-configured 90% RAM guard at approximately 90.2%, so no inference occurred. This is an infrastructure rejection, not a model failure. The percentage cutoff was subsequently removed as a default.
- Historical Runmux B1 and the closest analogue must remain distinct. The original prompt and permission snapshot are unavailable. evidence/historical-b1-reproduction.md records the limits. The B1 analogue at default reasoning / 16K reproduced finish=length: 5 inferences, 16,438 session reasoning tokens, final inference 16,384 reasoning and 0 ordinary output, 7 reads and no edit, 160.7 seconds. The explicit-none analogue used 11 inferences, 0 reasoning, 3,196 ordinary output, edited, then failed the visibility-resume assertion (1 sample where 2 were required), 31.8 seconds worker time. See evidence/ram-b1-t5-checkpoint.md.
- A separate none first attempt on revision 1.0.0 (EXP_20261029_174653, session ses_e773a55caffeHj15DIE5tQPZrS) failed visibility resume. One verifier-guided repair (EXP_20261029_181249, session ses_e77229381ffeCr10vlMTXdWKRW) passed the independent verifier without coordinator/Codex source changes. It added 9 inferences, 58,800 input tokens, 2,364 output tokens, 0 reasoning; repair first edit 11.052 s and user-turn elapsed 23.750 s. Preserve the first-attempt failure separately.
- A separate fresh revision 1.0.0 implementation (EXP_20261029_181006, session ses_e77251202ffejX5jWasdTRD7S2) failed single-flight: two fetches began while one was allowed. A later plan-then-execute none comparison failed visibility resume. Planning and execution together cost 12 inferences, 93,012 input, 4,882 output, 0 reasoning, 40.506 seconds measured stage/turn time. See evidence/b1-repair-budget-plan-comparison.md.
- Matched revision 1.0.1 workflows are in evidence/b1-workflow-comparison.md: A single-stage none failed visibility resume (12 inferences); B one targeted repair from A failed close() abort behavior (17 additional inferences); C fresh none with task-derived invariants failed the same visibility-resume assertion (13 inferences). They reached edits and normal stop, but none passed correctness. The single repair that passed was on v1.0.0 and does not contradict these v1.0.1 outcomes.

### B1 root cause

evidence/b1-root-cause-analysis.md distinguishes the bugs:

- **Visibility resume:** the implementation returned immediately if a poll was active and did not retain the fact that visibility returned. When the in-flight promise settled, normal interval scheduling happened rather than one immediate follow-up. Revision 1.0.1 now states the interaction explicitly.
- **Single-flight:** another implementation called AbortController.abort() and cleared the in-flight sentinel immediately. Visibility restore then started a second fetch before the original promise settled. Abort signal is not settlement.
- Workers read the relevant source roughly 7–9 times and used read/grep/write/edit tools. file-tools-v1 has no shell, so they could not run the Node command requested by the old v1.0.0 instruction. The benchmark ran public/hidden acceptance verifiers after completion. No coordinator patch caused the successful old repair.
- The matched v1.0.1 checklist did not prevent the bug. Remaining likely workflow improvements are explicit coupled invariants, a distinct request-settlement sentinel, and verifier-driven feedback. These are hypotheses for further testing, not demonstrated reliability gains.

## E. Current runtime condition

### Latest read-only observation

Latest local status scan (2026-10-29, around 14:05 PDT):

| Item | Observed state |
|---|---|
| LM Studio | Installed file C:\Program Files\LM Studio\LM Studio.exe, version 0.4.26+4; no GUI/backend process visible |
| lms daemon status --json | {"status":"not-running"}, exit 0 |
| lms server status --json --quiet | {"running":false,"port":1234}, exit 0 |
| lms ps --json | Stalled at “Waking up LM Studio service...”; the probe was interrupted with Ctrl+C, exit 1; no inventory was returned |
| Exact model | Downloaded key qwen38-27b-q4km; historical loaded instance and OpenCode alias qwen38_23GB; exact Qwen3.8-27B Q4_K_M. Current residency is unknown because lms ps cannot return and no server/backend is running |
| Historical model settings | LM Studio previously reported 98,304 context and reasoning metadata off/on, default on. This is stale after shutdown, not a current loaded-model verification |
| Baseline OpenCode profile | Isolated global alias was 98,304 context / 8,192 output / no explicit reasoning effort |
| Paused B1 project profile | Preflight JSON showed 98,304 context / 16,384 output / reasoning_effort=none, model qwen38-27b-q4km, base URL http://127.0.0.1:1235/v1. This is saved configuration evidence, not an effective running process now |
| Port 1234 | No listener |
| Port 1235 proxy | No listener/process |
| OpenCode 4196 | No listener/process |
| OpenCode 4096 | No listener at latest scan; no configuration/termination action was taken. Preserve it if it reappears |
| RTX 5090 | Latest point sample: 32,607 MiB total, 29,125 MiB used, 3,063 MiB free, 5% utilization; nvidia-smi listed no compute process |
| Host RAM/commit | GlobalMemoryStatusEx: 61.61 GiB physical total, 15.25 GiB available, 75% load; 165.61 GiB commit limit and 89.34 GiB commit available. WMI memory fields were zero/unavailable in this sandbox; Windows GPU perf-counter sets and page-file activity were unavailable |

The last LM Studio estimate in evidence/runtime/pre-b1-resource.json was about 29.22 GiB for the Qwen model/context. Current 3.06 GiB free is far below that estimate. GPU allocation is **not attributed**: WDDM provides no owner PID here. Do not infer that the allocation is the Qwen model or terminate any process/reset the GPU to reclaim it.

### Startup attempts and results

- lms daemon up --json: waited 15 seconds with stderr “Waking up LM Studio service...”; a following daemon check still said not-running.
- lms server start --port 1234 --bind 127.0.0.1: stalled at the same wake-up message and was interrupted; no listener appeared.
- lms ps --json also stalled at that message; it did not establish that the model inventory is empty.
- Starting the installed GUI normally and with hidden window both left no process. Direct process launch returned exit code -2147483645 (0x80000003, STATUS_BREAKPOINT). A diagnostic launch with --enable-logging=stderr --v=1 returned the same code with empty stdout/stderr. No crash detail was found in the checked application log locations.
- No model load, unload, GPU reset, process kill, Windows reboot, or inference occurred during the current recovery attempts. These startup failures and the current GPU sample are summarized in experiments/qwen_runtime_investigation/evidence/runtime/readiness-20261029.json (resource figures in that file are an earlier point sample).

## F. Monitoring and in-flight sessions

### Current B1 attempt

- Run: EXP_20261029_204142
- Benchmark trial: run-EXP_20261029_204142-qwen38-27b-q4km/trial-001
- OpenCode session: ses_e769a3321ffe4eT7Wq9CouFEql
- Workspace: experiments/qwen_runtime_investigation/evidence/state/workspaces/trial-rt7bsngv
- Effective config preflight: evidence/runtime/b1-fresh-effective-config-preflight.json
- The trial ended INFRASTRUCTURE_ERROR before submission. lifecycle.json says stage=not_submitted, has no owned worker PIDs, and records the requested 98,304/16,384/none profile. benchmark.log shows EOFError at the observer gate's input() (modules/agent_benchmark/agent_benchmark/cli.py:613) after stdin ended. It is not a model/provider result. The current session has zero input/output/reasoning tokens and no inference.
- Per-run monitor DB evidence/runs/EXP_20261029_204142/telemetry.sqlite3 reported one session, zero jobs, zero inference rows, 869 event rows, and five open provider_error collection gaps for messages/permissions/questions/session/status. The session row reported idle, model null, legacy source, and complete session-list coverage. This does not indicate a coding inference occurred.
- The zero-byte evidence/state/command.lock remains. No benchmark process appeared in the local scan and the trial did not submit. Do not delete the lock or workspace as cleanup without verifying the benchmark state mechanism.

### Recorder and live observer

- The exact-session recorder was started before the planned dispatch with endpoint 4196, the exact trial workspace/session, LM Studio URL 1234, and the per-run DB above. The process ID originally returned was 51788, but that PID was not found on a later scan. **Recorder lifecycle is uncertain:** its stdout log and DB continued to receive writes through approximately 14:08 PDT (stdout log 543,368 bytes; DB 1,130,496 bytes). No matching process was visible. Treat it as a possibly active writer; do not stop it, open the DB for mutation, or stage its log/DB until its process identity is resolved.
- The 120-second llm-monitor live observer produced valid evidence/runs/EXP_20261029_204142/live-sse-session.json: connected to 4196, 12 SSE frames, zero matching-session events, zero reasoning/text deltas, stream_capability=unavailable, deadline-limited/incomplete coverage, no last finish reason. It reported one tool-call field despite zero matching events; with no inference this is inconclusive and not evidence of a delivered coding tool call. The observer completed its deadline and left no confirmed observer process.
- A 3-second preflight snapshot evidence/runtime/live-sse-preflight.json connected but saw no matching events before dispatch, as expected. Neither snapshot validates incremental inference deltas for this B1 session because no inference was submitted.
- Earlier evidence in experiments/qwen_runtime_investigation/README.md records a separate real none inference where the live Monitor saw text deltas and persisted history was complete; no reasoning deltas were reported for that none run. Do not conflate it with the current B1 session.
- Current main is eeb40e84...; the venv llm-monitor.exe imports C:\Users\mcarls\src\scripts\modules\llm_monitor\llm_monitor version 0.6.0 while installed distribution metadata says 0.1.0. The merged SSE fix is in main. Historical found=false cases were traced to absent recorder lifecycle or wrong DB/endpoint scoping; use exact endpoint, project, session, and DB. See evidence/monitor-history-*.json and evidence/t1-monitor-findings.md.
- No other benchmark dispatch or durable worker job is pending. Historical sessions and evidence remain on disk and must not be cleaned.

## G. Current blockers

| Blocker | Symptom and evidence | Plausible causes / limits | Next safe action |
|---|---|---|---|
| LM Studio runtime unavailable | Daemon not-running, server down, lms ps wake-up hang, GUI exits 0x80000003; details in section E and evidence/runtime/readiness-20261029.json | GUI startup failure, llmster/service startup issue, or restricted desktop/runtime environment; no crash detail yet | Inspect app/daemon logs and process launch diagnostics. Do not load Qwen until the daemon works and capacity is verified |
| Unattributed GPU allocation | 29,125 MiB used / 3,063 MiB free, no process listed, historical Qwen estimate about 29.22 GiB | WDDM/driver allocation or hidden/unattributed owner; not proven to be LM Studio/Qwen | Obtain process attribution using approved Windows GPU diagnostics or wait for ownership evidence. Do not kill processes, reset GPU, or assume model residency |
| Recorder process not identified | Monitor stdout and DB timestamps advanced, but prior PID 51788 and matching process scans did not identify a writer | Detached/launcher process may have another identity; file writes could also be delayed | Identify the open DB/log handle and owning process before stopping it or starting another recorder. Preserve DB/WAL/SHM |
| Request-capture end-to-end path incomplete | Direct/proxy Qwen results match; 4196 project preflight pointed to 1235, but no live OpenCode inference reached proxy | Runtime was down before submission; actual provider fields are not correlated to a coding inference | Once runtime is safe, start loopback proxy and 4196 with the isolated override; verify /config for the exact project; capture one allowlisted request and correlate by timestamp, not request ID |
| Restricted pytest networking | Current pytest -vv -s ...test_request_capture_proxy.py stalled before test body in Python 3.12 Windows Proactor socketpair startup (socket.accept) for Starlette TestClient; the earlier run had passed, Ruff passes | Sandbox loopback/socketpair restrictions, not a proxy assertion | Re-run in an environment that permits local socket pairs or change the tests to avoid TestClient only if the limitation is reproducible outside this sandbox |
| Current B1 result is infra only | EXP_20261029_204142 ended at observer input() with EOF; lifecycle not_submitted, zero inferences | Interactive stdin ended; LM Studio also unavailable | Preserve the infra record. Start a fresh trial only after runtime and Monitor processes are understood |
| Reliability and live event provenance | none has correctness failures; no actual OpenCode request capture for a coding inference; current SSE attempt had no inference events | Small N and incomplete runtime/monitor coverage | Do not claim a reliable profile. Collect one controlled next trial with both request capture and Monitor before expanding |

## H. Remaining work and recommended execution order

1. **Immediately on takeover, reconcile the recorder.** Inspect evidence/runs/EXP_20261029_204142/monitor-recorder.stdout.log, its DB timestamps, the per-run WAL/SHM, and process/file-handle ownership. The log/DB were still changing near handoff. Do not terminate or overwrite it without verified ownership.
2. **Diagnose LM Studio startup without touching unidentified GPU owners.** Start with lms daemon status --json, lms server status --json --quiet, process inventory, GUI crash diagnostics, and the current memory snapshot. lms ps previously hung at “Waking up LM Studio service...”; do not interpret that as an empty inventory. After the service is healthy, use lms ps --json to verify exact loaded instance/key/context. Use the model's --estimate-only before any load; current free VRAM is far below the old estimate.
3. **Verify proxy/port routing before any inference.** Re-run the focused proxy tests in a socket-capable environment; start only the loopback proxy at 1235 and isolated OpenCode 4196 after confirming ownership. Verify the exact trial project's effective baseURL, model alias, context, output limit, and reasoning option. Keep the global baseline at 98,304/8,192 unless the specific trial calls for 16,384.
4. **For the next controlled trial, start recorder and live observer first.** Use endpoint http://127.0.0.1:4196, the actual workspace and new session/trial IDs, and a persistent TTY through the benchmark's observer gate. Validate matching session events and deadline completion. Missing reasoning deltas alone are not an SSE failure; no matching session events during an active inference is a regression to investigate.
5. **Continue only a small, hypothesis-led correctness comparison.** Preserve all prior first-attempt scores. Revision 1.0.1 A/B/C already failed; do not repeat those exact conditions automatically. Use the existing B1 fixture/verifier and a new fresh attempt only if it answers a specific remaining question about the explicit in-flight visibility/single-flight invariants or one targeted repair. Include first-attempt correctness, repair correctness, scope, inference-level tokens/finish reasons, latency, tool calls, and total workflow cost.
6. **Finish observability and root cause.** Reconcile recorder endpoint/project/session/database scoping; verify effective live request fields from the sanitized proxy; compare with Monitor and OpenCode histories. Keep configuration evidence, runtime acceptance, and task correctness as separate claims.
7. **Finalize operating policy and review artifacts.** Recommend none only with independent verification and bounded repair where justified; escalate complex/uncertain changes to Codex or another model. State that reliability remains statistically inconclusive. Run focused tests, inspect docs/status, then stage/commit/push only an explicit allowlist.

Do **not** repeat the 22-request mock forwarding sweep, direct reasoning_budget/thinking_budget cap probes, or identical short-prompt low/medium/xhigh probes unless new code/API evidence changes the hypothesis. Do not repeat the historical Runmux task claiming exact reproduction: its original prompt/permission snapshot is unavailable. Do not count prior 90%-guard pre-dispatch rejections as model outcomes. The current EXP_20261029_204142 EOF trial is preserved and should not be retried using the same session.

## I. Permissions and safety boundaries

Authorization already granted for this investigation:

- Manage the experimental LM Studio model and processes that are positively identified as owned by this experiment.
- Start/stop isolated OpenCode 4196 and the 1235 request-capture proxy.
- Run bounded, serial inference experiments on the exact Qwen model after safe readiness checks.
- Modify and test this isolated branch and stage/commit/push reviewed sanitized checkpoints.

Boundaries:

- Preserve OpenCode 4096 and unrelated GPU workloads.
- Do not reset the worktree, clean caches, discard evidence, or overwrite dirty main checkout work.
- Do not kill unidentified processes, reset the GPU, reboot Windows, or load a 29-GiB-class model into 3-GiB free VRAM.
- Do not restore automatic 90% physical-RAM rejection/cancellation.

## 2026-10-29 bootstrap successor update

This section supersedes the runtime-unavailable and “next action” statements above for the current host state. Historical experiment findings remain unchanged.

| Checkpoint | Result and evidence |
|---|---|
| LM Studio/API | PASS. `local-agent run` found the existing model already resident; `lms ps --json` showed one `qwen38_23GB` Q4_K_M instance, IDLE, context 98,304. Server status and `/v1/models` confirmed 1234. No software was installed; no `llmster` commands were used. |
| Direct inference | PASS. HTTP 200 ordinary assistant output, `finish=stop`, 6 completion tokens, 0 reported reasoning tokens for `reasoning_effort=none`, `max_tokens=96`. |
| OpenCode 4196 | PASS. `local-agent opencode status --port 4196 --json` reported healthy OpenCode 1.19.3. The trial project used the intended alias, context/output limits, `reasoningEffort=none`, and proxy URL 1235. OpenCode 4096 was not changed. |
| Proxy | PASS. Focused tests: 4 passed. Four live allowlisted captures show model key, `reasoning_effort=none`, `max_tokens=8192`, streaming, and five tools. Timestamp alignment to four Monitor inferences is the available correlation; no session ID is captured. |
| LLM Monitor | PASS with coverage limitation. Recorder history has 4 completed inferences, 3 tool calls, one successful write, 336 output tokens, and zero reported reasoning. DB integrity/FK checks passed. Live SSE delivered matching-session activity; TUI connected. Bounded snapshot reported `observation_deadline_limited` and `telemetry_incomplete`, so do not claim full live coverage. |
| T1 coding smoke | PASS. `EXP_20261029_214419`, trial 001, session `ses_e7660e211ffeup1ANACyWtDFD1`; independent functional, scope, and termination checks passed in 7.8 seconds. One pass proves pipeline operation, not reliability. |
| Old B1 recorder | RESOLVED. Process identity and matching DB/log ownership were confirmed, the obsolete recorder was stopped after graceful signals failed, and the preserved database passed integrity checks. `EXP_20261029_204142` remains not submitted with zero inference. |

The shared local-agent registration advertises provider URL 1234 while the experiment project's effective OpenCode configuration overrides it to capture proxy 1235. `local-agent model verify` therefore reports a baseURL mismatch (including with `--lms-port 1235`, which compares the shared registration against 1235). This is expected for the project override. Use effective project/provider inspection plus sanitized proxy records as route evidence; do not alter the shared registration to silence the warning.

### Recommended operating policy

- For short, bounded, low-risk tasks, use explicit `reasoning_effort=none` only after verifying the exact project configuration and request parameters. This setting removes reported reasoning-token use in the tested Qwen profile; it does not guarantee correct code.
- Require an independent test or hidden verifier for every change. Preserve first-attempt correctness separately from repaired correctness.
- Permit one targeted repair from actionable verifier output for tractable defects, then verify again. Existing evidence includes one successful repair and three failed matched revision-1.0.1 B1 workflows, so repair is an option, not a dependable recovery guarantee.
- Escalate asynchronous lifecycle, complex multi-file, broadly scoped, and ambiguous work to Codex or another stronger model. The current evidence does not support local Qwen as a general coding agent.
- Record endpoint, project/session/trial IDs, exact model and limits, setting provenance, per-inference usage/finish reason, tool outcomes, Monitor coverage, independent score, repair score, and total elapsed time. Keep GPU memory attribution caveats explicit.
- Do not repeat T3 or broad condition matrices absent a specific unresolved hypothesis. Small samples establish task examples only, not a reliability rate.

Remaining limitations: one T1 bootstrap pass; limited independent task/profile samples; all three matched revision-1.0.1 B1 paths failed; timestamp-only proxy/session correlation; deadline-limited live Monitor snapshot; device-level GPU metrics; and unverified low/medium/xhigh and numeric reasoning-budget behavior. The runtime startup issue is resolved as an execution-environment/access mismatch for the tools used, not an LM Studio installation failure. The user's clarification that the GUI was already running supersedes the earlier attempted hidden GUI launch as diagnostic evidence.
- Never stage raw prompts, generated source, session contents, runtime caches/snapshots, telemetry databases/WAL/SHM, or unaudited logs. Use explicit file allowlists.
- Do not merge into main without approval.

## Immediate handoff checklist

- [x] Preserve the isolated branch/worktree and reconcile the obsolete Monitor recorder; see the bootstrap successor update above.
- [x] Keep the exact experimental Qwen model loaded and verify its context and API readiness. Do not deal with `llmster` or install runtime components.
- [x] Preserve the B1 pre-dispatch session as an infrastructure result and run the bootstrap coding test in a fresh T1 session.
- [x] Keep port 4096 and the Runmux pilot untouched.
- [x] Stage and commit only the reviewed eight-file allowlist as `470329bf`; preserve evidence/, telemetry databases, WAL/SHM, logs, and runtime snapshots unstaged. Push this branch only; do not merge.
