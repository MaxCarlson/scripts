# PrivExec — Master Implementation Plan

**Project:** `MaxCarlson/scripts`  
**Module:** `modules/privileged_execution`  
**CLI:** `privexec`  
**Target platform:** Windows 11, PowerShell 7, Python, .NET  
**Initial integration:** Resource Coordinator H4  
**Status:** Planned; implementation not started  
**Plan date:** 2026-11-19

---

## 1. Objective

Build a small, reusable privileged-execution facility that allows locally running AI coding agents, including Codex and Gemini CLI, to execute narrowly authorized administrative operations without requiring the operator to repeatedly copy commands into elevated PowerShell and return their results manually.

The intended workflow is:

1. The operator starts a trusted privileged execution session.
2. The operator authorizes specific operations, targets, mutation modes, and an expiration time.
3. A non-elevated AI agent requests an approved operation using `privexec`.
4. The trusted process independently authenticates and authorizes the request.
5. The trusted process invokes the approved script or executable.
6. The agent retrieves structured results and continues working.
7. The operator intervenes only when the authorization scope changes, credentials expire, or an unexpected condition requires a decision.

**Success means eliminating the repetitive administrative command/result loop, not building a general-purpose Windows administration framework.**

The initial real-world integration is Resource Coordinator H4 qualification inside a Hyper-V Windows 11 guest.

## 2. Scope

### 2.1 Supported administrative use cases

The reusable module must be capable of invoking trusted implementations for:

- Hyper-V VM inspection and narrowly authorized VM administration.
- Windows Scheduled Task installation, modification, and removal.
- Windows service installation and configuration.
- Software installation requiring administrator privileges.
- PowerShell Direct operations against an exact Hyper-V guest VM.
- Structured collection and retrieval of operation results.

These operations are performed by approved scripts or adapters.

PrivExec **does not implement separate APIs for Hyper-V, Scheduled Tasks, Windows services, or software installers**.

H4 already provides substantial domain-specific implementations. PrivExec will reuse them.

### 2.2 Required components

The MVP consists of five functional elements:

1. **Operator-started session broker:** A trusted privileged process running only while required.
2. **Agent-facing client:** A lightweight Python CLI for submitting operations and retrieving results.
3. **Authorization mechanism:** Exact capability, target, mutation scope, and expiration checks.
4. **Approved execution mechanism:** Launch trusted PowerShell/Python entry points, capture results, and prevent unsafe retries.
5. **H4 integration:** Demonstrate the complete administrative workflow without rewriting Resource Coordinator.

Implementation infrastructure may include a small SQLite database, fixed capability descriptors, and a protected installation procedure.

### 2.3 Explicit non-goals

Do not implement:

- A permanent Windows service.
- A web dashboard, GUI, or MCP server.
- Remote or multi-machine execution.
- WSL2/Linux privilege mediation.
- A distributed task queue or scheduler.
- Arbitrary elevated PowerShell, CMD, Bash, or Python execution.
- Agent-supplied scripts or executable paths.
- A plugin marketplace or dynamic plugin loader.
- A general Hyper-V management framework.
- A general Windows service or Scheduled Task management framework.
- A persistent guest credential vault.
- An agent orchestration framework.
- Integration with `agent_sync` beyond ordinary CLI interoperability.
- Complex multi-agent coordination.
- Unnecessary abstraction layers intended only for hypothetical future use.

Do not load, invoke, or benchmark local LLMs as part of implementation or validation.

## 3. Verified repository context

### 3.1 Repository

https://github.com/MaxCarlson/scripts

The repository contains module packaging, launcher conventions, shared utilities, CLI discovery, testing standards, and project-local planning standards.

The following repository files were inspected through GitHub on November 19, 2026:

- `MODULE_STANDARDS.md`
- `docs/agent/PYTHON_REPO_STANDARDS.md`
- `docs/agent/SCRIPTS_REPO_STANDARDS.md`
- `docs/agent/LEGACY_PLANNING_MIGRATION.md`
- `modules/agent_sync/README.md`
- The opening sections of H4 qualification and recovery PowerShell scripts on `fix/rc-h4-task-discovery-20261115`.

