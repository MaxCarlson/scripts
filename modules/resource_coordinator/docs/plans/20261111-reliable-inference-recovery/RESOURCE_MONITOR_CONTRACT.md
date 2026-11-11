# Resource Coordinator recovery contract

Resource Coordinator remains the owner of GPU admission, restart inhibition, and recovery decisions. Resource Monitor may consume the existing read-only status route and request an authenticated operator override; it must not infer upstream termination from GPU utilization, model inventory, or an empty lease list.

## Read status

`GET /_coordinator/status` retains all existing fields. The additive `gpu_inference.recovery` object is:

```json
{
  "required": true,
  "inhibition": {
    "resource": "gpu.inference",
    "holder_id": "coord-...",
    "reason": "upstream_read_timeout",
    "inhibited_at": 0,
    "details": {}
  },
  "requests": [
    {
      "request_id": "coord-...",
      "resource": "gpu.inference",
      "phase": "uncertain",
      "model": "model-name",
      "path": "/api/v1/models/load",
      "created_at": 0,
      "updated_at": 0,
      "details": {
        "operation_type": "model_load",
        "elapsed_seconds": 120.0,
        "upstream_elapsed_seconds": 119.9,
        "outcome": "execution_uncertain",
        "configured_timeout_seconds": 1800.0,
        "upstream_timeout_seconds": 1800.0,
        "timeout_semantics": "bounded_overall_operation_deadline",
        "lease_acquisition_timeout_seconds": 120.0,
        "connect_timeout_seconds": 10.0,
        "model_load_reported_seconds": null,
        "terminal_evidence": "upstream_execution_uncertain",
        "recovery_recommendation": "Keep restart inhibited until upstream termination is verified or an operator explicitly recovers."
      }
    }
  ],
  "journal_status": "available",
  "recommendation": "Verify the upstream operation has terminated, then use authenticated service recover with an explicit reason."
}
```

`requests` may be empty when no durable journal is configured or no unresolved journal entry can be read. `journal_status` distinguishes `available`, `not_configured`, and `unavailable`. The existing `gpu_inference.inhibition` remains the in-memory hold view. The journal details are diagnostic evidence and do not establish backend termination.

## Request operator recovery

`POST /_coordinator/recover?resource=gpu.inference` requires `Authorization: Bearer <operator credential>` and a JSON body:

```json
{
  "override": true,
  "operator": "interactive-user",
  "reason": "Verified upstream idle"
}
```

The endpoint also requires no active or pending claims, checks the service readiness guard, and persists journal resolution before clearing the in-memory hold. This is an explicit operator override; the response reports `upstream_verified_idle: false` because the coordinator does not have an authoritative LM Studio per-operation query or cancellation capability. Resource Monitor should present the upstream-verification requirement and operator reason before submitting.

The normal CLI path is `resource-coordinator service recover -f -r "<reason>"`. It reads an existing ACL-validated shared credential without creating or rotating it. `RESOURCE_COORDINATOR_RECOVERY_TOKEN` and `RESOURCE_COORDINATOR_OPERATOR_TOKEN` remain explicit compatibility overrides. The server accepts the dedicated recovery token and the shared operator credential when its file ACL is valid.

## Terminal evidence

An inference terminal event or a valid, documented model-load success event with clean stream completion can release the request lease and start the normal guarded cooldown. For streaming model loads, `model_load.end` must include a nonempty `model_instance_id` and a finite, nonnegative `load_time_seconds`. An error, failure-shaped, malformed, or incomplete event is not terminal proof and retains the restart inhibition. Model loads use the bounded overall deadline configured by `service.model_load_timeout_seconds` (1800 seconds by default, maximum 3600); the HTTPX read, write, and pool timeouts for these requests use the same allowance, while the connect timeout remains 10 seconds. Inference phase timeouts and lease acquisition remain independently set to 120 seconds by default. HTTPX read timeouts measure inactivity between bytes and are not overall deadlines. Durable request details include elapsed time, outcome and available model-reported load duration. Any timeout or disconnect leaves execution uncertain; empty model inventory and low GPU utilization also remain insufficient evidence.

There is no supported operation-specific upstream cancellation endpoint in the current contract. Closing the proxy connection is not reported as successful cancellation.
