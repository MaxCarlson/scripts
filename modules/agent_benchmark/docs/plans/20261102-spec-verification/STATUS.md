# Specification verification study status

Branch `agent/spec-verification-policy-20261102`; implementation/runtime
qualification checkpoint `ee63bb32a6828952ad8ffdb6069b3e6f184a1254`. This
status update records the November 2, 2026 host preflight supplied by the user
and subsequent read-only sandbox checks. No inference, scored trial, service
start/restart, network change, merge, or push occurred.

## Current result

The policy implementation, frozen artifacts, run/resume integrity, Harbor
0.25.0 OpenCode v1 integration, content identities and native web-tool denial
are qualified offline or by the reported host preflight. A separate
two-trial beer-song SV0/SV1 acceptance procedure and one-task manifest are
prepared in `../../spec-verification-study.md` and
`../../spec-verification-beer-song-acceptance.json`.

The procedure is **not ready for live dispatch** under the stated
no-unauthorized-external-research control: the selected Harbor task declares
no network policy and Harbor 0.25.0 defaults an unspecified Docker network
policy to `PUBLIC`. The current suite does not pass a restrictive per-task
network policy into Harbor. Native web tool denial does not block shell egress.
Do not change Docker/host networking under this work item. A common, approved
egress regime that permits task setup and the local Monitor/model gateway but
prevents unauthorized task research is required before the smoke.

Effective decoding/output settings and in-memory model file binding remain
`RUNTIME_OBSERVATION_REQUIRED`, not implementation defects. Capture them from
SV0 request evidence and require the same values before proceeding to SV1.

## Final gate matrix

| Gate | Class | Result | Evidence | Blocks dispatch? | Remaining action |
| --- | --- | --- | --- | --- | --- |
| Frozen tasks and verifier trees | Mandatory | PASS | User-reported PS7 host preflight; recorded task/verifier fingerprints and current runner rehash | No | Runner rechecks exact selected tree before each trial |
| SV0/SV1 policy identities and persisted hashes | Mandatory | PASS | `sv0-unmodified-v1`; SV1 policy SHA `9874fc38201f32c215c212c8e5302bb9323fa575ca564b0f25db4e8dea3cbea3`; template SHA `f8db40dd1c1503fa482b40c5c7534fd4cf88327dfe4ed0ac029c789f0563f81a`; offline drift/resume tests | No | Each run revalidates artifacts before dispatch/resume |
| Harbor 0.25.0 and OpenCode v1 adapter | Mandatory | PASS implementation; task container version pending | Actual cached Harbor factory/render/runtime tests; host OpenCode 1.19.5 reported; adapter pins 1.19.5 | Container evidence required during trial | Verify Harbor install/version output before accepting result |
| Docker and host execution readiness | Mandatory | PASS per host preflight | User-reported Docker PASS; sandbox named-pipe check is denied | Recheck at actual run | Host suite run fails closed if unavailable |
| LLM Monitor content recording | Mandatory | PASS per host preflight | User reports gateway enabled, content recorder healthy, zero drops; current DB path preserved | Recheck before and after every task | Stop on unavailable gateway, unhealthy recorder, dropped observations, or incomplete capture |
| Model alias/provider/API route | Mandatory | PASS requested/host identity; effective request pending | Alias `qwen38_23GB`; key `qwen38-27b-q4km`; route is intended through Monitor; Chat Completions is explicitly requested | Runtime route must be checked before SV1 | Match Monitor content request and Harbor trial metadata |
| Model file candidate | Measurement | PASS candidate hash; loaded binding UNKNOWN | Candidate path/size/SHA in study doc; host inventory reports alias/key/size | Not alone | Correlate in-memory model identity to file if available; record unknown otherwise |
| Context, sampling, output and reasoning | Measurement | RUNTIME_OBSERVATION_REQUIRED | Context 98,304 reported by model inventory; adapter pins no temperature/top-p/top-k/model sampling seed/output limit/stops; UI default 32,768 is not effective state | Do not run SV1 until SV0 request and SV1 request settings are equal | Capture request parameters, context and reasoning controls; no assumed defaults |
| Native web tools | Mandatory | PASS for generated config; runtime confirmation pending | Actual Harbor 0.25.0 factory produced identical deny config for `websearch` and `webfetch` in SV0/SV1 | Confirm each trial's effective config | Check task-local generated OpenCode config or equivalent native evidence |
| Shell/container outbound network | Mandatory | FAIL | Harbor task has no network policy; pinned Harbor `DockerEnvironment` defaults unspecified policy to PUBLIC; suite does not select egress policy | **Yes** | Establish common authorized egress before dispatch; keep local gateway and required setup reachable |
| Concurrency/retries and evidence separation | Mandatory | PASS for procedure | `-j 1`, one task, zero Harbor retries; separate SV0/SV1 run roots; stop before SV1 if SV0 infra-invalid | No | Follow separate commands and inspect SV0 report before SV1 |
| Baseline/no-op equivalence | Validity | PASS simulated only | Actual Harbor renderer, mocked adapter and generated tool config compare as expected | Actual runtime comparison still required | Compare agent instruction, route, settings and tools in both artifacts |
| Independent score and complete evidence | Validity | UNKNOWN until run | No acceptance trial exists; host recorder preflight is healthy | Yes if evidence incomplete or infrastructure-invalid | Preserve Harbor raw job evidence and Monitor records, reconcile by trial ID |