The exact state of the local Windows checkout, active worktrees, uncommitted changes, and running agents has not been inspected.

### 3.2 Repository conventions

Follow the authoritative split standards referenced by `MODULE_STANDARDS.md`.

Key requirements:

- Every CLI option must have a short and long form.
- Module packaging uses `pyproject.toml`.
- New CLI entry points require the repository's specified versioning and installation handling.
- CLI discovery entries belong in `modules/scripts_help/scripts_help/registry/registry.py`.
- Python testing uses pytest.
- Temporary test directories belong under `modules/<module>/.pytest_tmp_root/`.
- Substantial new project plans belong under the module's `docs/plans/` directory.
- Use `stage` rather than the legacy planning term `cycle`.

Suggested canonical plan location:

`modules/privileged_execution/docs/plans/20261119-privexec-session-broker/`

### 3.3 Relevant existing modules

**`modules/agent_sync`**

Coordinates local agent delegation and worker execution. PrivExec is independent of this responsibility.

Do not merge privilege management into `agent_sync`.

**`modules/resource_coordinator`**

Contains the H4 administrative scripts and guest qualification harness. These scripts already provide many necessary domain-specific safety mechanisms.

The active Resource Coordinator implementation work retains ownership of this directory.

**`modules/vm_lab`**

Contains related Hyper-V tooling and evidence of earlier Resource Coordinator integration. Inspect only where useful for interoperability and existing conventions.

## 4. H4 reference environment

Historical context from the research proposal:

| Property | Value |
|---|---|
| Windows host | `XERES` |
| Hyper-V VM | `RC-H4-Windows-Acceptance` |
| VM ID | `d8483f98-8884-4758-abd1-cd6107c83c03` |
| Guest hostname | `DESKTOP-1ITSJV0` |
| Protected checkpoint | `9f45b469-382c-4be0-a50e-7a71384c7922` |
| H4 bundle SHA-256 | `a4cf9273e5b023bc592f964915115a4734793b350683a432f2932afda9a6bf64` |
| Historical H4 branch | `fix/rc-h4-task-discovery-20261115` |
| Historical reported HEAD | `ea6ad23fe705bc828f06a99ccf1ab3477e621d49` |

Relevant files:

- `modules/resource_coordinator/tools/h4_qualification/Invoke-H4GuestQualification.ps1`
- `modules/resource_coordinator/tools/h4_qualification/Invoke-H4GuestRecovery.ps1`
- `modules/resource_coordinator/tools/h4_qualification/Bootstrap-H4GuestBundle.ps1`
- `modules/resource_coordinator/tools/h4_qualification/windows_acceptance.py`

At inspection, the qualification and recovery wrappers existed on the historical H4 feature branch. The qualification wrapper was not found at its expected path on default-branch `main`.

### 4.1 Existing H4 authorization

The inspected qualification wrapper supports:

`Preflight`, `Setup`, `Checkpoint`, `Acceptance`, and `All`.

It defaults to read-only preflight. Mutations require explicit `-Apply`; guest lifecycle and task mutations also require `-AuthorizeGuestMutation`.

The recovery wrapper similarly separates read-only inspection from explicitly authorized mutation.

Both expose operation IDs, structured output, and validation logic.

An `install-only` H4 workflow is described in historical project context, but a corresponding mode in the inspected qualification wrapper was not confirmed. The implementation agent must determine the actual entry point before registering that capability.

### 4.2 Existing H4 safety mechanisms

Preserve and reuse:

- Exact VM identity checks.
- Guest hostname verification.
- Protected checkpoint identity checks.
- Pinned source and bundle hashes.
- Existing mutation authorization switches.
- Manifest ownership validation.
- Existing path and reparse-point protections.
- Post-operation inventories.
- Structured evidence.
- Recovery safety checks.
- Refusal of unexpected resources.

Do not weaken these checks or duplicate their business logic in PrivExec.

### 4.3 Historical qualification status

The November 19 research proposal reported:

