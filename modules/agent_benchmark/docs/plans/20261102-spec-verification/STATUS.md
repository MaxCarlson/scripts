# Specification verification study status

Branch `agent/spec-verification-policy-20261102`, based on
`b5722c00aa25d136f1df664d6db1d06a805254e2`. This status covers the validated
Harbor network-policy integration and non-inference Docker qualification. No
model inference, scored task, service restart, host network mutation, merge, or
push occurred.

## Current result

SV0/SV1 now share `sv-network-policy-v1`, represented in run-owned derived
Harbor task snapshots. Only the root `task.toml` receives the declared network
metadata. Original task/verifier files remain intact and their frozen
fingerprints are rechecked before materialization, dispatch, and resume. Harbor
selects the snapshot using its supported local-task path and retains source Git
URL/revision provenance.

The actual Harbor 0.25.0 Docker sidecar probe enabled the expected agent
`allowlist`, allowed the local Monitor gateway route (OPTIONS returned 405),
denied direct external DNS and the tested unlisted TLS paths, and enforced
verifier `no-network`. It also
found that the container's Docker embedded resolver still resolves
`example.com`; the probe does not capture upstream packets to establish
whether the answer was forwarded or cached. Because the strict gate requires
name resolution to be denied, network qualification is **FAIL**. Additionally,
`host.docker.internal` is a
host-wide hostname permission, not a port-specific allowance. The two-trial
acceptance is **not ready for live dispatch** until an existing supported,
approved common control closes the DNS gap and the same container probe passes,
or an explicit protocol change is authorized and documented. No workaround to
host firewall, Docker, WSL, or DNS was attempted.

## Implemented network contract

| Phase | Harbor task metadata | Purpose |
| --- | --- | --- |
| Environment setup | `network_mode = "public"` | Preserve dependency and OpenCode setup requirements |
| Agent | `network_mode = "allowlist"`, `allowed_hosts = ["host.docker.internal"]` | Permit the local Monitor/model gateway hostname and block tested external connections |
| Verifier | `network_mode = "no-network"` | Deny verifier network access |

SV0 and SV1 use identical task snapshot policy. Native `websearch` and
`webfetch` remain denied identically by the v1 adapter. The hostname allowlist
can reach other services on the host and does not restrict to port 8788.
Task setup remains public by design; agent execution is the restricted phase.

## Task integrity evidence

Actual Harbor 0.25.0 cached task selection and run-owned snapshot creation
passed for all three frozen cohort tasks. Original hashes are checked against
the values in `study_task_integrity.EXPECTED`; verifier hashes remain unchanged
in the derived snapshots. Full original/derived task and `task.toml` digests
are preserved in ignored evidence at
`modules/agent_benchmark/.pytest_tmp_root/sv-network-task-identities.json`.

| Task | Original Harbor task SHA-256 | Original = derived verifier SHA-256 | Derived task tree SHA-256 |
| --- | --- | --- | --- |
| beer-song | `79c3e5b6f2300c5de6ff862d212ea38d329ef31eb243e6a55da975c622b53376` | `01402f4ff69be049e7bc032c55215b018f19aa129021c3cf59d508764eb3a417` | `c35454e8ee53549174470f3401b7fbf477022fa38421700f8944f72e1509886e` |
| bottle-song | `7aa03a961facf5071aea121fb5ccb1a9519c133230025db0922a70803dab139c` | `c3c6d0bdf66833931416f8d9347285950fd895f9e648ebdd9b17c8223c0bdb2b` | `5147b96eb024d8dca2e388a8028317406cb4324bf30b00936a7c951e0ddfaeef` |
| bowling | `2150b7c876f6ef7f988ec9c032ee4e873aa6e62b9591183a44e6317c64d7104f` | `cb919322a81c1733f40d8c60345aa3f164de9d23a9813d2b50d6a6d4027c3790` | `6b9dac69d5c508db45e18509fdc060b9cd9911aae5439a677716f0c46f633ed9` |

Source Harbor dataset commit remains `f30b14415dd733c83627204bad0af69a89ceb46f`.
The derived hash differs because of the declared task metadata overlay; this is
not reported as an identical full-tree hash. The frozen verifier hash is
unchanged. Per-run manifests retain original task/verifier hashes, original
task tree hash, original and derived `task.toml` hashes, derived tree hash,
policy ID/configuration, and the snapshot path. Resume and dispatch reject
drift.

## Final gate matrix

