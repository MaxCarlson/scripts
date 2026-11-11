# Durable GPU Maintenance Sessions

Resource Coordinator 0.13 adds an authenticated, server-owned maintenance reservation for an external optimizer. The reservation shares the existing GPU admission gate with inference, model loading, gaming transitions, and guarded miner controls.

## Authentication and acquisition

Mutation routes use the configured Resource Coordinator operator credential:

```http
POST /_coordinator/maintenance/acquire
Authorization: Bearer <operator-token>
Content-Type: application/json
```

```json
{
  "operator": "mining_optimizer",
  "reason": "Optimization session",
  "lease_seconds": 3600,
  "inhibit_restarts": true,
  "request_id": "optimizer-run-20261111-001"
}
```

`request_id` (or its alias `idempotency_key`) should be generated uniquely per run and reused unchanged for retries. `GET /_coordinator/maintenance/operations/{operation_id}` reports pending, active, recovery-required, or a completed disposition. If it reports active after an acquisition response was lost, retry the identical acquire request to retrieve the same in-process token; the GET response never contains a token. RC keeps a bounded history of the latest 64 completed operation identities so delayed retries cannot create a second session during that history window. Reusing a completed ID returns conflict. Without a client-provided identity, an ambiguous result remains safely held but is harder for the client to recover. A pending response is HTTP 202 and does not grant GPU ownership.

The server closes GPU admission under the same LeaseManager condition used by protected RC work, persists the intent and restart hold, then stops and verifies only the Coordinator-owned miner. Only after the process is verified stopped does the server return a session and opaque fencing token. A failed or ambiguous stop retains the fence and recovery hold and returns a non-success response.

## Session lifecycle

The durable states are `idle`, `acquiring`, `active`, `releasing`, and `recovery_required`. Active tokens are generated cryptographically and retained only in process memory as a token digest plus a short-lived idempotent-acquire response value. A Coordinator restart revokes those tokens, converts any non-idle record to `recovery_required`, restores GPU admission closure and the miner hold, and does not resume the external owner.

Heartbeat requests use `POST /_coordinator/maintenance/heartbeat` with `{ "token": "…", "lease_seconds": 3600 }`. The current bounded lease range is 30–3600 seconds. A successful response includes the authoritative `expires_at`. Expiry revokes the token but does not prove that the optimizer stopped; the GPU fence and recovery hold remain until reconciliation.

`GET /_coordinator/maintenance/status` and the additive `maintenance` object in `GET /_coordinator/status` show owner, operation/session identity, expiry, pending/recovery state, restart inhibition, admission permission, and safe restoration disposition. They never expose the token. Maintenance status and operation lookup are read-only; all state-changing routes require operator authentication.

## Trusted restoration verification (v0.14)

Ordinary Mining release remains unavailable unless the deployment explicitly enables a trusted RC-side verifier. The verifier is disabled by default. Client `restoration_verified` and `restoration_evidence` are recorded as assertions/input only; they are not proof.

An enabled verifier requires a configured GPU UUID, a bounded allowlist of known miner executable names and restorable dimensions, and a separately accepted GPU-process-attribution capability. For example:

```yaml
maintenance_verification:
  enabled: true
  gpu_uuid: "GPU-<deployment-specific-uuid>"
  allowed_dimensions:
    - power_limit_mw
    - graphics_clock_offset_mhz
    - memory_clock_offset_mhz
  known_miner_executables:
    - krig.exe
  allowed_gpu_processes:
    - dwm.exe
    - explorer.exe
  gpu_process_attribution_confirmed: false
  observation_timeout_seconds: 5
  max_observation_age_seconds: 30
```

`gpu_process_attribution_confirmed` must remain `false` until that exact operating system, driver, GPU, and NVML process-query combination has been independently accepted. Setting it to `true` is an operator capability declaration; it does not itself prove NVML completeness. When false, missing, or unsupported, acquisition is rejected before RC stops its miner. The verifier uses the optional `maintenance-verification` package extra (`nvidia-ml-py`) and has no GPU setting commands. No live RTX 5090/WDDM acceptance is claimed by these source tests.

Mining must declare the allowed scope in its acquire request:

```json
{"mode":"power_offsets","dimensions":["power_limit_mw","graphics_clock_offset_mhz","memory_clock_offset_mhz"]}
```

Supported modes are `power`, `offsets`, and `power_offsets`, with dimensions limited to the corresponding power limit and clock offsets. RC reads and persists the baseline only after its managed miner is stopped and before returning the grant. The baseline is bound to the operation ID, GPU UUID, PCI identity, driver, timestamp, supported setting values, and GPU-process identities. Unsupported or incomplete baseline evidence does not grant ownership and preserves recovery protection if RC has already stopped its miner.

Mining must register every optimizer-owned trial miner immediately after launch and before it can mutate the GPU:

```http
POST /_coordinator/maintenance/processes/register
Authorization: Bearer <operator-token>
Content-Type: application/json
```

```json
{"token":"<session-token>","session_id":"<server-session-id>","pid":12345}
```

RC independently rereads PID, creation time, and executable identity. It does not adopt or terminate that process. At release it requires a complete host miner-process inventory, absence of registered exact process identities and absence of any configured known miner, plus fresh post-operation measurements matching the trusted baseline on every scoped dimension and the same GPU/driver identity. Missing process attribution, access errors, a surviving miner, unsupported settings, stale/mismatched measurements, verifier timeout/cancellation, expiry, or persistence failure retain the GPU hold. GPU utilization or an empty GPU-process list alone is never evidence of termination.