- v8 recovery: successful.
- v10 setup preflight: PASS.
- v10 setup: PASS.
- Checkpoint: NOT_RUN.
- Acceptance: NOT_RUN.
- Isolated install-only qualification: not yet reported complete.

These are historical reports, not proof of current H4 state.

## 5. Recommended architecture

```text
┌──────────────────────────────────┐
│ Codex / Gemini / other local AI │
│ Non-elevated client identity    │
└────────────────┬─────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│ privexec Python CLI              │
│ Request / response serialization│
│ No privilege authority          │
└────────────────┬─────────────────┘
                 │
                 │ Local Windows named pipe
                 ▼
┌──────────────────────────────────┐
│ PrivExec session broker          │
│ C# / .NET                        │
│                                  │
│ Authenticate Windows identity    │
│ Validate capability + parameters │
│ Check operator-approved scope    │
│ Enforce expiry and target        │
│ Serialize target mutations       │
│ Record operation state           │
│ Launch trusted entry points      │
└────────────────┬─────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│ Protected approved scripts       │
│ PowerShell 7 / Python            │
└────────────────┬─────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│ Windows host / Hyper-V guest     │
│ Existing H4 validation remains   │
└────────────────┬─────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│ Protected operation records      │
│ JSON result + evidence reference │
└──────────────────────────────────┘
```

### 5.1 Privileged broker

Implement a small C#/.NET process that:

- Starts only through a trusted operator action.
- Runs under the approved privileged Windows security identity.
- Listens on a local-only Windows named pipe.
- Authenticates connecting Windows client identities.
- Applies explicit application-level authorization.
- Executes only registered trusted capabilities.
- Persists operation state and structured results.
- Exits cleanly when the operator ends the session.

Use .NET 10 LTS if supported by the actual development environment and repository dependency policy; otherwise select a supported version and document the choice.

A Windows service is not required for the MVP.

### 5.2 Python client

The client:

- Parses CLI arguments.
- Reads optional JSON parameter files as untrusted data.
- Sends versioned structured requests.
- Displays structured responses.
- Retrieves existing operation results.

The client must not have privileged Windows permissions.

The client must not own or modify authorization policy.

### 5.3 Fixed capability descriptors

Each capability has an immutable, trusted descriptor installed alongside the broker.

It identifies:

- Capability ID and version.
- Trusted executable/script reference.
- Approved executable or script digest.
- Supported target identities.
- Allowed typed arguments and values.
- Read-only versus mutating modes.
- Maximum execution duration.
- Expected result format.

A capability descriptor is **trusted configuration**, not an agent-installable plugin.

Initially, descriptors can be read from protected files during broker startup.

No dynamic capability registration API is required.

### 5.4 Durable operation records

Use a small SQLite store protected by the privileged process identity.

The store provides:

- Stable operation IDs.
- Request idempotency.
- Operation status.
- Target and capability information.
- Authorization decisions.
- Start/end timestamps.
- Execution exit status.
- Sanitized output.
- Evidence references.
- Crash-recovery state.

Do not implement a general database management interface.

## 6. Security and trust boundaries

### 6.1 Crucial UAC limitation

Microsoft explicitly states that same-desktop UAC elevation is not a security boundary.

Accordingly, PrivExec must distinguish two security modes:

**Accidental-misuse containment**

An agent running under the same administrative user account as an elevated broker may be restricted by application-level policy, but this configuration is not a strong boundary against a compromised agent.

**Stronger operating-system isolation**

A non-administrator agent identity is separated from the privileged operator identity. Broker code, policy, logs, and trusted scripts are inaccessible for modification by the agent account. The privileged operator process and its session/desktop must also be protected appropriately.

The MVP should support clear identity validation and protected installation, with the security limitations explicitly documented.

Do not claim malicious-agent isolation until tested with actual Windows security identities.

### 6.2 Authentication

Use Windows authentication and named-pipe access control.

Never trust a username, SID, role, or approval status supplied inside the request payload.

The implementation must verify client identity server-side and reject unintended or remote connections.

Do not use `CurrentUserOnly` as a substitute for an explicit cross-account pipe ACL when broker and agent run under different Windows identities.