`PASS` is scoped to its evidence boundary. `FAIL` blocks trial dispatch.
`UNKNOWN` is not replaced with a presumed default.

| Gate | Class | Condition / observed evidence | Result | Blocks live acceptance? | Resolution boundary |
| --- | --- | --- | --- | --- | --- |
| TASK-01 | Mandatory | Actual Harbor cached task trees match frozen task/verifier identities; overlay preserves all non-`task.toml` bytes | PASS | No; recheck each run | Offline check passed for three tasks |
| POLICY-01 | Mandatory | SV0/SV1 policy identities, bytes, templates and resumes are frozen | PASS | No; runner rechecks | Existing offline tests and manifest validation |
| NET-CONFIG-01 | Mandatory | Harbor parses `public`/`allowlist(host.docker.internal)`/`no-network` from derived task config | PASS | No by itself | Actual Harbor TaskConfig parse and tests |
| NET-SIDECAR-01 | Mandatory | Harbor Docker egress sidecar/kernel support | PASS | Recheck at host qualification | Docker 29.9.2; Harbor egress kernel probe returned supported; sidecar enabled in actual synthetic task |
| NET-MONITOR-01 | Mandatory | Agent can reach local Monitor through allowed hostname | PASS for route connectivity | No by itself | In-container OPTIONS to the POST-only `/v1/chat/completions` route received 405; host preflight separately reported recorder healthy/zero drops |
| NET-EXT-DNS-01 | Mandatory | Agent cannot use external DNS, including container resolver | FAIL | **Yes** | Direct query to 1.1.1.1 returned `ECONNREFUSED`; Docker resolver returned two `example.com` addresses; upstream forwarding was not packet-captured |
| NET-EXT-CONN-01 | Mandatory | Agent cannot connect to unlisted external services | PASS for tested paths | No by itself | Unlisted `example.com:443` SNI and direct `1.1.1.1:443` TLS each returned `ECONNRESET`; does not establish all possible egress cases |
| NET-HOST-PORT-01 | Mandatory | Allowlist reaches only Monitor port 8788 on host | UNKNOWN / not guaranteed | **Yes under port-scoped threat model** | Harbor allowlist is hostname based; `host.docker.internal` may reach other host ports |
| NET-VERIFIER-01 | Mandatory | Verifier has no network | PASS | No | Actual phase switch to `no-network` denied Monitor request |
| TOOLS-01 | Mandatory | Native websearch/webfetch are denied identically | PASS for generated config | Verify task artifact during trial | Existing Harbor factory test |
| INFRA-01 | Mandatory | Host Docker and Monitor/recorder healthy | PASS in operator-reported Nov. 2 preflight | Recheck before qualification/trial | No services were started or restarted |
| ROUTE-01 | Mandatory | Model/provider/API route is identical and effective | Requested route is pinned; effective request UNKNOWN | Yes before SV1 | Compare Monitor and Harbor request evidence after SV0 |
| SETTINGS-01 | Measurement | Effective context/sampling/output/reasoning settings are observed and equivalent | RUNTIME_OBSERVATION_REQUIRED | Require equality before SV1 | First authorized request only; no default inference |
| BASELINE-01 | Validity | SV0 execution unchanged; SV1 differs only by intended prompt policy | PASS simulated | Runtime parity still needed | Offline adapter/manifest/task-policy comparison passed |
| ACCEPT-01 | Mandatory | Two sequential one-attempt trials with separate manifests, zero retries, recorder evidence | Prepared, not executed | Yes | Requires separate authorization after all safety gates pass |

## Container qualification evidence

Actual synthetic qualification used Harbor 0.25.0 with Docker Server 29.9.2
and cached `node:20`; no model, OpenCode task, or verifier was run. Command
(PowerShell 7, module directory):

```powershell
& $env:HARBOR_025_PYTHON -B -m agent_benchmark.network_qualification `
  -x -m http://host.docker.internal:8788/v1/chat/completions `
  -o .pytest_tmp_root/sv-network-qualification-gateway-route.json
