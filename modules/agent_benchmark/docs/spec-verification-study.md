# Specification-verification policy study

**Dispatch interlock:** Study dispatch currently fails with
`NETWORK_QUALIFICATION_UNAVAILABLE` before Docker readiness checks. The existing
probe report is not bound to the task snapshot or execution environment and
cannot authorize dispatch. A verified receipt mechanism remains to be built;
the commands below are historical and cannot yet execute a study trial.

Status: implementation and non-inference qualification are complete, but
container qualification found an external-DNS-resolution leak. No live
inference or scored Harbor trial has been authorized or launched. The
two-trial acceptance remains blocked until DNS isolation passes or an approved
equivalent control is established. The proposed 18-trial pilot is separate.

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

| Task | Harbor task SHA-256 | Original = derived verifier SHA-256 |
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

## Study-only network metadata overlay

The suite now materializes a run-owned copy under
`<run>/study-network/tasks/<task-id>`. It verifies the original selected task
and verifier trees against the frozen hashes above, then modifies only the
root `task.toml` by adding the policy below. The original task cache, registry,
instructions, verifier files, fixtures, expected outputs, and score semantics
are not edited. Before Harbor dispatch and resume, the runner verifies the
copied tree, unchanged verifier, exact metadata delta, policy identity, and
recorded original hashes. Harbor executes the run-owned copy through its
supported `--path` option while the manifest retains the source Git URL and
commit provenance.

```toml
[environment]
network_mode = "public"

[agent]
network_mode = "allowlist"
allowed_hosts = ["host.docker.internal"]

[verifier]
network_mode = "no-network"
```

`public` applies to task setup (including dependency/OpenCode setup),
`allowlist` to agent execution, and `no-network` to verification. Both arms
use this same declared policy. Harbor's hostname allowlist is not port-specific:
allowing `host.docker.internal` permits contact with other host services, not
only the Monitor on port 8788. The probe establishes Monitor HTTP reachability,
not isolation from other host ports.

Exact original and derived hashes from the actual cached Harbor 0.25.0 trees
are recorded in the ignored evidence file
`modules/agent_benchmark/.pytest_tmp_root/sv-network-task-identities.json`.
For every task, the original Harbor task digest and verifier digest match the
frozen values above, and the derived verifier digest equals the original
verifier digest. The added full-tree and `task.toml` digests identify the one
declared metadata overlay. The real-cache overlay test checks all three tasks
without changing the source cache.

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

Shell egress is governed by the Harbor task policy above, and was probed inside
a synthetic Harbor 0.25.0 Docker task using the same three phase policies.
Harbor parsed the intended configuration and enabled its egress sidecar. An
`OPTIONS` request to the actual
`host.docker.internal:8788/v1/chat/completions` route returned HTTP 405,
confirming the POST-only gateway route is reachable without sending a
completion request. Direct DNS to `1.1.1.1`, unlisted-host TLS with SNI, and
direct-IP TLS without SNI were blocked. The verifier phase could not reach the
Monitor, and Harbor removed the synthetic container after the probe.

However, the container's default Docker resolver returned two addresses for
`example.com`. Direct DNS to `1.1.1.1` was refused, but name resolution through
Docker's embedded resolver succeeded. The probe does not capture upstream
packets, so it cannot establish whether Docker forwarded that lookup or served
a cached answer. The strict gate requires name resolution to be denied, so it
correctly reports `FAIL`. The effective allowlist blocks the tested
connections but does not block use of the configured resolver. No host
firewall, Docker daemon, WSL, DNS, or network configuration was changed to
work around this limitation.

The supported Harbor policy blocks the tested direct external connection
paths and preserves local Monitor reachability, but it is not strict shell
egress isolation. The hostname allowlist also permits access to other host
services. Both limits must be resolved through an existing supported,
approved common infrastructure control or explicitly accepted by a revised
study threat model, then requalified before dispatch. No custom firewall,
sidecar patch, or installed Harbor modification was introduced.

A narrowly scoped protocol alternative for separate review is to permit name
resolution through Docker's embedded resolver while retaining the tested
connection allowlist, and explicitly accept that resolver queries could
potentially carry data. This would relax the current “external DNS denied”
condition and would not qualify as strict external isolation. The host-wide
reachability implied by `host.docker.internal` would also need explicit
acceptance if other host services are in scope. Neither protocol change is
currently approved.