### 6.3 Authorization

Authorization is independent of authentication.

An operator-approved session scope contains:

- Allowed client identity or identities.
- Allowed capability IDs.
- Exact target identity or identities.
- Allowed modes, including mutation permission.
- Expiration.
- Relevant fixed script/bundle identity.

Authorizations are created through the trusted operator interface.

Client requests cannot create, extend, or modify grants.

Authorization may remain in trusted process memory.

Broker restart requires a new authorization session.

### 6.4 No arbitrary code execution

The agent must not control:

- Executable paths.
- Script source.
- PowerShell expressions or script blocks.
- Interpreter flags.
- Working directory without validation.
- Trusted policy or capability definitions.
- Administrative credentials.
- Approval metadata.

Use fixed executables, typed arguments, and explicit validation.

Do not build a generic administrative command runner.

### 6.5 Filesystem protection

Trusted scripts and policy must be installed into a protected location, not invoked directly from an agent-writable Git worktree.

Use explicit path resolution and path-integrity checks to prevent unexpected junction, symlink, and reparse-point redirection.

A digest confirms file contents against a trusted reference; it does not replace filesystem ownership and access controls.

### 6.6 Credential handling

Guest credentials must be entered into a trusted operator-controlled process, not supplied through the agent CLI.

Avoid storing guest passwords on disk.

For PowerShell Direct, credentials or authenticated sessions may be retained in broker-owned PowerShell worker memory as necessary.

Do not serialize credentials into operation parameters, logs, environment variables, or command-line arguments.

After broker/worker restart, credentials may need to be reentered.

Do not build a general credential vault.

### 6.7 Mutation safety

Mutating requests require:

1. An authorized capability.
2. A matching exact target.
3. A valid active mutation grant.
4. Explicit `-A/--apply`.
5. Applicable H4 domain-specific authorization.
6. No conflicting active mutation against the same resource.

Unknown outcomes are never automatically retried.

## 7. Minimal CLI

```text
privexec status

privexec run <capability>
    -t/--target <target>
    [-p/--params-file <json-file>]
    [-n/--dry-run | -A/--apply]
    [-r/--request-id <id>]

privexec result <operation-id>
    [-w/--wait]
    [-f/--format json|text]

privexec broker start
```

The command layout is conceptual; implementation must provide conventional single-line help and platform-appropriate entry points.

`privexec broker start` is an operator-only action and must not be invocable as an agent-side privileged capability.

The operator interface should also support ending the current session and revoking its remaining authorization.

Do not add separate command families for grant management, generic job queues, plugins, or remote execution.

### 7.1 Client behavior

- `status` reports whether a compatible broker is reachable and basic nonsecret session status.
- `run` submits an approved request and returns an operation ID and result/status.
- `result` retrieves an existing result without reexecuting the operation.
- `result --wait` may wait for an outstanding execution using bounded polling.
- Missing `--apply` means dry-run for a mutating capability.
- Unsupported platforms fail with a clear diagnostic.

## 8. Versioned request/result contracts

### 8.1 Request

Illustrative schema:

```json
{
    "protocol_version": 1,
    "request_id": "client-generated-id",
    "capability": "h4.preflight",
    "target": {
        "type": "hyperv_vm",
        "id": "d8483f98-8884-4758-abd1-cd6107c83c03"
    },
    "mode": "dry_run",
    "parameters": {}
}
```

Requests must not contain trusted approval flags, credential material, executable paths, or script bodies.

The broker validates all fields and rejects unexpected properties.

### 8.2 Result

Illustrative schema:

```json
{
    "protocol_version": 1,
    "operation_id": "broker-generated-id",
    "request_id": "client-generated-id",
    "capability": "h4.preflight",
    "target_id": "d8483f98-8884-4758-abd1-cd6107c83c03",
    "state": "succeeded",
    "authorized": true,
    "exit_code": 0,
    "started_at": "ISO-8601 timestamp",
    "finished_at": "ISO-8601 timestamp",
    "diagnostic_category": null,
    "result": {},
    "evidence": [],
    "postcondition_verified": true
}
```

