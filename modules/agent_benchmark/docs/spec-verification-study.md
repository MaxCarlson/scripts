# Specification-verification policy study

Status: implementation and non-inference qualification are complete. No live
inference or scored Harbor trial has been authorized or launched. The proposed
18-trial pilot and the separately prepared two-trial acceptance are distinct.

## Intervention and frozen cohort

SV0 uses the explicit identity `sv0-unmodified-v1` and no prompt template. SV1
uses `sv1-specification-verification-v1`, policy source
[`sv1-v1.md`](../agent_benchmark/policies/sv1-v1.md), SHA-256
`9874fc38201f32c215c212c8e5302bb9323fa575ca564b0f25db4e8dea3cbea3`, and
generated template SHA-256
`f8db40dd1c1503fa482b40c5c7534fd4cf88327dfe4ed0ac029c789f0563f81a`.
Each run stores source bytes and template bytes in its own `policy/` directory;
execution and resume verify them against the saved manifest. The Harbor
OpenCode v1 adapter and all execution arguments are otherwise common.

The exploratory cohort remains the three Aider Polyglot tasks at revision
`f30b14415dd733c83627204bad0af69a89ceb46f`, three repetitions per condition
(18 planned trials). Historical results are not controls. The separate
acceptance smoke is exactly two attempts on beer-song, one per condition, with
SV0 first and SV1 dispatched only after SV0 has a completed, non-infrastructure
outcome. A valid verifier failure is acceptable; an infrastructure-invalid
SV0 stops the sequence.

The pre-registered exploratory order uses randomization seed `20261102`: shuffle
the nine task/repetition pairs, then select which condition runs first within
each pair. This remains a proposal and is not executed by the two-trial
acceptance.

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

Because the suite runs one repetition per task in each run, this exploratory
order requires one-task manifests and separate calls using the listed
repetition index. Its seed is recorded design metadata and does not set model
sampling randomness.

The selected Harbor cache trees were checked against recorded fingerprints;
the November 2, 2026 host preflight also reported all three task and verifier
trees PASS. The runner resolves the frozen registry revision and rechecks the
exact selected trees immediately before dispatch. Current fingerprints:

| Task | Harbor task SHA-256 | Verifier tree SHA-256 |
| --- | --- | --- |
| `polyglot_python_beer-song` | `79c3e5b6f2300c5de6ff862d212ea38d329ef31eb243e6a55da975c622b53376` | `01402f4ff69be049e7bc032c55215b018f19aa129021c3cf59d508764eb3a417` |
| `polyglot_python_bottle-song` | `7aa03a961facf5071aea121fb5ccb1a9519c133230025db0922a70803dab139c` | `c3c6d0bdf66833931416f8d9347285950fd895f9e648ebdd9b17c8223c0bdb2b` |
| `polyglot_python_bowling` | `2150b7c876f6ef7f988ec9c032ee4e873aa6e62b9591183a44e6317c64d7104f` | `cb919322a81c1733f40d8c60345aa3f164de9d23a9813d2b50d6a6d4027c3790` |

The source evidence is the preserved Harbor registry snapshot
`reports/agent-bench-suite/suite-20261102T185345-11c8981230/registry/registry.json`,
Harbor 0.25.0 `DatasetConfig`/`GitTaskId` resolution, and
`agent_benchmark.study_task_integrity`. The task SHA is Harbor's task-packager
digest. The verifier SHA is the sorted task-relative `tests/` path and file
digest aggregate defined by that module. The dataset revision is not a content
hash.

## Host evidence and settings provenance

On November 2, 2026, the user ran
[`Invoke-SpecVerificationPreflight.ps1`](../scripts/Invoke-SpecVerificationPreflight.ps1)
in PowerShell 7 on the Windows host. The reported checks passed for task and
verifier trees, synthetic instruction behavior, Docker access, host OpenCode,
LM Studio model alias, and LLM Monitor gateway/content recorder. Reported
Monitor state was gateway enabled at host `http://127.0.0.1:8788`, container
route `http://host.docker.internal:8788/v1`, `content` recording, healthy
recorder, zero dropped observations, and the existing database
`reports/agent-bench-suite/spec-verification-monitor-20261102.sqlite3`.
The running Monitor and database are preserved. The host's raw preflight JSON
was not supplied as a repository artifact; these host facts are operator
reported. The exact script and command are retained below for rechecking at
dispatch.

