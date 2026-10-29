# B1 transition-matrix follow-up

Date: 2026-10-29. This bounded follow-up tested whether an explicit ordered invariant prompt improves the revision-1.0.1 asynchronous polling fixture, then allowed one verifier-guided repair. It used the existing isolated OpenCode 4196 / proxy 1235 path and did not change runtime software or model settings.

## Controlled condition

- Model: Qwen3.8-27B Q4_K_M, exact key `qwen38-27b-q4km`; context 98,304; output cap 16,384; explicit `reasoning_effort=none`; `file-tools-v1`; seed 17.
- First attempt: run `EXP_20261029_233054`, trial 001, session `ses_e75ff5dd4ffeIOT274edonasxv`, one `extended-180s` run using the revision-1.0.1 lifecycle fixture and an ordered state-transition invariant append (SHA-256 `1CF6E42C860509C77BE17E71ED209B71FC7BB11E4B28163337A559D6D599D652`).
- Repair: run `EXP_20261029_234019`, trial 001, session `ses_e75f6c010ffe4Vn3fFlVu1AQcR`, a fresh 60-second repair fixture seeded byte-for-byte from the first attempt's S1. The repair prompt included the verifier error and the transition invariants. The hidden acceptance verifier was unchanged.

## Results

| Measure | Invariant-guided first attempt | One verifier-guided repair |
|---|---:|---:|
| Code verifier | Fail: JavaScript syntax error at line 132 | Fail; no code edit before timeout |
| Scope | Uncertain: one failed edit operation; all recorded targets stayed in the authorized source path and no path violations were found | Pass; no changed files |
| Termination | Confirmed | Confirmed after harness timeout |
| Budget | Pass | Fail: 60.4 seconds |
| First edit | 29.99 seconds after first inference | None |
| Worker time | 67.4 seconds | 60.4 seconds, timed out |
| Experiment wall time | 463.5 seconds including the pre-dispatch pause | 99.7 seconds including the pre-dispatch pause |
| Inferences | 21 completed | 7 total, 6 completed before abort |
| Input / output / reasoning tokens | 229,438 / 6,562 / 0 | 39,252 / 696 / 0 |
| Tool activity | 21 calls; 13 reads; 7 edit attempts; 3 failed calls overall | 7 reads; 0 edits |

The first attempt's verifier error was `SyntaxError: Unexpected token ')'` at line 132. Inspection shows the rejection callback's `else` block was closed, but the callback itself was not closed before `.then(...)` ended. The repair spent its turn reasoning that the parentheses were balanced, did not identify the missing callback brace, and made no edit. This is a concrete failure to interpret actionable verifier feedback. Do not retry this exact condition.

The ordered invariants did not produce a correct first attempt. Because this is one sample, it does not isolate a causal effect from prompt wording. The repair did not improve correctness and consumed 39,252 additional input tokens. Together these two turns used 28 inferences, 268,690 input tokens, 7,258 output tokens, and 0 reported reasoning tokens. This provides no evidence that an automatic repair improves this task class.

## Monitor reconciliation

Persisted history is complete for both sessions, with no collection gaps: 648 events for the first attempt and 216 for the repair. Both databases passed `llm-monitor db check` (`integrity=ok`, no foreign-key violations). They and their WAL/SHM files remain raw, unstaged evidence.

- First live snapshot: connected; 1,247 SSE frames, 1,168 session-matched events, 850 text deltas, 21 tools, 6 successful file edits, 0 malformed/oversized frames and 0 reconnect gaps.
- Repair live snapshot: connected; 5,203 SSE frames, 5,136 session-matched events, 5,028 text deltas, 7 tools, no writes, 0 malformed/oversized frames and 0 reconnect gaps.
- Both bounded 180-second snapshots ended with `observation_deadline_limited` and `no_recent_events` after the worker stopped. These describe the observer window and idle tail, not missing persisted events. Both also retained `telemetry_incomplete` after streaming text had begun. In the installed Monitor source, that warning is set when activity is initially observed without incremental content and is not cleared when deltas later arrive; treat it as an early activity-only warning, not evidence of an SSE regression. `repeated_read_only_tools` was similarly retained after the repair's read-only phase.
- The earlier T1 database also has complete history and no gaps. Its live snapshot was not saved, so its exact `telemetry_incomplete` trigger cannot be recovered. Its `no_recent_events` and deadline warnings are consistent with a 7.8-second task observed for 120 seconds. No genuine SSE regression was demonstrated.

## Request provenance

The sanitized proxy recorded 21 first-attempt requests and 7 repair requests. Every matching capture shows model `qwen38-27b-q4km`, `max_tokens=16384`, `reasoning_effort=none`, streaming enabled, and five tools. Per-run capture counts equal the Monitor inference counts and their timestamps fall within the corresponding session windows. The proxy does not store an OpenCode session/message ID, so this remains timestamp correlation, not exact request identity. No broader proxy capture was added.

## Operating decision

- Keep local Qwen for small, bounded, low-risk edits or file-creation tasks only when an independent verifier can reject incorrect output. `reasoning_effort=none` avoids the observed reasoning-token drain but does not establish code correctness.
- Do not delegate asynchronous lifecycle/state-machine work, concurrency/cancellation logic, broad changes, or ambiguous tasks for direct acceptance. The revision-1.0.1 first attempt and repair both failed; escalate those tasks to Codex or another stronger model.
- Allow one repair only when the verifier gives a localized, actionable defect and the task is still within a bounded, inspectable scope. Stop when the worker makes no edit or cannot correctly explain the verifier failure; do not chain retries.
- Capture exact project/session/trial, model and limits, sanitized outbound parameters, inference usage/finish reasons, tool outcomes, scope and termination, first-edit latency, repair outcome, and both worker and end-to-end wall time.

This remains a small task sample, not a reliability estimate. Raw prompts, source snapshots, session contents, proxy rows, recorder logs, and SQLite databases are excluded from this committed summary.

## Final runtime check

After the trials, `lms ps --json` showed exactly one idle Q4_K_M model instance (`qwen38_23GB`, key `qwen38-27b-q4km`) at context 98,304. `local-agent opencode status --port 4196 --json` returned reachable/healthy on OpenCode 1.19.3. Loopback listeners were present on 1234, 1235, and 4196. The final Runmux inventory did not contain job 19; unrelated jobs 6 and 4 remained running. No service restart or model reload was needed.