Only the broker may issue authoritative operation IDs, execution results, and authorization decisions.

### 8.3 State transitions

Minimal durable state model:

```text
requested
    |
    v
validated
    |
    +---- denied
    |
    v
approved
    |
    v
executing
    |
    +---- succeeded
    |
    +---- failed
    |
    +---- outcome_unknown
```

An unapproved request fails promptly. No persistent approval queue is needed.

Before starting a mutation, the broker must durably record `executing`.

If the broker terminates and the result cannot be established, the operation becomes `outcome_unknown`.

An `outcome_unknown` mutation requires independent reconciliation before another attempt.

### 8.4 Idempotency

For each authenticated client and request ID:

- Same request ID and identical canonical payload: return existing operation/result.
- Same request ID with different payload: reject.
- Already completed operation: never reexecute.
- Unknown previous outcome: never reexecute automatically.

Use database uniqueness constraints and transactions to prevent races.

### 8.5 Concurrency

Allow concurrent safe read-only requests when appropriate.

Allow at most one active mutation per exact target.

Reject conflicting requests immediately rather than introducing a full scheduling system.

## 9. H4 reference capabilities

The MVP will introduce these capability families:

### `h4.preflight`

Read-only H4 environment and setup verification.

Must not cause host/guest mutation.

### `h4.qualify`

Controlled H4 qualification operations.

Use explicitly enumerated modes backed by verified existing entry points.

Initially prioritize:

- Read-only preflight.
- Setup verification.
- A verified install-only operation if the current harness exposes one.
- Acceptance after its existing authorization and prerequisites are understood.

Do not initially expose unrestricted `All`, arbitrary checkpoint creation, or unchecked VM lifecycle control.

Checkpoint and acceptance modes must have independently appropriate authorization.

### `h4.recover`

Dedicated H4 recovery operation using the existing recovery wrapper.

Recovery mutation requires a separate explicit grant.

No recovery operation may bypass ownership, manifest, or protected-checkpoint validation.

### Trusted script staging

PrivExec must execute approved versions of H4 scripts installed into a protected location.

The trusted script version and its dependency/bundle identity must be pinned.

Updates require operator-controlled installation or replacement.

The agent's working tree must not be used as privileged executable source.

## 10. Installation and operator setup

Provide one repeatable installation/setup path.

The initial setup should:

1. Build or locate the trusted broker binaries.
2. Validate approved artifacts.
3. Prepare protected installation and data directories.
4. Apply least-privilege Windows ACLs.
5. Install approved capability descriptors and trusted scripts.
6. Verify the resulting ACLs and file integrity.
7. Report the installed version, location, and authorization requirements.

The installer must support dry-run by default.

Actual elevated installation requires explicit operator authorization.

Do not create a Windows service or a background startup task.

Do not automatically alter the user's account configuration.

A separate privileged operator account may be used when chosen and authorized by the user.

## 11. Implementation phases

### Phase 0 — Repository baseline and contract

**Objective:** Establish safe ownership and freeze the minimum interfaces.

Tasks:

1. Inspect local Git branches, worktrees, dirty status, active agents, and recent validated commits.
2. Create an isolated PrivExec feature worktree.
3. Read applicable repository standards.
4. Inspect H4 integration points read-only.
5. Establish module layout and canonical planning documents.
6. Finalize request/result schema and capability descriptor format.
7. Select supported .NET and Python versions.
8. Document Windows account/ACL deployment assumptions.
9. Identify exact integration constraints without modifying H4.

**Exit criteria:**

- Worktree and branch recorded.
- No existing worktree damaged.
- Master plan committed.
- Interface contract documented.
- H4 integration seam identified.

### Phase 1 — Secure broker foundation

**Objective:** Prove the end-to-end authorization boundary using synthetic read-only operations.

Implement:

- Python CLI package and entry point.
- C#/.NET broker process.
- Local-only named-pipe transport.
- Windows client identity checks.
- Operator-started session.
- In-memory authorized session scope.
- Expiration and revocation.
- Protected capability descriptor loading.
- Synthetic read-only operation.
- Non-mutating installer planning.
- Structured status and result responses.