Read-only local inspection found the candidate model file
`$HOME/.lmstudio/models/local/qwen38-27b-q4km/Qwen3.8-27B-Q4_K_M.gguf`,
16,810,714,336 bytes, SHA-256
`e00082f779fa385cee8c68a3ec8833a75778cc87272240b942f74e0b8243e520`. Its
path/size agree with the host-reported alias `qwen38_23GB`, model key
`qwen38-27b-q4km`, and size. LM Studio's host model inventory reported
context length 98,304 and idle state. The filesystem digest proves the
candidate artifact identity, not that the in-memory model is bound to those
exact bytes. Quantization is reported as Q4_K_M by the model key and filename;
backend/runtime build and in-memory file binding remain unverified.

`$HOME/.lmstudio/settings.json` contains a UI default context length of 32,768;
that is not the loaded model's observed 98,304 context and is not used as an
effective value. The host OpenCode binary reported 1.19.5. The Harbor adapter
pins `opencode-ai@1.19.5`, and Harbor's install path verifies the executable in
the task container, but that container install has not yet run.

The study requests OpenCode model `openai/qwen38_23GB`, routed through
`llm-monitor/qwen38_23GB`, API format `openai_chat_completions`, with the
Monitor endpoint above. The study's `-Z 20261102` seed is design/randomization
metadata; it is not a model sampling seed. The shared Harbor v1 command
includes `--thinking` (OpenCode's JSON reasoning-event output flag) and
`--dangerously-skip-permissions`; no sampler, generation seed, stop sequence,
or output-token limit is pinned by the adapter. Temperature, top-p, top-k,
generation seed, output limit, stop behavior, reasoning configuration,
backend version, and actual request route therefore require observation from
each accepted Monitor request and native Harbor artifacts. Do not substitute
LM Studio defaults or the UI default for absent request evidence.

Both arms use Harbor jobs/concurrency 1, one attempt, zero Harbor retries,
the same frozen task, container and requested route. The beer-song task declares
1 CPU, 4 GiB memory and 10 GiB storage; actual host contention and runtime
resource use remain observations. The OpenCode run permits its ordinary shell
and task tools. Native web search and fetch are a separate restriction.

## Web tools and container network

In Harbor 0.25.0, the installed OpenCode adapter's
`disable_web_search=true` option writes per-job OpenCode permission denials for
`websearch` and `webfetch`. The study command passes that option in both arms.
An offline construction with the actual Harbor 0.25.0 factory confirmed that
SV0 and SV1 generate identical native web-tool config, and that selecting the
SV1 template does not change that config. This is a source-backed synthetic
check, not observation of a live container's config.

This does not deny network access from shell commands. The frozen beer-song
task's `task.toml` has no network policy. Harbor 0.25.0's `DockerEnvironment`
uses `NetworkMode.PUBLIC` when no network policy is supplied; its egress
sidecar is only enabled for a non-public policy. The study runner does not
select an alternate network policy. Therefore shell-level outbound internet
is **not restricted by this experiment**, and task-specific external reference
retrieval remains possible. Both arms would have equal egress, but this fails
the requirement that task-specific external information not be obtained from
unauthorized sources. It is a mandatory live-dispatch blocker for this
acceptance protocol, not a prompt-policy implementation defect. Do not claim
strict isolation from the native web-tool denial. No firewall, Docker, WSL,
DNS, or host network setting was changed.

The source check was against the managed Harbor 0.25.0
`harbor/environments/docker/docker.py` constructor and the frozen beer-song
task's `task.toml`; the latter declares resource limits but no network policy.
Harbor's pinned source includes a no-network Compose file and an egress
sidecar, but neither is selected by this study command.

Harbor also needs network access for task setup and installing the pinned
OpenCode package. An eventual approved network regime must preserve that setup
and the local Monitor/model gateway while preventing unauthorized external
task research, and must be identical across the two arms. The current suite
does not provide that task-container egress policy as a study CLI option.

## Final qualification gate matrix

`PASS` means evidence supports that condition at the named evidence boundary;
it does not imply all runtime facts are effective. `UNKNOWN` values remain
explicit. A live request can qualify measurement fields only after the
mandatory safety gates pass.

| ID | Class | Required condition | Evidence and observed result | Status | Blocks live acceptance? | Offline resolution? |
| --- | --- | --- | --- | --- | --- | --- |
| TASK-01 | Safety | Frozen task and verifier content matches the selected Harbor registry trees | Host preflight reported all three PASS; fingerprints above; runner resolves registry and rehashes before dispatch | PASS | No; recheck before each run | Yes; implemented and host-verified |
| POLICY-01 | Safety | SV0 unmodified instruction contract; SV1 frozen intended addition; run/resume hash integrity | Policy IDs/hashes above; synthetic Harbor rendering and freeze/drift tests; CLI binds reviewed SHA | PASS | No; run preflight checks again | Yes; implemented and tested |
| ADAPTER-01 | Safety | Harbor 0.25.0 dynamically loads the v1 adapter and installs OpenCode 1.19.5 | Cached Harbor 0.25.0 import/render tests; host OpenCode 1.19.5 reported; container version is pinned but not installed yet | PASS for implementation; container value RUNTIME_OBSERVATION_REQUIRED | Container version must be checked in trial evidence | No for actual task container |
| INFRA-01 | Safety | Docker reachable and Monitor content recorder healthy with no drops | November 2 host preflight reported Docker PASS, gateway/recorder PASS, dropped observations 0; live suite also rechecks | PASS at preflight | Recheck immediately before trial and at task boundary | No; host access required |
| ROUTE-01 | Safety | Correct loaded model, provider, protocol, and same route across arms | Host reports alias/key/context; Monitor gateway config is content-recording at 8788; plan requests `llm-monitor/qwen38_23GB` + Chat Completions. Actual request route not yet recorded | PASS for requested/host route; effective request RUNTIME_OBSERVATION_REQUIRED | Must validate request evidence before considering SV0 acceptable and before SV1 | No; needs first request |
| MODEL-01 | Measurement | Exact model-file identity and quantization | Candidate GGUF path, size, and SHA recorded above; alias/model key agree. In-memory binding and backend identity not exposed by preflight | PASS for file candidate; in-memory binding UNKNOWN | Not alone; reconcile with runtime before SV1 | Partly; loaded binding needs runtime evidence |
| SETTINGS-01 | Measurement | Equal context, sampling, limits, stops, and reasoning settings | Inventory context 98,304 observed; adapter does not pin decoding/output values; LM Studio UI default 32,768 is not effective evidence | RUNTIME_OBSERVATION_REQUIRED | Do not dispatch SV1 unless SV0 request and SV1 request show matching settings (prompt is excluded) | No; request evidence needed |
| TOOLS-01 | Safety | Native `websearch` and `webfetch` denied identically | Actual Harbor factory builds identical deny config for both arms; both command lines request the supported option | PASS for generated config; runtime config not yet captured | Verify native configuration in each task before outcome acceptance | Live artifact required |
| NET-01 | Safety | No unauthorized task-specific external research; identical shell egress controls | Frozen task omits network policy; Harbor Docker defaults unspecified policy to PUBLIC; experiment does not set a policy | FAIL (public egress permitted by default) | **Yes; current blocker** | Not with current suite CLI; requires a supported, separately approved common egress regime |
| EXEC-01 | Safety | Sequential, one attempt, zero retries; preserve results and stop on infrastructure failure | Suite plans one repetition, `-j 1`, Harbor max retries 0; separate arm output roots and commands below | PASS for procedure | No; operator follows stop rule | Yes |
| BASELINE-01 | Validity | SV0 preserves the existing v1 execution contract; only declared policy differs | Synthetic actual-adapter comparison and identical generated web config; SV1 template contributes instruction plus the declared template option | PASS, simulated | Actual instruction, agent/model route, config and request diff must be checked across live evidence | No for actual runtime parity |
| MEASURE-01 | Validity | Independent hidden verifier result and complete Monitor/Harbor evidence | Preflight recorder healthy; no smoke request exists | UNKNOWN until acceptance | Yes if recorder is incomplete, dropped, or trial infrastructure-invalid | No |

The supported network feature is available in Harbor, but the existing suite
does not currently carry a per-task `NetworkPolicy` into Harbor's job config.
This status report does not authorize changing that integration or host
network. Until an approved common egress policy is available, the acceptance is
**not ready for live dispatch**. Decoding settings are measurement gaps rather
than code defects; capture them from SV0 and require equality before SV1.

## Two-trial acceptance procedure (preview is the default)

The one-task manifest is
[`spec-verification-beer-song-acceptance.json`](spec-verification-beer-song-acceptance.json).
It fixes the dataset revision and task. Each `suite run` creates a separate
immutable run manifest and artifact directory. The commands below use the
existing suite CLI; no separate runner is introduced.

Open PowerShell 7 in the worktree and prepare the environment. This only sets
process-local interpreter/import variables and selects LiteLLM's bundled cost
map to prevent an unsolicited cost-map lookup. It does not touch services or
configuration.

```powershell
$repo = 'C:\Users\mcarls\src\scripts\.worktrees\spec-verification-policy-20261102'
$module = Join-Path $repo 'modules\agent_benchmark'
$manifest = Join-Path $module 'docs\spec-verification-beer-song-acceptance.json'
$policy = Join-Path $module 'agent_benchmark\policies\sv1-v1.md'
$coordinatorPython = 'C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe'
$env:HARBOR_025_PYTHON = 'C:\Users\mcarls\AppData\Local\uv\cache\archive-v0\6oHf_rWkqYo-3vQ-qABxe\Scripts\python.exe'
$env:LITELLM_LOCAL_MODEL_COST_MAP = 'True'
$env:PYTHONPATH = "$module;$repo\modules\benchmark_core;$env:PYTHONPATH"
$policySha = (Get-FileHash -LiteralPath $policy -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Location $module
```

Preview both arms first. These `plan` commands do not infer. They require the
host's existing Docker and Monitor to be reachable and content recording
healthy; there is intentionally no `-r/--recover-local` flag. Stop if either
plan is blocked, the task/revision/policy differs, or `-Q` rejects the policy.

```powershell
& $coordinatorPython -B -m agent_benchmark suite plan `
  -M $manifest -a opencode -m openai/qwen38_23GB `
  -L -U http://host.docker.internal:8788/v1 -H http://127.0.0.1:8788 `
  -R content -A openai_chat_completions -j 1 -S -I 1 -Z 20261102 -F
$sv0PlanExit = $LASTEXITCODE

& $coordinatorPython -B -m agent_benchmark suite plan `
  -M $manifest -a opencode -m openai/qwen38_23GB `
  -L -U http://host.docker.internal:8788/v1 -H http://127.0.0.1:8788 `
  -R content -A openai_chat_completions -j 1 -S `
  -P $policy -Q $policySha -I 1 -Z 20261102 -F
$sv1PlanExit = $LASTEXITCODE
if ($sv0PlanExit -ne 0 -or $sv1PlanExit -ne 0) { throw 'Preview failed; no run was dispatched.' }
```

The acceptance must remain stopped while `NET-01` is FAIL. After a separately
approved, identical egress regime has been configured and requalified, explicitly
authorize **one** run at a time with the suite's required `-x`. Before each
command, display and check the task, policy identity, model, endpoint, and
output root. The example uses a unique evidence root and fails rather than
overwriting an existing one:

```powershell
$acceptanceRoot = Join-Path $repo 'reports\agent-bench-suite\spec-verification-acceptance-20261102'
$sv0Root = Join-Path $acceptanceRoot 'SV0'
$sv1Root = Join-Path $acceptanceRoot 'SV1'
if (Test-Path $acceptanceRoot) { throw "Evidence root already exists: $acceptanceRoot" }
New-Item -ItemType Directory -Path $sv0Root,$sv1Root -Force | Out-Null

[pscustomobject]@{ Condition='SV0'; Task='polyglot_python_beer-song'; Revision='f30b14415dd733c83627204bad0af69a89ceb46f'; Model='openai/qwen38_23GB via LLM Monitor'; API='openai_chat_completions'; Policy='sv0-unmodified-v1'; Output=$sv0Root } | Format-List
# Execute only after separate explicit authorization and all blocking gates pass.
& $coordinatorPython -B -m agent_benchmark suite run `
  -M $manifest -a opencode -m openai/qwen38_23GB `
  -L -U http://host.docker.internal:8788/v1 -H http://127.0.0.1:8788 `
  -R content -A openai_chat_completions -j 1 -S -I 1 -Z 20261102 `
  -o $sv0Root -F -x 2>&1 | Tee-Object -FilePath (Join-Path $sv0Root 'dispatch.jsonl')
$sv0Exit = $LASTEXITCODE
[ordered]@{condition='SV0';exit_code=$sv0Exit;task='polyglot_python_beer-song';policy_id='sv0-unmodified-v1';inference_dispatched=$true} |
  ConvertTo-Json | Set-Content -LiteralPath (Join-Path $sv0Root 'command-result.json') -Encoding utf8NoBOM
Write-Output "SV0_EXIT_CODE=$sv0Exit"
if ($sv0Exit -ne 0) { throw 'SV0 was not a valid completed outcome; do not dispatch SV1.' }
```

Inspect SV0's `manifest.json`, `report.json`, task result and native Harbor
artifacts. A normal scored verifier failure can continue; missing/incomplete
recording, route/settings mismatch, or any `infrastructure_invalid` result
must stop before SV1. Do not call `resume --retry-invalid`. Only after SV0 is
accepted and its request settings/route are recorded, authorize SV1 in a
separate command:

```powershell
[pscustomobject]@{ Condition='SV1'; Task='polyglot_python_beer-song'; Revision='f30b14415dd733c83627204bad0af69a89ceb46f'; Model='openai/qwen38_23GB via LLM Monitor'; API='openai_chat_completions'; Policy='sv1-specification-verification-v1'; PolicySha256=$policySha; Output=$sv1Root } | Format-List
& $coordinatorPython -B -m agent_benchmark suite run `
  -M $manifest -a opencode -m openai/qwen38_23GB `
  -L -U http://host.docker.internal:8788/v1 -H http://127.0.0.1:8788 `
  -R content -A openai_chat_completions -j 1 -S -P $policy -Q $policySha `
  -I 1 -Z 20261102 -o $sv1Root -F -x 2>&1 |
  Tee-Object -FilePath (Join-Path $sv1Root 'dispatch.jsonl')
$sv1Exit = $LASTEXITCODE
[ordered]@{condition='SV1';exit_code=$sv1Exit;task='polyglot_python_beer-song';policy_id='sv1-specification-verification-v1';policy_sha256=$policySha;inference_dispatched=$true} |
  ConvertTo-Json | Set-Content -LiteralPath (Join-Path $sv1Root 'command-result.json') -Encoding utf8NoBOM
Write-Output "SV1_EXIT_CODE=$sv1Exit"
```

`-F` stores compact command events in the separate `dispatch.jsonl`; run
directories retain the immutable manifest, checkpoint, report, imported trial,
logs, and native Harbor job evidence. Keep the existing Monitor recording
database intact. Do not emit environment variables or credential values.
Reconcile each run's imported instruction/ATIF turn, model route and observed
generation parameters with its Monitor request before treating the pair as
comparable. The task does not need to pass for the trial to be accepted.

## Non-inference validation evidence

At checkpoint `ee63bb32a6828952ad8ffdb6069b3e6f184a1254`, the focused
qualification previously passed 29 Agent Benchmark tests and Ruff. This turn
did not repeat that suite. Additional checks performed for this report:

| Check | Exact result |
| --- | --- |
| Harbor option/config check using the cached Harbor 0.25.0 interpreter, actual `AgentFactory`, and SV0/SV1 adapters | PASS; both generated configs denied `websearch` and `webfetch` identically; policy did not alter tool config; exit 0 |
| `python -m agent_benchmark suite plan --help` | PASS; showed `-S`, `-P`, `-Q`, `-I`, `-Z`, monitor and API flags; exit 0 |
| SV0/SV1 `suite plan` structural preview with no Monitor flag (therefore not a final routed preview) | Both emitted the expected one-task plan, same task/revision/model/protocol, policy IDs differed as declared; both exit 1 because sandbox Docker named-pipe access was denied |
| Exact monitored SV0/SV1 plan preview (`-L`, existing endpoint, no recovery) | Both exited 2 with `MONITOR_NOT_RUNNING` in this sandbox; no service was started |
| Candidate GGUF SHA-256 | PASS, hash recorded above; read-only 16.8 GB file hashing |
| Actual Harbor native web config generation | PASS; exit 0 |

The sandbox preview without `-L` is only structural evidence: it reports
`llm_monitor_required=false`, recording `off`, and is not the final monitored
condition. The exact monitored preview command is prepared for the host above;
the operator-reported host preflight previously saw Docker and Monitor PASS.
The only remaining blockers are the common shell egress policy and the listed
runtime observations/dispatch authorization, not unimplemented policy or
manifest behavior.

## Outcomes and offline review

The hidden task verifier's pass/fail result is the primary outcome. A
false-green observation means a locally executed test or test suite passes
while the submitted implementation fails an independently checked
requirement. That discrepancy can reflect insufficient test coverage; it does
not by itself prove that the local oracle is incorrect. Keep separate fields
for local test pass, requirement coverage, oracle correctness, independently
verified task success, source correction after a failure, and changes to test
expectations. Where the trajectory cannot establish a field reliably, record
structured manual review as unknown/pending rather than scoring it.

Keep test quality outside canonical verifier scores. Collect test commands,
test exit results, requirement-review fields, input/output token observations,
request counts, tool calls, and wall-clock duration by the persisted trial ID.
Do not join token data by task name or directory-name conventions, and do not
print full prompts or reasoning traces into coordinator output.
