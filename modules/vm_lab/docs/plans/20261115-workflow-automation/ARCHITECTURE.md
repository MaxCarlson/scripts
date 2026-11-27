# Architecture and Interface Contracts (Design Proposal)

**Status:** proposed, to be audited and frozen in Phase 0. The JSON sketches below are *not* live APIs. The implementer must preserve existing `vm-lab` exports/CLI semantics.

## 1. System boundaries

```text
User / authorized local coding agent
       |
       +--> vm-lab plan/status/diagnose (no elevation if no Hyper-V call)
       +--> vm-lab workflow apply/resume (explicit capabilities)
                    |
             Typed workflow engine
             - input/schema validation
             - immutable operation identity
             - DAG transitions + receipts
             - artifact/evidence catalogs
             - recovery/reconciliation
                    |
         Bounded operations and guest executor
          |            |           |             |
      Hyper-V VM   PS Direct   Artifact store  Evidence store
      lifecycle    sessions    with hashes    with receipts
                    |
          External project-provided guest entrypoint
          (e.g. RC windows_acceptance.py; not in vm-lab)
```

**No general privileged API**: workflows describe typed operations and validated inputs; `guest.exec` runs only in an authenticated, exact-ID owned Windows guest with a pinned trusted executable/script and scoped, explicit mutation approval. Host-side scripts are never deserialized and executed from arbitrary workflow fields.

## 2. Proposed CLI contract

Prefer extending the current `Invoke-VmLab.ps1` operation dispatch and `vm-lab.cmd` launcher. Candidate syntax (finalize in Phase 0):

```powershell
vm-lab -o workflow-plan -f .\workflow.json -j
vm-lab -o workflow-status -OperationId <id> -j
vm-lab -o workflow-apply -f .\workflow.json -a -AuthorizeHostMutation -j
vm-lab -o workflow-resume -OperationId <id> -a -AuthorizeGuestMutation -j
vm-lab -o workflow-evidence -OperationId <id> -j
vm-lab -o workflow-doctor -OperationId <id> -j
```

Requirements: short *and* long flag names for newly added parameters; no incompatible rename of `-o/-n/-t/-r/-a/-j`; CLI help/examples match exactly implemented choices. If `-f` clashes with existing aliases, choose a different new short alias, document it, and retain backward compatibility. `-WhatIf` overrides apply on all mutation paths. No prompt on JSON output except explicitly requested secure credential prompt in an interactive host session.

**Top-level structured result** (concept):

```json
{
  "schema_version": 1,
  "status": "AWAITING_INTERACTION",
  "reason_code": "windows_oobe_pending",
  "operation_id": "20261115-143723-e58eb8ae",
  "vm": {"host": "XERES", "name": "Example-VM", "id": "<uuid>", "owned": true},
  "stage": "windows_install",
  "next_action": "Complete supported guest account creation, then resume",
  "evidence_root": "C:\\VM-Lab-Operations\\<operation-id>",
  "pending_capabilities": ["guest_setup"],
  "results": [],
  "exit_code": 0
}
```

An intentional hold can have exit code 0 *only* if the caller explicitly requested a hold-producing stage and `status` makes incomplete workflow evident. A final requested acceptance run must exit nonzero unless all required stages pass. Define and test exact exit semantics: 0 completed requested contract; 2 awaited authorized interaction; 3 blocked/denied; 4 invariant/trust failure; 5 incomplete evidence; 1 generic failure (codes are proposals subject to Phase 0 compatibility review). Never require callers to guess from an exit code alone.

## 3. Workflow definition schema v1

Use strict JSON decoding with explicit allowed keys and types. Reject unknown operation types and schema versions. Workflow is a *plan of typed actions*, not PowerShell source.

```json
{
  "schema_version": 1,
  "workflow_id": "example-windows-acceptance",
  "vm": {
    "template": "windows11-dev",
    "name": "Example-VM",
    "root": "C:\\VMs\\Example-VM",
    "iso": "C:\\ISOs\\Win11.iso",
    "network_policy": "disconnected",
    "guest_identity": {"os": "Windows 11", "architecture": "x64", "require_local_admin": true}
  },
  "operation_root": "C:\\VM-Lab-Operations",
  "stages": [
    {"id": "preflight", "type": "host.preflight", "depends_on": []},
    {"id": "create", "type": "vm.create", "depends_on": ["preflight"], "capability": "host_mutation"},
    {"id": "os_handoff", "type": "windows.install_handoff", "depends_on": ["create"]},
    {"id": "ready", "type": "guest.wait", "depends_on": ["os_handoff"]},
    {"id": "deploy", "type": "artifact.deploy", "depends_on": ["ready"], "manifest": "artifacts.json", "capability": "guest_mutation"},
    {"id": "checkpoint", "type": "vm.checkpoint_transaction", "depends_on": ["deploy"], "checkpoint_type": "Standard", "require_off": true, "capability": "vm_lifecycle"},
    {"id": "restart", "type": "vm.start", "depends_on": ["checkpoint"], "capability": "vm_lifecycle"},
    {"id": "ready_again", "type": "guest.wait", "depends_on": ["restart"]},
    {"id": "accept", "type": "guest.exec", "depends_on": ["ready_again"], "command_ref": "project_acceptance", "capability": "guest_mutation"},
    {"id": "evidence", "type": "evidence.collect", "depends_on": ["accept"]}
  ]
}
```