Test:

- Authorized identity accepted.
- Wrong identity rejected.
- Unapproved target rejected.
- Expired grant rejected.
- Unknown capability rejected.
- Malformed request rejected.
- Client cannot alter approval or policy.
- Broker exits without leaving unexpected processes.

**Exit criteria:**

A synthetic read-only request works end-to-end, and the authorization negative tests pass.

Actual privileged account and ACL behavior must later be verified on Windows.

### Phase 2 — Execution and persistence

**Objective:** Safely execute trusted operations and return durable results.

Implement:

- Fixed executable/script invocation.
- Typed parameter validation.
- Bounded stdout/stderr handling.
- Structured JSON result parsing.
- Secret filtering and output limits.
- SQLite operation ledger.
- Idempotent request handling.
- Target-level mutation conflict handling.
- Timeouts and child process supervision.
- Unknown-outcome handling after crashes.
- Durable sanitized evidence references.

Test:

- Valid synthetic operation.
- Rejected script substitution.
- Argument injection attempt.
- Untrusted path or reparse-point attempt.
- Duplicate request ID.
- Request ID reused with different payload.
- Concurrent conflicting mutations.
- Timeout.
- Broker crash during a synthetic mutation.
- Unknown-outcome replay refusal.
- No credential leakage.
- Result retrieval after broker restart.

**Exit criteria:**

Synthetic read-only and mutating operations execute correctly without arbitrary-code execution, duplicate mutations, or unsafe retry behavior.

### Phase 3 — H4 integration

**Objective:** Demonstrate real value with the existing Resource Coordinator scripts.

Tasks:

1. Reconcile current H4 code and validated status.
2. Confirm exact entry points and parameter contracts.
3. Implement `h4.preflight`.
4. Validate preflight without VM mutation.
5. Add one narrowly authorized qualification operation.
6. Integrate PowerShell Direct credential handling through a trusted process.
7. Preserve H4's existing mutation authorization requirements.
8. Capture existing H4 evidence and diagnostics.
9. Add `h4.recover` under separate authorization.
10. Run approved end-to-end qualification testing only after explicit permission.

**Exit criteria:**

An agent can execute at least two consecutive preauthorized H4 administrative operations and consume their results without manual command copying, while all H4 safety checks remain intact.

Real VM mutation is not permitted merely because the software implementation is complete.

## 12. Testing requirements

### 12.1 Automated tests

Default tests must not require elevation or modify real Hyper-V resources.

Cover:

- Protocol compatibility.
- Request validation.
- Client identity policy logic.
- Grant scope and expiry.
- Privileged executable allowlisting.
- Parameter injection.
- Path redirection.
- Synthetic mutation behavior.
- Replay and idempotency.
- Concurrency.
- Crash recovery.
- Output sanitization.
- Result persistence.

### 12.2 Windows integration tests

Separately verify, on Windows:

- Named-pipe ACL enforcement.
- Actual client identity derivation.
- Privileged and unprivileged account isolation.
- Protected installation ACLs.
- Operator session lifecycle.
- Trusted script execution.
- Result ownership and access control.

Mocked identity tests alone are not sufficient.

### 12.3 H4 validation

Use only the designated disposable H4 VM.

Preserve protected checkpoints and historical evidence.

Read-only qualification is preferred initially.

Mutating acceptance tests require separate operator authorization.

## 13. Acceptance criteria

The module is complete when all of the following are demonstrated:

- [ ] Agent-facing `privexec` CLI works.
- [ ] Trusted broker can be started by the operator.
- [ ] Client authentication uses actual Windows identity.
- [ ] Per-capability, target, mode, and expiration authorization works.
- [ ] Unapproved operations are denied.
- [ ] Arbitrary elevated shell execution is impossible through the public interface.
- [ ] Trusted code and policy are protected from unprivileged agent writes.
- [ ] Mutations default to dry-run.
- [ ] Explicit apply and a valid mutation grant are both required.
- [ ] Approved PowerShell/Python operations execute successfully.
- [ ] Agent retrieves structured results and evidence.
- [ ] Duplicate request IDs do not duplicate execution.
- [ ] Broker crashes cannot trigger automatic mutation replay.
- [ ] Conflicting target mutations are rejected.
- [ ] Guest credentials do not appear in client requests or logs.
- [ ] Windows security controls are tested with real identities.
- [ ] Existing H4 validation logic is preserved.
- [ ] The agent can complete the approved multi-step H4 workflow without repeated copy/paste.

