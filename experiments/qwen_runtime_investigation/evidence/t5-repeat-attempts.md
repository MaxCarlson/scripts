# T5 repeat phase — infrastructure attempts

This file records two attempts to begin the requested fresh 8,192-token T5
repetitions. The first was stopped before dispatch. The second reached one
inference but was cancelled by the resource guard before a usable response.

| Experiment | Condition | Correctness | Response / termination | Inferences | Reasoning / output tokens | Wall time / first write | Infrastructure |
|---|---|---|---|---:|---|---|---|
| `EXP_20261029_165520` | `qwen-async-behavior`, omitted/default, 98,304 context, 8,192 output, no seed, `file-tools-v1`, OpenCode 1.19.3 at 4196 | N/A | No worker session; no finish reason | 0 | N/A | No inference; no first write | Pre-dispatch guard rejected at 90.3% RAM (limit 90%) |
| `EXP_20261029_165742` / `ses_e77675d30ffeE202ThTugrVNLz` | Same omitted/default condition, fresh session | Infrastructure error; no correctness verdict | Worker cancelled by `ResourceLimitExceeded`; session idle afterward; no finish reason | 1 observed inference event, incomplete | Monitor row reports 0 input / 0 output / 0 reasoning and 4.111 s, but `finish_reason` is null, so actual generated usage is unknown | 5.8 s; no tool call or first write | Post-dispatch RAM reached 90.6% (limit 90%); host available RAM was 5.8 GiB |

The run wrote `experiment-failure.json` and `benchmark.log` under
`evidence/runs/EXP_20261029_165520/`. No automatic retry occurred. The benchmark
log sampled host RAM at 89.3%, 89.4%, and 89.7% shortly before the transition
check rejected 90.3%. After the CLI exited, independent `psutil` reads showed
89.5%, then 89.5%, 89.8%, and 90.3% over the following 20 seconds. This
indicates fluctuating host pressure; this first attempt has no time-correlated
process sample. No memory owner was terminated or unloaded.

For `EXP_20261029_165742`, the runner log contains 44 resource samples from
86.0% to 91.6% RAM use, with 8.63 GiB down to 5.20 GiB available; device VRAM
samples were 29.04–29.28 GiB used. The runner's abort threshold was crossed at
90.6%. After the worker and recorder stopped, `psutil` read 89.5% / 6.45 GiB
available. This is partial reclamation evidence, not process attribution. The
Monitor captured complete lifecycle coverage and `idle` → `inference_running` →
`idle`, but no tool events and no finished token/finish record. Its one inference
row had zero *reported* token counts and no finish reason; do not interpret those
zeros as proof that generation used no tokens.

A read-only process snapshot after the abort showed `llama-server.exe` (PID 3916,
parent `LM Studio.exe`) at 17.54 GiB working set. This is the model-server
process, not a measurement attributable to the 4.111-second inference. The
LM Studio API still reported the exact Qwen key IDLE after the attempt. The
server working set was not sampled at dispatch, so a pre/post process delta is
unavailable.

The benchmark report returned `INFRASTRUCTURE_ERROR` at 5.7 s. Its hidden
verifier encountered `NotImplementedError` because the source remained the
untouched starter. This is not a correctness failure or reasoning exhaustion.

Before launch, read-only `local-agent model verify` confirmed the isolated
OpenCode endpoint at `http://127.0.0.1:4196`, model alias `qwen38_23GB`, exact
LM Studio key `qwen38-27b-q4km`, Q4_K_M quantization, 98,304 context, 8,192
configured output, and LM Studio model status `IDLE`. The runner's device-level
sample was 31.46 GiB / 34.19 GiB VRAM used with 0% utilization; it is not
process-attributed. Afterward, OpenCode 4096 remained healthy and its
`/session/status` endpoint returned an empty active-session set; it was not
used or modified. OpenCode 4196 was healthy and the cancelled session was
idle. The latest host sample was 89.4% / 6.54 GiB available, still close enough
to the limit that the next trial should wait for more headroom. No process was
stopped, and no model was unloaded.

The remaining request is two fresh *completed* trials per condition at T5/8,192
(omitted/default and explicit `none`). Neither attempt above counts toward the
model-result denominator. Keep `-M 90` enabled and dispatch only with enough
headroom that the threshold is unlikely to be crossed during inference.