Harbor's declared network-policy contract and phase configuration are described
in the [Harbor 0.25.0 network-policy documentation](https://github.com/harbor-framework/harbor/blob/v0.25.0/docs-mintlify/tasks/network-policies.mdx),
[task configuration model](https://github.com/harbor-framework/harbor/blob/v0.25.0/src/harbor/models/task/config.py),
and [Docker environment implementation](https://github.com/harbor-framework/harbor/blob/v0.25.0/src/harbor/environments/docker/docker.py).

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
| NET-01 | Safety | Agent shell can reach the local Monitor but cannot reach unauthorized external services or use external DNS | Actual Harbor 0.25.0 Docker probe: sidecar enabled; `allowlist` effective; OPTIONS to POST-only Monitor gateway route returned 405; direct `1.1.1.1` DNS refused; unlisted SNI and direct-IP TLS reset; Docker embedded resolver returned `example.com`; verifier `no-network` denies Monitor | FAIL (name resolution remains available through Docker resolver; host alias is not port-specific) | **Yes** | Derived task metadata and Harbor policy are implemented; strict DNS/host-port isolation requires an existing supported control or an explicitly accepted study threat model |
| EXEC-01 | Safety | Sequential, one attempt, zero retries; preserve results and stop on infrastructure failure | Suite plans one repetition, `-j 1`, Harbor max retries 0; separate arm output roots and commands below | PASS for procedure | No; operator follows stop rule | Yes |
| BASELINE-01 | Validity | SV0 preserves the existing v1 execution contract; only declared policy differs | Synthetic actual-adapter comparison and identical generated web config; SV1 template contributes instruction plus the declared template option | PASS, simulated | Actual instruction, agent/model route, config and request diff must be checked across live evidence | No for actual runtime parity |
| MEASURE-01 | Validity | Independent hidden verifier result and complete Monitor/Harbor evidence | Preflight recorder healthy; no smoke request exists | UNKNOWN until acceptance | Yes if recorder is incomplete, dropped, or trial infrastructure-invalid | No |

Harbor's supported per-task metadata is now carried in the run-owned snapshot
and selected by the runner for both arms. Actual container enforcement is
partially demonstrated, but the DNS-resolver leak leaves NET-01 **FAIL**. The
acceptance is **not ready for live dispatch**. Resolving this blocker must use
an existing supported, approved common control and then pass the same
container-side probe; host network mutation is outside this implementation.
Decoding settings remain runtime measurement gaps; capture them from SV0 and
require equality before SV1.

## Two-trial acceptance procedure (preview is the default)

The former standalone qualification followed by `suite run -x` cannot satisfy
run-bound receipts. Prepare each arm separately, qualify its exact run, then
resume it only with separate authorization for inference. Keep SV0 and SV1
sequential and preserve the existing stop rule and recording requirements.
Preparation resolves the frozen registry and reads cached task trees; it may
access the registry, so authorize that access separately. Qualification creates
a synthetic Docker container and requires separate authorization. No probe or
inference is authorized by this document.

From `modules/agent_benchmark`, supply the existing study arguments, including
`-S -I 1 -Z 20261102`, the selected cohort, monitor route, and output root:

```powershell
# Prepare only: add -P <policy> -Q <reviewed-sha256> for SV1.
& $coordinatorPython -B -m agent_benchmark suite run <study-arguments> -N -F
# Record the run_dir and run_id from the prepared event.
# After separate authorization for a network probe, use the exact interpreter
# selected for dispatch. -m must match the frozen endpoint plus /chat/completions.
& $env:HARBOR_025_PYTHON -B -m agent_benchmark.network_qualification `
  -x -r <run_dir> -m <frozen-monitor-url>/chat/completions
# Only after a PASS receipt and separate authorization for inference:
& $coordinatorPython -B -m agent_benchmark suite resume `
  -d <output-root> -r <run_id> -x -F
```

The interpreter used for qualification must equal `HARBOR_025_PYTHON`, which
is also used for study dispatch. Each run needs its own receipt. The receipt
expires after at most 24 hours and is checked again at dispatch and resume.
DNS denial and application egress are separate gates: the earlier observed
Docker resolver success remains a failure. Direct external TCP and DNS over
UDP are also checked; absence of a response to one destination is bounded probe
evidence, not proof of universal isolation. The gateway is identified by its
frozen URL and expected OPTIONS response; a process identity is not measured.
The checksum detects corruption but is not authentication. Protect run files
from untrusted writers, since a writer can forge both evidence and checksum.
Synthetic tests provide no live qualification. Before SV1, inspect SV0's
native artifacts, Monitor recording and effective settings; stop on an
infrastructure-invalid result or a route or settings mismatch.

## Non-inference validation evidence

Earlier checkpoints and this network-isolation implementation were validated
separately. Exact final focused commands and exit codes:

The Agent Benchmark command ran from `modules/agent_benchmark` with
`HARBOR_025_PYTHON` set to the managed Harbor 0.25.0 interpreter at
`C:\Users\mcarls\AppData\Local\uv\cache\archive-v0\6oHf_rWkqYo-3vQ-qABxe\Scripts\python.exe`;
that enables the cached actual-task and CLI contract checks instead of skipping
them.

| Check | Exact result |
| --- | --- |
| Focused Agent Benchmark policy/network/suite/Harbor tests (10 files; includes actual cached Harbor task-tree overlay and CLI contract qualification) | `python -m pytest tests/network_qualification_test.py tests/study_network_policy_test.py tests/spec_verification_policy_test.py tests/study_task_integrity_test.py tests/harbor_runner_test.py tests/harbor_importer_test.py tests/suite_test.py tests/suite_revision_test.py tests/suite_cli_test.py tests/harbor_prompt_runtime_test.py -q`; 107 passed, exit 0 |
| Benchmark Core comparison and intervention contracts | `python -m pytest tests/contract_test.py tests/compare_test.py tests/experiment_test.py tests/prompt_intervention_test.py -q`; 82 passed, exit 0 |
| Ruff on changed Agent Benchmark implementation and regression-test files | `ruff check agent_benchmark/network_qualification.py agent_benchmark/study_network_policy.py agent_benchmark/study_task_integrity.py agent_benchmark/suite.py agent_benchmark/harbor/runner.py agent_benchmark/harbor/importer.py tests/network_qualification_test.py tests/study_network_policy_test.py tests/spec_verification_policy_test.py tests/study_task_integrity_test.py tests/harbor_importer_test.py`; all checks passed, exit 0 |
| Cached Harbor task/verifier overlay identity check | `HARBOR_025_PYTHON=<managed Harbor 0.25.0 interpreter> python -m pytest tests/study_network_policy_test.py::test_cached_frozen_task_overlays_preserve_original_verifier_trees -q`; 1 passed, exit 0 |
| Actual Harbor 0.25.0 `run --help` CLI contract | PASS, exit 0; supports `--path`; does not define `--task-git-url` or `--task-git-commit`. Runner uses the supported local path; original Git URL/revision remain validated in run and trial provenance rather than unsupported CLI flags |
| Harbor option/config check using the cached Harbor 0.25.0 interpreter, actual `AgentFactory`, and SV0/SV1 adapters | PASS; both generated configs denied `websearch` and `webfetch` identically; policy did not alter tool config; exit 0 |
| `python -m agent_benchmark suite plan --help` | PASS; showed `-S`, `-P`, `-Q`, `-I`, `-Z`, monitor and API flags; exit 0 |
| SV0/SV1 `suite plan` structural preview with no Monitor flag (therefore not a final routed preview) | Both emitted the expected one-task plan, same task/revision/model/protocol, policy IDs differed as declared; both exit 1 because sandbox Docker named-pipe access was denied |
| Exact monitored SV0/SV1 plan preview (`-L`, existing endpoint, no recovery) | Both exited 2 with `MONITOR_NOT_RUNNING` in this sandbox; no service was started |
| Candidate GGUF SHA-256 | PASS, hash recorded above; read-only 16.8 GB file hashing |
| Actual Harbor native web config generation | PASS; exit 0 |
| Synthetic Harbor 0.25.0 Docker network qualification | Harbor 0.25.0 / Docker Server 29.9.2 / `node:20`; container created and cleaned; effective allowlist and sidecar PASS; `OPTIONS /v1/chat/completions` returned 405 from local Monitor route; direct `1.1.1.1` DNS, external SNI TLS, direct-IP TLS blocked; Docker resolver resolved `example.com`; report status FAIL, command exit 1; final evidence at ignored `.pytest_tmp_root/sv-network-qualification-gateway-route.json` (2026-11-03 00:31:54 UTC) |
| Network probe preview | `python -m agent_benchmark.network_qualification`; `status: UNKNOWN`, no container or inference, exit 0; default is Monitor `/v1/chat/completions`, checked with OPTIONS only |
| Actual frozen task cache and derived digest evidence | Three task overlays materialized in a temporary directory; task/verifier hashes match frozen values; evidence in ignored `.pytest_tmp_root/sv-network-task-identities.json`; test exit 0 |

The sandbox preview without `-L` is only structural evidence: it reports
`llm_monitor_required=false`, recording `off`, and is not the final monitored
condition. The exact monitored preview command is prepared for the host above;
the operator-reported host preflight previously saw Docker and Monitor PASS.
The new run-owned task/network-policy path is implemented and its unit and
cached-task checks pass. The actual container qualification returns exit 1
because Docker's embedded resolver resolves an external hostname. That is the
current mandatory safety blocker, alongside runtime-only settings and separate
inference authorization; it is not an unimplemented suite policy-injection
path.

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