**Design corrections required before implementation:** the example illustrates ordering but is not a runnable plan: `artifact.deploy` requires a concrete artifact manifest, `guest.exec` requires a trusted project command descriptor, and `windows.install_handoff` must specify an interaction/resume policy. The implementation schema must catch invalid VM power-state edges at *plan time*. `guest.exec` requires a trusted external command descriptor with exact artifact digest, working directory, args and output policy, not a free-form `command` string. Never assume a workflow author is trusted merely because the file is local.

### Typed operation catalog (initial)

| Type | Inputs | Preconditions | Postconditions/evidence |
|---|---|---|---|
| `host.preflight` | host resource floors, ISO refs, artifact manifest | read-only | inspected host/ISO/permissions and confidence |
| `vm.create` | validated existing template/config | unique root/name, capacity, authorized | exact VM ID, manifest path, observed Hyper-V settings |
| `vm.connect` | VM ID | interactive desktop | launched or explicit headless blocker |
| `windows.install_handoff` | answer media option, completion policy | created VM | `AWAITING_INTERACTION` until guest provably ready |
| `guest.wait` | timeout, backoff, identity policy | running Windows guest | heartbeat/PS Direct credentialed probe, exact OS/build/user/admin |
| `artifact.deploy` | pinned manifest, destination | verified guest/paths/authorization | per-file hash/source fingerprint/receipt |
| `guest.bootstrap` | profile, pinned installer/wheels/requirements | authorized, transferred inputs | verified runtime and per-profile receipt |
| `guest.exec` | pinned command ref, args, cwd, env, timeout | guest identity + mutation policy | exit code, stdout/stderr, result JSON, duration |
| `vm.shutdown` | graceful timeout | exact owned VM | confirmed Off, else `PARTIAL` |
| `vm.checkpoint_transaction` | name/type/Off requirement/restart policy | guest/capability checks | checkpoint ID/type/time, power state and readiness |
| `vm.start` | VM ID, headroom reserve | exact owned Off | confirmed Running, not just `Start-VM` returned |
| `evidence.collect` | approved guest roots/files/globs and host destination | authenticated guest, safe paths | retrieved manifest, hashes, statuses, partial-copy hints |
| `workflow.assert` | declarative receipt/status constraints | prior stage receipts | verifiable gate, no arbitrary host code |

**Project-owned stages:** project-specific acceptance/mutation happens *inside* `guest.exec` via a pinned external runner. RC's `offline/task/full/rollback/cleanup` matrix remains RC-provided. Module must support matrix iteration, fail-fast, per-phase evidence and cleanup callback decisions, but must not encode RC's authorization phrase or task names.

## 4. Operation journal and stage receipts

Persist under an explicitly chosen operation root, separate from VM ownership manifests:

```text
<operation-root>/<operation-id>/
  workflow.json              # immutable normalized definition and digest
  operation.json             # atomic current-state journal
  approvals.json             # metadata/capability IDs only, never credentials
  receipts/<stage-id>/<attempt>.json
  artifacts/manifest.json
  evidence/<stage-id>/...
  logs/<stage-id>-<attempt>.stdout.log
  logs/<stage-id>-<attempt>.stderr.log
  diagnostic/status.json
```

`operation_id`: generated once; a supplied reuse must match the immutable workflow digest, exact VM identity/host/root, and journal schema. Normalize path case/drive; reject UNC, `..` traversal, reparse ancestors and path escape. Never place operation state inside a mutable third-party project source tree.

**Journal minimum fields:** `schema_version`, `operation_id`, `workflow_id`, `workflow_digest`, `host_identity`, `vm_id`, `vm_name`, `vm_config_path`, `owner_namespace`, `created_at`, `updated_at`, `overall_state`, `stage_states`, `last_attempt`, `evidence_index`, `last_error`, `approval_requirements`, `code_version`.

**Stage receipt minimum fields:** `stage_id`, `stage_type`, `attempt`, `input_digest`, `dependency_receipts`, `actor`, `started_at`, `finished_at`, `observed_before`, `observed_after`, `authorization_capability`, `result_status`, `reason_code`, `exit_code`, `output_hashes`, `remote/host evidence paths`, `recovery_hint`.

