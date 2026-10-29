# B1 repair, numeric reasoning budget, and planning comparison

Date: 2026-10-29. All worker runs used the isolated OpenCode 1.19.3 server on
port 4196 and the loaded LM Studio 0.4.26.0 model key
`qwen38-27b-q4km` (API alias `qwen38_23GB`), Q4_K_M, context 98,304. No
inference was sent to the preserved OpenCode 4096 server. Host RAM was 82.5%
used before the first run and 81.1% afterward, below the unchanged 90% guard.
The OpenCode session-status endpoint was empty after the runs.

## Preserved B1 first attempt and one repair

The original B1 analogue `EXP_20261029_174653` remains failed and unchanged.
It ended normally with `finish=stop`, but its independent verifier found the
visibility-resume behavior produced 1 sample where 2 were required. It made
its first edit after 18.097 s. The first-attempt score remains failed.

For the single repair, a disposable Agent Benchmark fixture was initialized
from the preserved original S1 implementation and public tests. The worker was
told only the failing assertion and required behavior: after visibility resumes
while a request is in flight, deliver that response and issue exactly one
immediate follow-up sample when it settles, while retaining single-flight
behavior. No reference implementation or hidden expected code was included.
The repair used a fresh OpenCode session, the same explicit `none` profile,
98,304 context, 16,384 output ceiling, `file-tools-v1`, and a 60-second
`canonical-60s` budget.

| Measure | Original first attempt | One repair |
|---|---:|---:|
| Correctness | Fail, preserved | Pass, separate result |
| Inferences | 11 | 9 additional |
| Input tokens | 71,371 | 58,800 additional |
| Reasoning tokens | 0 | 0 additional |
| Ordinary output tokens | 3,196 | 2,364 additional |
| First edit | 18.097 s | 11.052 s |
| OpenCode user-turn elapsed | 30.675 s | 23.750 s |
| Final finish / termination | `stop`, confirmed | `stop`, confirmed |
| Tool activity | read 9, write 1, edit 3 | read 8, edit 3 |

The two turns used 20 inferences, 130,171 input tokens, 5,560 output tokens,
and 0 reported reasoning tokens. Their measured OpenCode turn durations sum to
54.425 s. Agent Benchmark reported 25.3 s for the repair worker phase. The
repair passed both the runner's independent verifier and a fresh direct run of
`verifier/check.py` against the archived repair S1 snapshot. No Codex or
coordinator code was changed. The original first-attempt score was not
replaced, repaired in place, or rescored.

Evidence: original `runs/EXP_20261029_174653/.../trial-001` (session
`ses_e773a55caffeHj15DIE5tQPZrS`), repair
`runs/EXP_20261029_181249/.../trial-001` (session
`ses_e77229381ffeCr10vlMTXdWKRW`), and the disposable starting fixture
`repair-fixtures/b1-none-visibility-resume-repair-01`.

## Separate fresh single-stage B1 result

Before the repair, one new fresh B1 attempt (`EXP_20261029_181006`) used the
same `none`, 98,304-context, 16,384-output, and `file-tools-v1` settings with a
180-second budget. It failed a different assertion: two in-flight requests
were observed where the single-flight invariant requires one. This was a
worker correctness failure, not a provider, transport, tool-permission,
termination, or verifier-infrastructure failure.

It completed with `finish=stop`, confirmed termination, 12 inferences, 114,607
input tokens, 8,023 output tokens, 0 reasoning tokens, 15 successful tool
calls (9 reads, 3 writes, 2 edits, 1 grep), a first edit at 15.875 s, and a
65.638-second OpenCode turn (session `ses_e77251202ffejX5jWasdTRD7S2`). This
separate fresh first attempt was not repaired.

## Numerical reasoning-token budget

Direct, serial probes used `POST /v1/chat/completions` against the exact loaded
model, with the same deterministic arithmetic prompt, temperature 0, seed 17,
and `max_tokens=8192` as the preserved omitted-field baseline. The prompt and
generated text were not saved.

| Request | HTTP | Reasoning tokens | Completion tokens | Result |
|---|---:|---:|---:|---|
| Omitted numeric field (baseline) | 200 | 65 | 71 | Correct answer |
| `reasoning_budget: 16` | 200 | 65 | 71 | Correct answer; requested cap exceeded |
| `thinking_budget: 16` | 200 | 65 | 71 | Correct answer; requested cap exceeded |

