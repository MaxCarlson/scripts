# Specification verification study: proposed pilot

Status: offline implementation under review. No inference or scored trial is authorized by this document.

Compare SV0 (`-S`, no policy file) with SV1 (`-S -P <sv1-v1.md>`) using the same isolated OpenCode v1 adapter. SV1 freezes its UTF-8 policy and generated template under the run directory; both are verified against the manifest before dispatch and on resume. Policies are limited to 16,384 bytes and Jinja delimiters are rejected. The legacy OpenCode route remains separate.

Plan SV1 with `agent-bench suite plan -M docs/spec-verification-cohort.json -a opencode -S -P <policy-file> -I 1 -Z 20261102` and record the resulting policy SHA-256. An authorized run must supply that digest with `-Q`; a changed source policy is rejected. `-I` and `-Z` record the repetition and randomization seed. Planning does not establish the effective model or hardware settings.

The intended cohort consists of `polyglot_python_beer-song`, `polyglot_python_bottle-song`, and `polyglot_python_bowling` from `aider/aider-polyglot` revision `f30b14415dd733c83627204bad0af69a89ceb46f`, three independent repetitions per condition: 18 trials. This is exploratory. Historical trials are not controls. Both arms request Harbor's native web-tool denial. This does not establish network isolation or prevent shell access to the internet; enforcement remains a pre-dispatch gate.

The proposed order below uses seed 20261102: shuffle the nine task/repetition pairs, then randomly choose which condition runs first within each pair. The suite currently executes one repetition per task per run, so this order requires a one-task manifest per run and the listed `-I` and `-Z` values.

| Order | Task | Condition | Repetition |
| ---: | --- | --- | ---: |
| 1 | beer-song | SV0 | 3 |
| 2 | beer-song | SV1 | 3 |
| 3 | bottle-song | SV1 | 1 |
| 4 | bottle-song | SV0 | 1 |
| 5 | bottle-song | SV1 | 2 |
| 6 | bottle-song | SV0 | 2 |
| 7 | beer-song | SV0 | 1 |
| 8 | beer-song | SV1 | 1 |
| 9 | bowling | SV0 | 3 |
| 10 | bowling | SV1 | 3 |
| 11 | bowling | SV1 | 2 |
| 12 | bowling | SV0 | 2 |
| 13 | bottle-song | SV1 | 3 |
| 14 | bottle-song | SV0 | 3 |
| 15 | bowling | SV1 | 1 |
| 16 | bowling | SV0 | 1 |
| 17 | beer-song | SV0 | 2 |
| 18 | beer-song | SV1 | 2 |

Use identical agent, model and model file, provider, API, context, sampling, output limits, timeout, permissions, web access, recording, hardware regime, concurrency one and zero retries for both conditions. Record unknown settings as unknown. Task and verifier content hashes must be collected independently before comparison. Declare the policy as the intended intervention in the benchmark-core comparison. Do not treat task IDs or revision-derived keys as content hashes.

Before live execution, independently verify Harbor 0.25.0 dynamic import and rendering, OpenCode 1.19.5 installation, the model route and weights, monitor recording, task and verifier identities, policy comparison compatibility, permitted web access, and contamination controls. Neither this document nor offline tests establish those runtime facts. The optimization baseline and no-op gates remain applicable.

Primary outcome is the independent verifier result. A local passing test and an independently failed requirement form a false-green observation; this does not establish an incorrect test oracle. Coverage, oracle correctness, altered expectations and source correction require explicit review. Track test commands and failures, token and request counts by trial ID, tool invocations and wall time separately from canonical scores.
