# Specification verification study: proposed pilot

Status: offline implementation under review. No inference or scored trial is authorized by this document.

Compare SV0 (`-S`, no policy file) with SV1 (`-S -P <sv1-v1.md>`) using the same isolated OpenCode v1 adapter. SV1 freezes its UTF-8 policy and generated template under the run directory; both are verified against the manifest before dispatch and on resume. Policies are limited to 16,384 bytes and Jinja delimiters are rejected. The legacy OpenCode route remains separate.

Plan SV1 with `agent-bench suite plan -c aider-python-10 -a opencode -S -P <policy-file>` and record the resulting policy SHA-256. An authorized run must supply that digest with `-Q`; a changed source policy is rejected. The built-in cohort contains ten tasks, so create a three-task custom cohort manifest before planning this pilot. Planning does not establish the effective model or hardware settings.

The intended cohort consists of `polyglot_python_beer-song`, `polyglot_python_bottle-song`, and `polyglot_python_bowling` from `aider/aider-polyglot` revision `f30b14415dd733c83627204bad0af69a89ceb46f`, three independent repetitions per condition: 18 trials. This is exploratory. The suite executes one repetition per task per run; the order across the 18 trials and its seed must be frozen before dispatch. Historical trials are not controls.

Use identical agent, model and model file, provider, API, context, sampling, output limits, timeout, permissions, web access, recording, hardware regime, concurrency one and zero retries for both conditions. Record unknown settings as unknown. Task and verifier content hashes must be collected independently before comparison. Declare the policy as the intended intervention in the benchmark-core comparison. Do not treat task IDs or revision-derived keys as content hashes.

Before live execution, independently verify Harbor 0.25.0 dynamic import and rendering, OpenCode 1.19.5 installation, the model route and weights, monitor recording, task and verifier identities, policy comparison compatibility, permitted web access, and contamination controls. Neither this document nor offline tests establish those runtime facts. The optimization baseline and no-op gates remain applicable.

Primary outcome is the independent verifier result. A local passing test and an independently failed requirement form a false-green observation; this does not establish an incorrect test oracle. Coverage, oracle correctness, altered expectations and source correction require explicit review. Track test commands and failures, token and request counts by trial ID, tool invocations and wall time separately from canonical scores.