**Receipt trust:** do not trust marker `completed=true` alone; verify underlying postconditions and external artifact digests. Receipt content cannot be treated as authority to change a VM. Approvals expire at phase/request boundary and must be checked again on resume, even if a stale approval record exists.

**Atomic writes:** temporary file in same directory, exclusive create, flush when available, no unsafe overwrite of existing receipt; journal updates replace atomically. Support crash injection before write, during rename and after mutation but before receipt. Make stage re-probe/reconcile handle all three without duplicating external effects.

## 5. Guest identity and isolation policy

Reusable policy fields: expected VM Hyper-V GUID, host ID, name, guest OS caption/build/architecture, Hyper-V virtual hardware manufacturer/model, expected guest hostname (optional), local guest admin token, PowerShell Direct account identity, network policy (`disconnected` default), forbidden services/tasks/processes, allowed guest test root(s). Require fresh observation before mutation; a cached `guest_status` is insufficient.

For H4-like tests, RC adapter can require no pre-existing RC/KRig tasks, services or processes and no occupied listener port; the generic module supplies an inventory-query interface and fails closed if a required query is unavailable. Avoid baking RC names into core.

**Unmanaged H4 VM:** preserve read-only inspection only. A future delegation interface may allow scoped operations under a signed external owner policy, but that is a distinct architecture decision with separate tests/authorization. For now, newly created `vm_lab` VMs are the primary supported target.

## 6. Artifact trust and transfer contract

An artifact manifest lists relative paths, exact byte lengths, SHA-256, expected destination, and optional publisher signature metadata. Project-supplied manifests for guest files must have an independently trusted root digest (from release evidence or authorized source). A locally computed digest is useful for transfer stability but not for authenticity.

For each artifact: verify source, stage to unique temp inside approved guest root, verify guest-side hash, atomically commit (same volume), and record receipt. If interrupted, compare source and staged/destination hashes; resume without overwriting content not explicitly owned by this operation. For directories, enumerate recursively with junction/symlink rejection, stable relative names and collision rules. Support big installers/archives/wheelhouses and per-file progress, avoiding indiscriminate re-copying of unchanged files.

**Evidence pull:** preserve guest directory tree; manifest all files and SHA-256, transfer in batches, maintain partial status with per-file retry, capture stdout/stderr/JSON even when the guest command fails. Evidence is not declared complete until expected paths and counts match; never convert RC `FAIL` into PASS after cleanup.

## 7. Guest command contract

Inputs: pinned guest executable or script artifact hash, argument **array**, working directory, explicit allowlisted environment overrides, timeouts, output size limit/truncation policy, expected result JSON schema, idempotency class (`read_only`, `replayable`, `non_repeatable`), authorized mutation capability.

Process launch must not perform shell interpolation by concatenating untrusted strings. Use PowerShell `& $exe @args` or equivalent with careful exit code collection; separate PowerShell terminating exceptions from child exit codes. Do not serialize credential-bearing environment variables. Capture guest PID/run ID where feasible, and support disconnection reconciliation for long-running commands. A timeout must not imply a process stopped; classify as unknown/partial until verified. Do not blindly rerun `non_repeatable` tasks after transport loss.

For acceptance phases: project supplies argv, expected JSON output (`status='passed'`), and project result policy (e.g. no skipped real Scheduled Task tests). Module keeps output and exit code distinct; project may define stricter assertions via typed result predicates. Project cleanup is an external explicit step, not generic forced-delete.

## 8. Lifecycle checkpoint transaction

Sequence:

1. Verify exact owned VM ID/name/config path, policy `Standard`, snapshot uniqueness and disk capacity.
2. Verify guest prerequisites/receipts for requested qualified baseline; record intended pre-state.
3. Close PS Direct sessions before shutdown.
4. Request graceful `Stop-VM -VM $vm` without `-Force`/`-TurnOff`; bounded poll for `Off`.
5. On timeout, record `PARTIAL/shutdown_not_confirmed` and **do not** checkpoint.
6. Reacquire VM object by ID and verify name/path/owner; `Checkpoint-VM -VM $vm -SnapshotName ... -Passthru`.
7. Verify exact snapshot ID/name/type/CreationTime via `Get-VMSnapshot -VM $vm`; write receipt.
8. Optionally `Start-VM -VM $vm` with fresh RAM headroom checks; poll `Running`, heartbeat, authenticated PS Direct, guest identity.
9. Record `ready`, `awaiting_credentials`, or `partial/restart_failed`; never mark completed just because `Start-VM` returned.