Both numeric fields were accepted by the endpoint but did not enforce the
requested cap in this test. The exact OpenAI-compatible Chat Completions docs
list `max_tokens` among supported payload parameters and do not list a
numeric reasoning budget. LM Studio's native `/api/v1/chat` docs expose
`max_output_tokens` and categorical reasoning settings (`off`, `low`,
`medium`, `high`, `on`), not a numeric reasoning-token cap. This is evidence
for the tested LM Studio route and Qwen GGUF, not a claim about other models or
endpoints. The useful verified control remains `reasoning_effort=none`; the
agent trials' project configuration requested it and session histories report
zero reasoning, but no live outbound OpenCode request capture was correlated
to these sessions.

Sanitized request and result fields: `numeric-budget-probes.json`. References:
[LM Studio Chat Completions](https://lmstudio.ai/docs/developer/openai-compat/chat-completions)
and [LM Studio native chat](https://lmstudio.ai/docs/developer/rest/chat).

## One bounded plan-then-execute comparison

Because the repair passed, one comparison used the same B1 starter and hidden
verifier. The planning stage was one direct call to the exact model with
`reasoning_effort=none`, `max_tokens=4096`, temperature 0, seed 17. It produced
a 796-token plan with 1,444 input tokens, 0 reasoning tokens, `finish=stop`,
and took 6.531 s. Only the ordinary plan text and sanitized scalars were
retained; the planning prompt was not saved.

The plan was added to a fresh Agent Benchmark task prompt, then executed once
through the normal OpenCode worker and independent verifier using
`reasoning_effort=none`, 98,304 context, 8,192 output, `file-tools-v1`, and a
180-second task budget. The execution failed the same visibility-resume
assertion as the original B1 first attempt (1 sample instead of 2). It ended
with `finish=stop` and confirmed termination. It used 11 inferences, 91,568
input tokens, 4,086 output tokens, 0 reasoning tokens, 12 successful tool
calls (9 reads, 1 write, 2 edits), first edit at 15.379 s, and a 33.975-second
OpenCode turn. The combined planning-plus-execution cost was 12 inferences,
93,012 input tokens, 4,882 output tokens, 0 reasoning tokens, and 40.506 s
of measured stage/turn time (the benchmark worker-phase display was 35.3 s).

This one comparison did not establish a correctness benefit from planning:
both single-stage and plan-then-execute fresh attempts failed, on different
assertions. The staged run used less output and elapsed time, but the sample is
too small to call that a reliable improvement. Evidence is in
`b1-plan-stage-none.json`, `b1-plan-stage-none.txt`, and
`runs/EXP_20261029_181657/.../trial-001` (session
`ses_e771eceafffe1ZxozZwS9sPnRU`).

## Telemetry coverage and interpretation

Each trial has a correlated OpenCode session ID and a persisted `session.json`
with per-inference tokens, finish reasons, tool results, and edit timestamps.
The LLM Monitor history queries for the new sessions returned `found=false`;
the corresponding sanitized query results are
`monitor-history-b1-fresh.json` and `monitor-history-b1-repair.json`. Thus the
token and tool data above come from persisted OpenCode session evidence, not
Monitor, and there is no Monitor-side coverage for these new sessions. No
device memory measurement is attributed to an individual inference. The
plan-execution Monitor lookup also returned `found=false` in
`monitor-history-b1-plan-execution.json`.

## Assessment

- The preserved reasoning-exhaustion failure remains distinct from these
  `none` correctness failures. None of the new sessions ended with
  `finish=length`; each ended with `stop`.
- `none` avoided reported reasoning-only expenditure and allowed quick edits,
  but did not guarantee correct lifecycle behavior.
- A single verifier-guided repair succeeded without coordinator code edits;
  that is evidence that bounded recovery can work, not yet a reliability rate.
- A numeric cap independent of `max_tokens` was not found on the OpenAI route
  used by OpenCode. The tested candidate fields were silently accepted but
  did not cap reported reasoning tokens.
- Do not claim a reliable profile from these trials. Retain independent
  verification and the one-repair limit as a candidate workflow. Keep
  `reasoning_effort=none` at 8K/16K as a tested actionability aid, with
  correctness and live request-field delivery still separately verified.
- No bridge or LM Studio response-delivery defect was established. The
  observed failures are incorrect worker implementations after normal tool
  execution and normal completion.