```

Observed exit code: **1** (`status: FAIL`). Final evidence, generated
2026-11-03 00:25:09 UTC:
`modules/agent_benchmark/.pytest_tmp_root/sv-network-qualification-gateway-route.json`.
Container cleanup: PASS. The report records individual probe values, effective
Harbor config, sidecar state, image, and exit codes. No local Monitor response
body or credentials are collected. Harbor 0.25.0 was confirmed by the managed
runtime; Docker's kernel capability probe returned `True`.

The module's default command `python -m agent_benchmark.network_qualification`
is preview-only and returned exit 0 / `UNKNOWN`; it creates no container.
The actual container command above is non-inference, but it is intentionally
not a scored task. Do not treat its current `FAIL` as a gate satisfied.

## Two-trial acceptance state

The exact SV0 then SV1 suite commands and separate evidence roots remain in
[`spec-verification-study.md`](../../spec-verification-study.md). The network
qualification command is now a mandatory preceding gate: it must exit 0 and
write `status: PASS`. The current observed DNS result fails it, so operators
must stop before either `suite run -x`. The SV0-before-SV1 stop rule, one task,
one attempt, sequential execution and zero retries remain unchanged. No
inference is authorized by this status report.

## Tests and changes in this checkpoint

Focused validation on the final implementation:

- Agent Benchmark network/policy/suite/Harbor tests, including actual Harbor
  0.25.0 `run --help` inspection and cached task overlay identity:
  `python -m pytest tests/network_qualification_test.py tests/study_network_policy_test.py tests/spec_verification_policy_test.py tests/study_task_integrity_test.py tests/harbor_runner_test.py tests/harbor_importer_test.py tests/suite_test.py tests/suite_revision_test.py tests/suite_cli_test.py tests/harbor_prompt_runtime_test.py -q` — **107 passed**, exit 0.
  This ran with `HARBOR_025_PYTHON` set to
  `C:\Users\mcarls\AppData\Local\uv\cache\archive-v0\6oHf_rWkqYo-3vQ-qABxe\Scripts\python.exe`.
- Benchmark Core contracts/comparison/intervention:
  `python -m pytest tests/contract_test.py tests/compare_test.py tests/experiment_test.py tests/prompt_intervention_test.py -q` — **82 passed**, exit 0.
- Ruff over changed implementation and regression-test files — all checks
  passed, exit 0; exact invocation is in `../../spec-verification-study.md`.
- `python -m agent_benchmark.network_qualification` — preview only,
  `status: UNKNOWN`, exit 0; no container and no inference.
- Explicit synthetic Docker qualification — Harbor 0.25.0, Docker Server
  29.9.2, `node:20`; container cleanup PASS, qualification FAIL, inner command
  exit 1 because external name lookup through the Docker resolver succeeds.
- Actual Harbor `run --help` — exit 0, confirms supported `--path` and absence
  of the attempted Git URL/commit options. Those unsupported flags were
  removed; source provenance is verified and persisted in study artifacts.

Private qualification reports remain under ignored `.pytest_tmp_root`;
original benchmark archives, task caches, verifier files, and historical
evidence remain unchanged. The exact commands and hash evidence are also
recorded in the study document.

### P02 qualification receipts (2026-11-02)

Study dispatch requires `network-qualification.json` in the prepared run directory. To produce it, run the existing non-inference qualification with `-x -r <run-dir>` after preparing that run; `-m` must match the frozen monitor endpoint plus `/chat/completions`. The producer checks the task snapshots and records Docker daemon and image identity, Harbor runtime, policy, probe results, cleanup, and a 24-hour expiry. It fails closed when measurements are unavailable or change during the probe. The SHA-256 is an integrity checksum, not a signature; receipts must be protected from untrusted modification. Synthetic test receipts are test fixtures only and are not live qualification evidence. No live qualification was run as part of implementation.


### P02 independent integration review

Receipt review added run-ID binding, explicit direct-IP TCP containment and
DNS negative-response handling, an effective verifier policy check, and a
requirement that the probe and dispatcher use the same Harbor interpreter.
Study runs now prepare with `suite run -N` and require a per-run receipt before
`resume -x`; rejected qualification leaves the pending attempt unchanged.
These are offline implementation checks, not a live qualification result.
See the updated study procedure for runtime authorization and trust limits.

Integration candidate validation: Agent Benchmark receipt, suite, Harbor,
Monitor, recovery, doctor and review tests: 170 passed, exit 0, including all
four cached Harbor-dependent checks. Benchmark Core contract/comparison/
experiment/intervention tests: 82 passed, exit 0. Ruff check, Ruff format
check and Git whitespace validation passed. No Docker network probe or model
inference was executed. The gateway URL/OPTIONS response identifies the
endpoint; the gateway process identity remains unmeasured. The protected run
directory and local operator remain the receipt trust boundary.
