# B1 analogue workflow comparison

Date: 2026-10-29. These are fresh trials of the synthetic Agent Benchmark B1 analogue,
not exact reproductions of the historical Runmux prompt or permissions. All coding trials
used OpenCode 1.19.3, LM Studio 0.4.26.0, Qwen3.8-27B Q4_K_M (`qwen38-27b-q4km`),
98,304 context, a 16,384 output ceiling, `reasoning_effort=none` in the isolated
project configuration, `file-tools-v1`, and seed 17. The first attempt and checklist
condition used the same task revision 1.0.1 and 180-second worker budget. The repair
started from the first attempt's failed S1 and used one 60-second budget.

## Results

| Condition | Correctness | Inferences | Input / output / reasoning tokens | Tool calls | First edit | Worker time | Command elapsed |
|---|---|---:|---:|---:|---:|---:|---:|
| A — single-stage `none` | Fail: visibility resume produced 1 sample, expected 2 | 12 | 85,833 / 3,515 / 0 | 15 (9 reads, 1 write, 2 edits, 3 other; 0 failed) | 23.9 s | 36.7 s | 171.5 s |
| B — one targeted repair of A | Fail: `close()` did not abort the active request | 17 additional | 166,919 / 2,835 / 0 additional | 19 (10 reads, 2 edits, 6 failed, 1 other) | 21.2 s | 33.3 s | 106.2 s |
| C — fresh single-stage `none` plus invariant checklist | Fail: same visibility-resume assertion as A | 13 | 128,271 / 7,211 / 0 | 15 (6 reads, 2 writes, 6 edits, 1 other; 0 failed) | 23.2 s | 57.1 s | 111.7 s |

First-edit latency is measured from the first recorded inference start to the first
successful write/edit event. Worker time is the benchmark's measured coding phase;
command elapsed also includes preflight, monitor attachment and report generation.
Token totals are sums across completed inferences within each session. The maximum
ordinary output in one inference was 1,671 tokens for A, 600 for B, and 2,427 for C.
Every final inference ended with `finish=stop`; earlier inferences ended with
`tool-calls`. None ended with `finish=length`.

The strict and end-to-end denominators are explicit: A first-attempt correctness was
0/1; B repaired correctness was 0/1 and end-to-end success after one allowed repair
was 0/1; C checklist first-attempt correctness was 0/1. All three sessions produced
actionable tool calls and edits, but none produced a verified implementation. A
separate earlier repair on fixture revision 1.0.0 passed; that one success is retained
as separate evidence and does not override these revision 1.0.1 outcomes.

## Root causes

- **A — missed follow-up:** The implementation set `pendingFollowUp` when visibility
  returned during a request. Its settlement path called `maybeScheduleNext()`, which
  unconditionally cleared the flag and scheduled the normal interval. It never issued
  the immediate follow-up. The worker inspected the source (nine read-only calls), but
  the file-tools profile cannot run shell tests; the harness ran the independent
  verifier. The task revision 1.0.1 explicitly states this transition.
- **B — repair regression:** The repair added a settlement path that consumes the
  pending follow-up, so it passed that earlier assertion. It stores
  `new AbortController().signal` as `inFlightSignal`, then calls `abort()` on that
  signal. The abort operation belongs to the controller; the signal remains unaborted,
  so the verifier's explicit `close()` assertion fails. Its abort path also clears the
  in-flight marker before the promise settles, which can permit overlap after an abort.
  The repair prompt named the close and single-flight requirements; this is an
  implementation defect, not a missing requirement.
- **C — eligibility guard blocks queuing:** The checklist condition added
  `pendingFollowUp` handling to `setVisible`, but its `isEligible()` predicate includes
  `!inFlight`. `setVisible(true)` returns on `!isEligible()` before reaching the branch
  that would queue a follow-up while `inFlight` is true. The requirement was present in
  both the base task and checklist; this is an implementation/control-flow defect.

The known single-flight failure from the earlier fresh B1 attempt remains distinct:
that implementation set its in-flight marker to idle immediately after requesting
abort, before the fetch promise settled. The v1.0.1 task now states the invariant
explicitly. A known-good earlier repair artifact passes the current independent
acceptance verifier, so these failures are not explained by a broken verifier. The
original Runmux failure remains an analogue because its complete prompt and permission
snapshot are unavailable.

## Actionability, correctness and resource outcomes

