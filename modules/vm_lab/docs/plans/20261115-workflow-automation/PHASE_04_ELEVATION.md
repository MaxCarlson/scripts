# Phase 4 — Bounded Elevated Execution Bridge for Agents

**Depends on:** Phase 3 workflow state/typed operations.  
**Scope:** explicitly launched local elevated PowerShell runner, privilege boundaries and result receipts.  
**No automatic UAC bypass, permanent admin process, service or scheduled task.**

## Objective

Eliminate the repeated Worker-ResourceCoordinator pattern of a non-elevated coding agent preparing 50–100 lines of PowerShell, waiting for the user to paste them into an Administrator console, then copying evidence back. The user should perform a small, explicit approval/execution action for a **bounded typed plan**, while the agent can inspect durable results and continue its workflow without ongoing privileged access.

## 1. Threat model and principles

Adversaries/risks: untrusted repository changes, compromised coding agent, edited request file, stale approvals, target name spoofing, a malicious guest, path traversal, race between approval and execution, forged success receipts, accidental access to production RC/KRig, and session compromise. Never infer operator consent from plan file presence or SHA-256 alone.

- Unprivileged planning may read allowed inventory/artifact metadata and write a pending request in an operation-owned directory.
- Privileged execution starts **only** through a user-invoked foreground PowerShell 7 process in an authenticated admin/Hyper-V Administrators session.
- Runner validates strict request schema and source code trust/provenance before any mutation.
- Runner supports only **typed allowlisted operations** implemented in module: create/start/stop/checkpoint/guest.deploy/guest.exec etc. No free-form host `scriptblock`, `Invoke-Expression`, `cmd /c`, network shell, arbitrary DLL or unconstrained file writes.
- Operator reviews exact VM ID, stage, effects, source digests, guest executable and requested authorization capability. The approval is bound to those details and expires; replay prevention is mandatory.
- Credentials are requested with `Get-Credential` at execution boundary and remain in memory; never stored in request, journal or logs.
- Runner writes result/evidence paths accessible to the user and non-elevated agent without granting write access to trusted approvals and receipt integrity roots.

## 2. Request contract

Proposed JSON request v1 (fields to finalize in Phase 0/4):

```json
{
  "schema_version": 1,
  "request_id": "<uuid>",
  "operation_id": "<operation-id>",
  "stage_id": "checkpoint_clean",
  "plan_digest": "<sha256>",
  "module_source_digest": "<sha256>",
  "target": {"host": "XERES", "vm_id": "<uuid>", "vm_name": "Example-VM", "manifest_digest": "<sha256>"},
  "capabilities": ["vm_shutdown", "checkpoint_create", "vm_start"],
  "expires_at_utc": "<timestamp>",
  "expected_preconditions": ["owned", "running", "standard_checkpoint_policy"],
  "result_root": "C:\\VM-Lab-Operations\\<operation-id>\\operator-results"
}
```

The plan digest only detects modifications; it is **not** proof that a particular user approved it. The design must specify the actual operator confirmation mechanism, read-only review output, environment identity and replay prevention. Do not invent cryptographic signing without key lifecycle/ACL controls.

## 3. Foreground runner behavior

1. Check admin/Hyper-V privileges without mutating host. Fail with reason if insufficient.
2. Parse request with allowlisted schema, anti-traversal and bounded payload size; no symlink/junction escapes.
3. Verify pinned source/module integrity, expected host and VM GUID/manifest/owner; compare plan digest to immutable workflow record.
4. Display explicit short summary of changes, authorized capabilities and paths; require fresh interactive approval unless a valid, separately user-authorized narrow approval mechanism is established.
5. Reject unexpected/expired/replayed request IDs and changed live VM/plan state.
6. Execute one or more *pre-approved typed stages* in declared order with pre/postcondition checks.
7. Return structured JSON receipt and exact exit code; redact credentials and secret environment values.
8. On failure, preserve partial/uncertain state with recovery hints; never auto-stop unrelated workloads or force cleanup.
9. Exit process, drop privileged context and close guest sessions. No persistent network listener or service.

### Allowed ergonomic improvement

Provide an intentionally small one-liner to launch pending plan from an elevated console (e.g. `pwsh -NoProfile -File <trusted-runner> -Request <path>`), rather than copying a large custom script. Optionally provide a UI chooser of pending reviewed requests; maintain explicit user action. The module can emit an *attention-needed* event to an existing notification system, but cannot guarantee background execution without an authorized supervisor.

## 4. Permissions and evidence

Distinguish:

- **Agent-writable request draft:** untrusted until reviewed.
- **Read-only source snapshot:** commit SHA and locally verified bytes; no automatic trust from git origin alone.
- **Operator-approved request:** explicit contextual approval, timestamp/nonce and bound digest.
- **Runner evidence:** tamper-evident manifest, actual VM ID and results; protect write access via filesystem ACLs/ownership and session identity, not hashes alone.

Avoid ACL changes to production or host-wide directories. Use an operation-owned root and set least-privilege permissions during explicit approved setup; test on Windows 11/NTFS. No credential material in `script_logging` telemetry; redact arguments that could contain secrets.

## 5. Negative test matrix

- Request absent/invalid JSON, unsupported operation, unknown schema, corrupt digest, path traversal, reparse path, too-large input.
- Approval missing, expired, replayed, wrong operator, modified request after review, changed source digest.
- Wrong host, VM ID/name mismatch, unmanaged VM, protected H4 VM, host privilege failure, guest auth failure.
- General approve-create does **not** allow checkpoint, guest-exec or shutdown; phase capability denial leaves zero mutations.
- Tricky command string in operation JSON cannot become executable PowerShell/host shell.
- Concurrent runner instances cannot mutate same VM; completed receipt cannot be replayed to another VM.
- PowerShell process killed before/after mutation; journal correctly reports uncertainty and safe resume.
- Logging retains exit code, source hash and result root without credentials.

Run tests using a fake elevated context boundary; do not escalate real privileges during unit tests. A real foreground operator test is deferred to separately authorized disposable VM acceptance.

## 6. Deliverables and gate

- Trusted/typed request schema and explicit foreground runner entry point with `-Help`, `-WhatIf`, `-Apply`, short aliases.
- A review command producing a human-readable effect list and stable JSON.
- Replay protection and plan/source/VM binding; credential handling and log redaction.
- Unit tests for all denial paths, stage execution, rollback of *planned* but not executed actions, and crash recovery.
- A user-facing short invocation and agent-readable durable response example.
- Permission/auth audit document; exact limitations and live tests pending.

**Pass criteria:** with user-supplied authorized runner, a non-elevated agent can submit a typed VM operation, observe success/failure and resume without ever receiving privileged execution rights, running an arbitrary host script, or touching protected resources.

**Do not claim Phase 4 operationally accepted until live privilege test on a separate disposable VM.**