## Evidence and exact checks

The latest host preflight is operator-reported from PowerShell 7 on
2026-11-02. It reported task/verifier, synthetic contract, Docker, OpenCode,
model alias and Monitor PASS. Its raw JSON was not provided in the worktree;
the source procedure is
[`Invoke-SpecVerificationPreflight.ps1`](../../../scripts/Invoke-SpecVerificationPreflight.ps1).
Keep the already running Monitor and recording DB unchanged. No repeated live
smoke was run.

Read-only model file hash:

```powershell
Get-FileHash -LiteralPath "$HOME\.lmstudio\models\local\qwen38-27b-q4km\Qwen3.8-27B-Q4_K_M.gguf" -Algorithm SHA256
```

Observed SHA-256 was
`e00082f779fa385cee8c68a3ec8833a75778cc87272240b942f74e0b8243e520` for
16,810,714,336 bytes. This identifies the on-disk candidate, not the loaded
memory mapping. `$HOME\.lmstudio\settings.json` showed UI `defaultContextLength`
32,768; it is not treated as the model inventory's 98,304 context.

Actual Harbor native web-config construction (cached Harbor interpreter,
factory-created SV0 and SV1 agents, no inference): PASS, exit 0. Both generated
identical per-job config with `websearch` and `webfetch` denied.

CLI help check `python -m agent_benchmark suite plan --help`: PASS, exit 0.
Structural one-task `suite plan` preview without Monitor mode emitted both
policy plans and same task/revision/model/API values, but returned exit 1 due
Docker named-pipe permission denial in sandbox. It is not the monitored plan:
the test has `llm_monitor_required=false` and recording off. The exact
monitored preview was also attempted with `-L` and no recovery flag; both arms
returned exit 2 `MONITOR_NOT_RUNNING` in the sandbox. No service was started.
These sandbox limitations do not contradict the later user-reported host
preflight.

Earlier focused checks remain recorded at checkpoint `ee63bb32`: 29 targeted
Agent Benchmark tests and Ruff passed; previous qualification recorded 79
Agent Benchmark tests and complete Benchmark Core tests (one skip). They were
not repeated because this update only changes documentation and adds the
one-task manifest.

## Live acceptance

Exact PowerShell 7 environment setup, default non-inference preview commands,
and two separate `suite run -x` commands are in
[`spec-verification-study.md`](../../spec-verification-study.md). The preview
requires Docker and Monitor availability but does not start them. The execution
commands must not be issued until the egress blocker is resolved and separate
live authorization is given. SV0 runs first. A valid scored failure is an
acceptable outcome; if SV0 is infrastructure-invalid or lacks complete
recording, stop and do not dispatch SV1. No retries or automatic continuation
are part of this procedure.
