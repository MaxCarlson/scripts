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

Use identical agent, model and model file, provider, API, context, sampling, output limits, timeout, permissions, web access, recording, hardware regime, concurrency one and zero retries for both conditions. Record unknown settings as unknown. Declare the policy as the intended intervention in the benchmark-core comparison. Do not treat task IDs or revision-derived keys as content hashes.

The cached task trees were independently hashed offline using Harbor 0.25.0 `Packager.compute_content_hash`; all three match the corresponding historical Harbor lock files, which name the pinned source revision. The verifier hash below is SHA-256 of the sorted sequence of each file's task-relative UTF-8 POSIX path, a NUL byte, and its binary SHA-256 digest, over all files under `tests/`. Harbor's `GitTaskId.get_local_path()` resolves the verified URL, revision and registry path to these exact cache trees. The study runner checks both hashes immediately before each dispatch and fails closed if a tree is absent or differs. Existing study runs whose saved registry evidence lacks `git_path` must be replanned.

| Task | Harbor task SHA-256 | Verifier tree SHA-256 |
| --- | --- | --- |
| beer-song | `79c3e5b6f2300c5de6ff862d212ea38d329ef31eb243e6a55da975c622b53376` | `01402f4ff69be049e7bc032c55215b018f19aa129021c3cf59d508764eb3a417` |
| bottle-song | `7aa03a961facf5071aea121fb5ccb1a9519c133230025db0922a70803dab139c` | `c3c6d0bdf66833931416f8d9347285950fd895f9e648ebdd9b17c8223c0bdb2b` |
| bowling | `2150b7c876f6ef7f988ec9c032ee4e873aa6e62b9591183a44e6317c64d7104f` | `cb919322a81c1733f40d8c60345aa3f164de9d23a9813d2b50d6a6d4027c3790` |

Harbor 0.25.0 dynamic import and synthetic rendering have been checked in the cached environment. Before live execution, verify OpenCode 1.19.5 installation, the model route and weights, monitor recording, the actual execution task and verifier identities, policy comparison compatibility with observed controls, permitted web access, and contamination controls. Offline tests do not establish those runtime facts. The optimization baseline and no-op gates remain applicable.

| Control | Offline evidence | Remaining observation |
| --- | --- | --- |
| Harbor adapter | Cached Harbor 0.25.0 factory imported the repository adapter and rendered both synthetic prompts. A mocked adapter invocation retained v1 flags and omitted forced fake VCS. | Verify OpenCode 1.19.5 was installed and its live invocation matches the recorded command. |
| Policy | SV0 has explicit `sv0-unmodified-v1` identity; SV1 source SHA-256 is `9874fc38201f32c215c212c8e5302bb9323fa575ca564b0f25db4e8dea3cbea3`. The plan and frozen artifacts carry separate template and source hashes. | Verify the actual agent-facing instruction digest during a separately authorized qualification. |
| Dataset | Cached task trees match historical Harbor task-lock digests at the pinned revision; verifier hashes are listed above. | Match the task and verifier trees actually selected for execution. |
| Model and route | `openai/qwen38_23GB`, monitor routing and Chat Completions can be requested in the plan. | Loaded model-file digest, quantization, provider route, backend and effective context/sampling/output settings are unknown. |
| Tools and web | Both study commands request `disable_web_search=true`; Harbor accepts the option. | Verify the native denial and separate shell/network controls. |
| Recording and resources | One concurrent job and zero retries are planned. A read-only monitor plan could not see a running monitor in the sandbox. | Verify monitor recording readiness, resource regime and absence of dropped observations in the execution environment. |
| Comparison | Benchmark Core accepts a declared SV0/SV1 prompt intervention only when the remaining contract is complete and equal; missing values are refused. | Supply actual task/verifier digests and observed controls; current planned manifests do not establish equivalence. |

## Non-inference host procedure

Run in PowerShell 7 from the worktree. Replace the interpreter paths if the cache or virtual environment has moved. `-OutputPath` is optional; when provided it must not already exist. The script emits `spec-verification-host-preflight-v1` JSON, runs only synthetic tests and read-only probes, and returns exit 1 for a definite identity or synthetic-contract failure. UNKNOWN checks do not imply readiness. It never emits raw monitor responses, model output, or credentials.

```powershell
$harborPython = 'C:\Users\mcarls\AppData\Local\uv\cache\archive-v0\6oHf_rWkqYo-3vQ-qABxe\Scripts\python.exe'
$coordinatorPython = 'C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe'
pwsh -NoProfile -File .\modules\agent_benchmark\scripts\Invoke-SpecVerificationPreflight.ps1 `
  -HarborPython $harborPython -CoordinatorPython $coordinatorPython
$LASTEXITCODE
```

For a later separately authorized study command, set `$env:HARBOR_025_PYTHON = $harborPython` in that PowerShell process. The runner uses this same Harbor interpreter for cache selection, hashing, and execution. The qualification process sets `LITELLM_LOCAL_MODEL_COST_MAP=True` to use LiteLLM's bundled cost map and avoid a network lookup; it restores the caller's environment afterward.

If the host script reports a loaded alias, inspect its allowlisted metadata with `lms ps --json | ConvertFrom-Json | Select-Object identifier,modelKey,status,contextLength,sizeBytes`, then check `$LASTEXITCODE`. For an independently identified local model file, record only its digest with `Get-FileHash -LiteralPath '<exact model file path>' -Algorithm SHA256 | Select-Object Algorithm,Hash`. These checks do not establish effective sampler or output settings; obtain those from the runtime's read-only configuration and request-provenance evidence. Do not put credentials, raw prompts or full service responses into the evidence file.

Primary outcome is the independent verifier result. A local passing test and an independently failed requirement form a false-green observation; this does not establish an incorrect test oracle. Coverage, oracle correctness, altered expectations and source correction require explicit review. Track test commands and failures, token and request counts by trial ID, tool invocations and wall time separately from canonical scores.
