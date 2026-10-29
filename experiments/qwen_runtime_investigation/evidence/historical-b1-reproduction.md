# Historical Runmux B1 lifecycle/visibility failure

## Preserved failure

Source evidence is the separate Runmux pilot evidence worktree at
`C:\Users\mcarls\src\scripts\.worktrees\runmux-llm-monitor-local-gpu-pilot-20261029-evidence\task-b1-medium-16384-report.md`.
The source worktree was clean at baseline commit
`392cf349138845dd9d867d3b3bddeeda97594b0a` (`codex/local-runmux-llm-monitor-local-gpu-pilot-20261029`).

The report identifies the task as **Runmux LLM Monitor Task B1 — Lifecycle and
Visibility State**. It records OpenCode 1.19.3, LM Studio 0.4.26.0, Qwen3.8-27B
Q4_K_M (`qwen38_23GB` / `qwen38-27b-q4km`), `local-worker`, selected variant
`medium`, context 98,304, and output 16,384. The run had four inferences, 16,587
session reasoning tokens, 339 ordinary output tokens, four successful read-only
tool events, and zero edits. The final inference used exactly 16,384 reasoning
tokens, zero ordinary output tokens, and ended `finish=length`. That is a single
inference exhausting its generation allowance; the 16,587 reasoning total is a
separate session sum across four inferences. The session became idle, the worktree
was clean, and no repair or retry was made.

The report does not preserve the full worker prompt, the exact four-tool
sequence, or a dispatch-time permission snapshot. It notes that actual outbound
LM Studio request fields were not captured. The selected `medium` variant is
therefore configuration metadata, not proof of model-side effort behavior.

The pinned overview/telemetry plan (`00-implementation-plan.md`) has SHA-256
`4055CDBB9AD533D5DAB2875947CC43036E1523012524050DF0CE38A6E6DCF392`; its
Task 3 contract is the closest surviving prompt source. The matching
`dashboard.js` at that baseline has SHA-256
`9CEDCFDF738BB614DFE13C6FFA681D6C8A6F9DC9BC41A687D2282141FD32EE5D`.
The preserved B1 summary report has SHA-256
`05393D72D1897C2029D59557CACC940E83530966EE9265A40994EA19FAA1D045`.

## Closest reproducible benchmark fixture

The reusable fixture `qwen-runmux-polling-lifecycle` is integrated into
`modules/agent_benchmark/agent_benchmark/tasks/`. Its behavior contract follows
the pinned Runmux overview/telemetry Task 3 plan at the source baseline above:
selected run and non-minimal mode gate polling; requests are single-flight;
superseded runs are aborted; hidden pages suspend polling and resume immediately;
lock, deselect, and close clean up; terminal states stop; transient errors retry.
The fixture is self-contained and uses the existing Agent Benchmark trial runner,
scope audit, telemetry, and correctness verifier.

Reproduction differs from historical B1 in these known ways:

- The original prompt is unavailable; the new prompt is a precise reconstruction
  from the source plan's Task 3 requirements and the B1 title.
- The fixture isolates the polling lifecycle in a synthetic JavaScript module
  instead of editing the full Runmux dashboard and its integration tests.
- The new task uses `file-tools-v1`; historical effective permissions were not
  recorded. Four historical read-only tool events were observed, but that does
  not establish the full available tool set.
- The historical session used port 4096 and selected `medium`; the experiment
  uses the isolated OpenCode server on 4196 and compares omitted/default against
  the explicit `reasoning_effort=none` profile at the historical 16,384 output
  ceiling. Live outbound provider fields remain unverified.

This is a controlled regression analogue, not an exact replay. Do not overwrite
the historical failure record with new results.

## Resource gate and next sequence

The earlier explicit-`none` 16,384 attempt was rejected before dispatch at
90.2% host RAM against the existing 90% guard; it created no model session and
is not a model result. Subsequent read-only host samples during this checkpoint
were 94.1%, 93.5%, 93.5%, and 93.5%. Process enumeration and local service
inspection are restricted in the execution environment, so this RAM cannot be
reliably attributed to a process and no allocation was unloaded. Preserve the
guard and do not dispatch until preflight passes.

First run the requested additional T5 trials at output 8,192, serially and with
fresh sessions: omitted/default and `none`, two or three trials per condition.
Then run one matched omitted/default versus `none` comparison on this B1 analogue
at output 16,384. Only after that comparison should a genuinely harder
multi-file task be screened. Record failures and infrastructure blocks as-is.

No completed Agent Benchmark comparison trial had produced `finish=length` at
the time this section was written. The preserved historical B1 attempt did;
keep per-inference usage separate from session totals.

## Subsequent controlled analogue results

The historical claim above remains unchanged: its original prompt and
dispatch-time permissions are missing, so it cannot be exactly replayed. The
synthetic fixture has since been run under omitted/default reasoning and
explicit `reasoning_effort=none`; results and RAM measurements are in
[`ram-b1-t5-checkpoint.md`](ram-b1-t5-checkpoint.md).

The default analogue reproduced the no-edit exhaustion: four read-only
`tool-calls` inferences followed by a fifth inference ending `length` at 16,384
reasoning tokens and zero ordinary output. The `none` analogue used zero
reasoning, made edits, and finished normally, but the independent verifier
found that it failed to resume polling immediately after an in-flight response
when the page became visible. This is an incorrect implementation of an
explicit fixture requirement, not an infrastructure failure. The original
verdict is preserved; no repair or rescore has been applied.