**Standard vs Production:** specifically require and verify Standard where a lab demands it; do not substitute silently. Power-off before Standard checkpoint avoids capturing running memory state but is a project policy, not mandatory for all VM uses.

## 9. Privilege boundary: bounded operator execution

Separate unprivileged agent **planning** from elevated local operator **execution**. Implement a foreground, explicit opt-in PowerShell entry point (e.g. `Invoke-VmLabApprovedPlan.ps1`) reading a schema-checked typed request with plan digest, VM ID, expected stage, capability IDs, path restrictions and bounded expiration. The elevated operator verifies request in a privileged session and uses only compiled module operations. No arbitrary host code, serialized scriptblocks or direct shell strings. No standing privileged Windows service, scheduled task, network listener or UAC bypass.

The run creates a signed/hashed evidence transcript (authentication/signature scheme finalized during Phase 4; **hash alone does not prove caller authorization**), a result JSON file and strict exit code. The agent can inspect results after the operator executes the approved request. Do not allow reusing one approval for a modified plan; no automatic privilege persistence. Ask operator approval at defined mutation boundary; credentials remain in memory only.

A typed `guest.exec` itself allows execution of guest programs; limit this to explicitly pinned guest files and expected role, with a separate `guest_command` approval rather than assuming every VM creation approval grants arbitrary guest code execution.

## 10. Host resource and workload coordination

Record CPU count, host available RAM, VM startup/dynamic limits, disk capacity and expected VHDX max. Use a configurable host reserve (current default: 4 GiB) plus an optional external reservation/lock for concurrent workers. Re-check immediately before Start-VM. Read-only probes may sample active processes; do not stop KRig, WSL, Docker, LM Studio, mining or production services for headroom. No false guarantee based on one-time RAM observations.

## 11. Windows installation options

A) Interactive boot/OOBE supported by default, with explicit `AWAITING_INTERACTION` and next-step guidance. B) Optional answer-file media with validated `Autounattend.xml`, supported installation choices, and no stored account password. C) Optional prepared guest image using documented `Sysprep /generalize /oobe /shutdown` and licensing/activation considerations. Phase 5 must validate Windows release/build behavior rather than depend on undocumented OOBE bypasses.

Provide evidence of answer media mounted and Windows Setup actual progress; simply generating XML is not equivalent to completing installation. Keep installation-specific disk modification scoped exclusively to a **new empty owned VHDX**.

## 12. Compatibility, testing and design review

- Existing functions/flags/ownership manifest must remain supported.
- Schema evolution: reject unknown major versions and provide read-only migration of known legacy records; do not silently rewrite existing state.
- No read-only command may mutate VM, disks, network or guest.
- T1 fake adapters execute *real orchestration* while mocking Hyper-V and PS Direct boundaries; T4 probes actually execute on a separate disposable guest.
- Validate Windows 11 host/guest, PowerShell 7 host, PowerShell Direct initial guest (Windows PowerShell may be available before PowerShell 7 install); inspect exact Hyper-V cmdlet parameter sets before implementation.
- Preserve test artifacts for success and all failure modes; run PowerShell Pester plus Python toolkit suites and a clean-process CLI check.

### Phase 0 Finalized Decisions (Implemented in `src/Contracts.ps1`)
- `-f` (`-WorkflowPath`) does not collide with existing aliases (`o,n,c,t,i,r,s,m,a,j,oo,rb,st,mr`), so `-WorkflowPath` (`-f`), `-OperationId` (`-op`), `-OperationRoot` (`-or`), `-ArtifactManifestPath` (`-am`), `-CommandRef` (`-cr`), `-EvidenceRoot` (`-er`) are finalized.
- Strict JSON schema validators (`Test-VmLabWorkflowSchema`, `Test-VmLabArtifactManifestSchema`, `Test-VmLabOperationJournalSchema`, `Test-VmLabStageReceiptSchema`), deterministic canonical SHA-256 (`Get-VmLabCanonicalSha256`), path containment/reparse safety (`Test-VmLabSafePath`), protected VM registry (`Assert-VmLabTargetNotProtected`), and capability checks (`Test-VmLabCapabilityAuthorized`) are implemented in `modules/vm_lab/src/Contracts.ps1`.

- Confirm exact workflow CLI verb set and flag short aliases.
- Confirm JSON schema field names and durable store root semantics.
- Define whether `guest.exec` restricts to pinned files only or also supports narrowly allowlisted read-only built-ins.
- Choose explicit response to mid-execution guest disconnect (probe with operation run ID vs block on uncertainty).
- Define approval token schema and how operator identity/intent are established without persistent credentials.
- Define how external projects register workflow definitions and expected output schemas without giving them host execution authority.
- Determine whether a fresh Windows guest can be operationally qualified without upgrading H4's active guest; never use active H4 as surrogate.