All three trials completed normally, reached edits, passed scope checks and had
confirmed worker termination. They used zero reported reasoning tokens and did not
exhaust their per-inference output allowance. Their independent correctness failures
are model implementation errors, not reasoning-only exhaustion, transport failure,
or infrastructure failures. A had no failed tool calls; B had six failed tool calls
among 19, but its close-abort defect is directly visible in the generated code.

The task-derived checklist condition used six reads versus nine in A, but still failed
the same assertion and used 7,211 output tokens versus 3,515. The first-write latencies
were similar. With one sample per condition, these observations do not establish that
the checklist improved source discovery, latency or correctness. Planning with `none`
also failed in an earlier separate comparison. Do not treat these results as a
reliability estimate.

Benchmark device/host samples were diagnostic only. Across A/B/C, maximum observed
host RAM use was 86.0%/82.2%/83.7%; minimum available host memory was 8.60/10.98/10.02
GiB. Maximum device GPU memory use was 29.01/28.87/28.87 GiB, with at least
2.83/2.97/2.97 GiB free. GPU values are device-level, not attributed to the model or
one inference. No allocation failure or resource-related process termination occurred.
The fixed 90% RAM guard was disabled; those percentages were observations, not verdicts.

## Monitor and configuration provenance

The earlier `found=false` Monitor lookups have two distinct causes. The fresh baseline
(`ses_e77229381ffeCr10vlMTXdWKRW`) and plan-execution session
(`ses_e771eceafffe1ZxozZwS9sPnRU`) have no trial-local `monitor-recorder.log`, so no
persisted Monitor recording was started for those sessions; their token/tool data comes
from OpenCode session evidence. For the later repair and checklist sessions, recorder logs
show the recorder writing to each experiment's own `runs/EXP_.../telemetry.sqlite3`, while
the original lookup used the shared `evidence/telemetry.sqlite3`. Re-querying with the
correct per-run database and endpoint `http://127.0.0.1:4196` finds both sessions with
complete coverage and zero recorded gaps. The earlier `found=false` result was therefore
a database-scope mismatch for those two, not a collection failure. Keep the raw recorder
logs and databases as local evidence; this report records only the sanitized diagnosis.

The merged LLM Monitor 0.6.0 source from `origin/main` commit
`eeb40e8468d5fb33816caa5a8ec45f20b639c4f8` was imported from the main checkout by
the installed executable. The separate live observer attached before A's dispatch.
It reported `stream_capability=streaming`, 826 SSE frames, 759 matching-session events,
574 text-delta events, 0 reasoning-delta events, 15 tool calls, and 3 file writes.
The first text delta arrived at 19:16:40.634 UTC, during an inference and about
1.08 seconds before that inference completed. Deltas were not delayed until after
inference completion. The observer exited successfully at its 120-second deadline.
Its snapshot is deadline-limited and reports incomplete live coverage; the separate
persisted history has complete coverage with 118 events, 12 inferences, 15 tools and
no recorded gaps.

The trial-local `opencode.json` files contain `reasoningEffort: "none"`, context
98,304 and output 16,384. Persisted history reports zero reasoning tokens. However,
the live observer reported empty effective model options and
`observed_outbound_provider_parameters: unavailable`. This disagrees with the
project-local configuration and leaves the actual request field unverified. Zero
reasoning tokens are behavioral evidence for these sessions, not an outbound request
capture. The historical mock-provider capture proves serialization, while the direct
LM Studio probe shows `none` yields zero reasoning tokens for the exact GGUF.

## Recommendation from this comparison

`reasoning_effort=none` remains useful for actionability and avoiding reasoning-only
truncation, but it is not a correctness control for this lifecycle task. Keep
independent verification mandatory. At most one targeted repair can recover some
failures, but this new repair regressed another explicit lifecycle requirement, so
repair is not yet reliable. Use Qwen autonomously only for small, bounded changes with
clear contracts and independent checks; escalate stateful lifecycle or multi-file
changes to Codex when verification fails. Do not recommend a numeric reasoning budget:
the tested LM Studio fields were accepted without enforcing their cap.

No additional same-condition GPU repetitions were launched after this comparison. With
single observations per condition and all three revision-1.0.1 workflows incorrect, the
data do not support a reliability estimate or an operating profile for complex coding.
Repeating an unchanged workflow would not test a new intervention. Resume agentic trials
only after a concrete change to the repair feedback or execution workflow, and keep the
independent verifier as the end-to-end gate.