Power limit is compared exactly in milliwatts; offset values are compared exactly in MHz. Fixed/locked-clock modes are not supported for automatic release because a reliable independent getter for the prior policy has not been established. Those sessions require explicit authenticated operator reconciliation. Windows WDDM and GeForce process attribution is device/driver-dependent; NVIDIA documents unsupported and incomplete process-query cases, so an apparently successful query is not a universal capability guarantee ([NVML device queries](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html), [nvidia-smi process reporting](https://docs.nvidia.com/deploy/nvidia-smi/index.html)). Clock-offset read support is also driver/device-dependent ([NVML clock-offset query](https://docs.nvidia.com/deploy/nvml-api/620/api/structnvmlClockOffset__v1__t.html)).

Release verification runs off the asyncio event loop while the maintenance fence remains active. RC then revalidates the exact operation, session, token, and expiry under its manager lock before recording the result. Only a successful independent verification, a still-stopped managed miner, and a durable release transition clear the maintenance-specific hold. Normal cooldown and existing supervisor policy decide whether RC may restart its own miner.

The optional configuration does not change existing deployments. Where the NVML/process capabilities cannot be validated, use the audited operator recovery path. A client Boolean or client-provided evidence file cannot substitute for independent verification.

## Release and restoration evidence

Release uses `POST /_coordinator/maintenance/release`, for example:

```json
{
  "token": "<session-token>",
  "session_id": "<server-session-id>",
  "operator": "mining_optimizer",
  "restoration_verified": true,
  "restoration_evidence": { "evidence_id": "optimizer-run-20261111-001" },
  "resume_miner": true
}
```

`restoration_verified` is only the client's assertion. RC verifies the managed miner remains stopped and, when the opt-in trusted verifier is configured, independently checks the approved baseline settings and external miner termination as described above. Without an accepted verifier, the client assertion alone is rejected and the hold remains. An authenticated operator may resolve a recovery-required session with `operator_override: true` and a bounded `override_reason`. This is an explicit audited override, not independent hardware evidence.

A successful release records the disposition, clears only that session's inhibition, opens admission and starts the ordinary inference cooldown. The durable `restart_not_before` timestamp lets startup re-arm that cooldown after a Coordinator restart so startup cannot skip it. Existing unrelated GPU holds remain in force. Duplicate release for the completed operation returns its recorded disposition.

No success acknowledgement is returned for a rejected release. The server returns structured non-2xx responses for invalid input (400), missing/invalid operator authentication (403), stale or conflicting ownership (409), missing operation (404), unavailable state/service (503), or durable persistence failure (500).

## Safety and fencing limits

- All RC-managed `gpu.*` claims and idle-guarded GPU actions share the maintenance fence. Inference and model-load admission checks it before the already-loaded-model reuse shortcut.
- Automatic restart, watchdog recovery, manual resume, and gaming transitions respect the fence or its durable inhibition.
- RC never terminates or adopts an external/unowned miner.
- Uncertain shutdown, restoration, expiry, cancellation, persistence, and service-restart outcomes fail closed.
- Logical fencing prevents stale clients from using RC-managed routes; it cannot stop a stale external process from directly invoking NVIDIA driver APIs. The optimizer must stop itself before release, and operators must account for this limitation.
- Observational events use stable event keys and safe owner/operation/session metadata; they do not contain bearer tokens or unrestricted restoration payloads. No notification transport is implemented here.

## Mining client compatibility

The Mining client implementation checkpoint supplied for H2B is `8f53e3d32d2bce560a2b35c802e6ac1c3fbfa7db`; the original merged client baseline was `4b1f2a57b0bac536d250a7018df1f8a20c78e1c5`. H2B addresses idempotent acquisition, pending-operation polling, server expiration, strict acknowledgements, token redaction, and ownership-before-mutation. The remaining H2C compatibility work is **not yet complete enough for unattended production use**:

| Client behavior at reviewed commit | Server contract / required Mining follow-up |
|---|---|
| H2B acquire payload does not declare a `tuning_scope` | Add the additive `tuning_scope: {mode, dimensions}` field. RC rejects verified automatic acquisition without a supported declared scope. Fixed clocks are not eligible. |
| H2B does not register each optimizer-owned trial process | Call `POST /_coordinator/maintenance/processes/register` with token, session ID, and PID immediately after launch and before GPU mutation. Failed registration must stop that process and retain local recovery state. |
| Release `restoration_evidence` contains client-side evidence only | Preserve it as context, but do not label it independent. RC's own observer compares hardware and process state; without configured, accepted NVML/process capabilities, ordinary release remains inhibited and operator reconciliation is required. |
| RC verifier currently defaults disabled and process-attribution acceptance defaults false | Deployment must separately validate the exact GPU/driver/Windows capability profile and explicitly enable supported dimensions. No production configuration change is made by this source branch. |
| Fixed/locked-clock restore | No automatic release: independent previous-state readback is unsupported. Use the authenticated operator reconciliation path. |

Until Mining addresses these items and cross-repository acceptance passes, this RC branch demonstrates source-side protocol behavior only. It does not declare the live optimizer ready.