## 14. Source ownership and Git workflow

PrivExec owns:

`modules/privileged_execution/**`

Necessary limited shared modifications may include:

- CLI registry entry.
- Package/setup registration.
- Relevant tests and documentation.

Resource Coordinator retains exclusive ownership of:

`modules/resource_coordinator/**`

Treat `modules/agent_sync/**` and `modules/vm_lab/**` as read-only references unless explicitly authorized otherwise.

Create a dedicated branch and worktree from the appropriate verified checkpoint.

Do not modify, reset, merge, or rebase an active agent's checkout.

Use local checkpoint commits.

Do not push or merge without explicit authorization.

## 15. Expected deliverables

- Packaged `privexec` Python CLI.
- C#/.NET session broker.
- Minimal protected capability descriptors.
- Operator startup and controlled shutdown.
- Idempotent setup/install scripts with dry-run.
- SQLite operation records.
- Structured request/result contract.
- Synthetic security and reliability tests.
- H4 reference integration.
- Windows validation instructions.
- Project-local documentation.
- Reproducible evidence of executed tests.
- Final status and implementation summary.

Do not create separate deliverables for excluded features.

## 16. Complexity and risk

**Estimated engineering difficulty:** Moderate to high, primarily because of Windows identity isolation, protected script execution, crash behavior, and PowerShell Direct credential lifecycle—not because of the CLI or IPC protocol.

Expected relative effort:

| Phase | Complexity |
|---|---|
| Phase 0 | Low |
| Phase 1 | Medium–High |
| Phase 2 | Medium–High |
| Phase 3 | High |

Primary risks:

1. Confusing elevation with a true security boundary.
2. Allowing an untrusted parameter to influence executed code.
3. Running agent-modifiable scripts with administrator privileges.
4. Accidentally duplicating mutations following a crash.
5. Exposing PowerShell Direct credentials.
6. Interfering with the active H4 worktree.
7. Adding unnecessary framework features that delay the actual H4 workflow.

Scope should not expand to solve these risks by introducing an unrelated orchestration system.

## 17. Authoritative references

Repository:

- https://github.com/MaxCarlson/scripts
- https://github.com/MaxCarlson/scripts/blob/main/MODULE_STANDARDS.md
- https://github.com/MaxCarlson/scripts/blob/main/docs/agent/PYTHON_REPO_STANDARDS.md
- https://github.com/MaxCarlson/scripts/blob/main/docs/agent/SCRIPTS_REPO_STANDARDS.md
- https://github.com/MaxCarlson/scripts/blob/main/docs/agent/LEGACY_PLANNING_MIGRATION.md
- https://github.com/MaxCarlson/scripts/blob/main/modules/agent_sync/README.md

Windows security:

- https://learn.microsoft.com/en-us/troubleshoot/windows-server/windows-security/disable-user-account-control
- https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights
- https://learn.microsoft.com/en-us/windows/win32/ipc/impersonating-a-named-pipe-client
- https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-createnamedpipew
- https://learn.microsoft.com/en-us/dotnet/api/system.io.pipes.namedpipeserverstreamacl.create

PowerShell and Hyper-V:

- https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/powershell-direct
- https://learn.microsoft.com/en-us/powershell/scripting/security/remoting/jea/security-considerations

## 18. Final governing requirement

**Implement the smallest secure system that lets an agent request an already-authorized elevated operation, execute it through trusted existing tooling, and consume its results.**

The implementation is finished when that workflow works reliably against H4 and satisfies the security acceptance criteria.

Do not add features without a demonstrated need.
