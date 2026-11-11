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

`restoration_verified` is only the client's assertion. RC independently verifies the managed miner is stopped, but does not have a generic proof source for external optimizer restoration of GPU clocks, power, or other hardware settings. A deployment may inject a trusted restoration verifier; without one, the client assertion alone is rejected and the hold remains. An authenticated operator may resolve a recovery-required session with `operator_override: true` and a bounded `override_reason`. This is an explicit audited override, not independent hardware evidence.

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

The read-only Mining checkout was verified at `4b1f2a57b0bac536d250a7018df1f8a20c78e1c5`. The existing client sends the canonical acquire, heartbeat, and release routes and uses a 3600-second requested lease, but it is **not yet compatible enough for production use**:

| Client behavior at reviewed commit | Server contract / required Mining follow-up |
|---|---|
| 10-second acquire timeout; no stable request ID; treats response as a direct grant | Add a stable per-run idempotency key, accept 202 as pending, poll operation status, and recover a granted result after transport loss. Never start optimization before a 200 `granted` response with token/session. |
| Computes expiration as local `now + lease_seconds` | Use server-returned `expires_at` from acquisition and every heartbeat. |
| Serializes `MaintenanceSession.fencing_token`; logs the raw token in acquisition output | Redact token from `to_dict`, trial/journal serialization and logs. Keep it only in protected in-memory client state needed for requests. |
| Release tries alternate routes and can call legacy miner start/stop fallback; success checks are permissive | Require HTTP success plus JSON `status: released` and matching session/disposition. Do not fall back to direct miner control when the maintenance protocol rejects or times out. |
| Sends `restoration_verified` boolean without independently verifiable evidence | Add a defined evidence payload understood by a configured RC verifier, or require operator-authenticated RC recovery. The Boolean alone is intentionally insufficient. |
| `--allow-legacy-coordinator` remains available | Disable that path for exclusive-maintenance runs; legacy stop/start does not establish server-enforced GPU ownership. |
| Existing method already sends token in heartbeat/release bodies and supports 3600 seconds | Keep bearer token out of logs and persistent artifacts; preserve authenticated requests and use RC's authoritative acknowledgements. |

Until Mining addresses these items and cross-repository acceptance passes, this RC branch demonstrates source-side protocol behavior only. It does not declare the live optimizer ready.
