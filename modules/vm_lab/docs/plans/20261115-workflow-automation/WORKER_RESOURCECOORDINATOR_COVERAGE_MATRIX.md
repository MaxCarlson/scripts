# Worker-ResourceCoordinator VM Coverage and Regression Matrix

**Purpose:** this is the acceptance ledger for *everything VM-related observed in the Worker-ResourceCoordinator conversation and examined H4 source*. An implementation phase is not complete while its corresponding rows remain unaccounted for.

Legend: `EXISTING` = current `vm-lab` covers a basic operation (not necessarily real-host-qualified); `PARTIAL` = reusable primitive exists but H4 orchestration is missing; `MISSING` = requires new generic functionality; `PROJECT` = application-specific logic stays outside vm-lab, which must support launching/evidencing it. Evidence: `HISTORY` = reconstructed from conversation, `SOURCE` = checked in named H4 source files, `BOTH`.

## A. VM provisioning and Windows installation

| ID | Observed H4 task or problem | Coverage today | Needed module/CLI behavior | Phase | Evidence | Status |
|---|---|---|---|---|---|---|
| A01 | Check Hyper-V host privileges; non-elevated Codex `Get-VM` permission denied | PARTIAL | Diagnostic preflight and deferred authorized operation request | 0,4 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| A02 | Verify host identity XERES, available RAM and disk while KRig/WSL may run | PARTIAL | Resource capacity and reservation/readiness recheck, never stop workloads | 0,2,4 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| A03 | Validate downloaded Win11 ISO readable, size and hash vs trusted expected release | PARTIAL | Artifact trust policy with expected source SHA/publisher evidence | 1 | SOURCE | SUPPORTED_AND_TESTED (mocked) |
| A04 | Validate path containment, UNC rejection, junction/reparse ancestors, no existing VHDX | EXISTING | Regression gate; keep strict fail-closed behavior | 0,6 | SOURCE | SUPPORTED_AND_TESTED |
| A05 | Gen2 4-vCPU VM with 4–8 GiB Dynamic RAM, 80 GiB Dynamic VHDX | EXISTING | Template replay and live configuration proof | 0,6 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| A06 | Secure Boot MicrosoftWindows, local key protector + vTPM | EXISTING | Exact config verification, deterministic failure | 0,6 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| A07 | Configure Standard checkpoints, disable automatic checkpoints | EXISTING | Verify actual policy before transaction | 2 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| A08 | No virtual NIC by default; explicit switch only if approved | EXISTING | Preserve network-isolated install/setup | 0,5 | BOTH | SUPPORTED_AND_TESTED (mocked) |
| A09 | ISO attached as SCSI DVD; set DVD ahead of VHDX in UEFI boot order | EXISTING | Plan/show verified firmware boot order, failure diagnostics | 5 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| A10 | Do not auto-start VM after provisioning | EXISTING | Separate capability to authorize creation vs startup | 0,4 | SOURCE | SUPPORTED_AND_TESTED (mocked) |
| A11 | Initial `SCSI DVD boot loader failed` after missed "Press any key" prompt | PARTIAL | VMConnect integrated install guide, controlled retry, boot diagnostics | 5 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| A12 | Windows 11 installation via VMConnect and local guest OOBE account | PARTIAL | Installation state machine, prompt handoff, answer media optional | 5 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| A13 | OOBE network-required screen with no NIC | MISSING | Offline-local-account assistance using supported Windows mechanisms; no undocumented bypass dependency | 5 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| A14 | Downloaded installer/Windows build compatible with guest and offline isolation | PARTIAL | ISO version/release and guest build checks; no assumption 4-MiB VHD means not installed | 0,5 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| A15 | Need to create future VMs without manually setting Hyper-V flags again | EXISTING | One declarative plan and quickstart used by workflow | 3,6 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |

## B. Guest connectivity, provenance and prerequisites

| ID | H4 operation/problem | Coverage today | Required outcome | Phase | Evidence | Status |
|---|---|---|---|---|---|---|
| B01 | Establish `New-PSSession -VMId` after guest login without guest networking | EXISTING | Bounded authenticated readiness/retry and session cleanup | 0,2 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B02 | Local guest `DESKTOP-1ITSJV0\mcarls` vs host XERES; insist on guest Administrator | PARTIAL | Configurable credential hint and independent identity/admin checks | 1 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B03 | Verify Windows 11 Pro build/arch and Hyper-V manufacturer/model | PARTIAL | Reusable typed guest policy with fail-closed queries | 1 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B04 | Preflight no RC/KRig tasks/services/processes in guest | PROJECT | Declarative inventory rules, project asserts actual names and safe test root | 1,3 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| B05 | Verify listener port/ownership not interfering with host/guest services | PROJECT | Guest inventory adapter + project-owned TCP assertions | 1,3 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| B06 | Transfer Python 3.12 x64 and PowerShell 7 MSI installers | PARTIAL | Multi-file deployment, pinned SHA, resume | 1 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B07 | Transfer 26 pinned wheels and wheel hash manifest | PARTIAL | Recursive file/directory artifact manifest, per-file verification | 1 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B08 | Transfer bundle ZIP, standalone bootstrap script and verify source+guest digest | PARTIAL | Trust root digest, immutable staging, exact destinations | 1 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B09 | Verify all transferred files inside guest before using them | PARTIAL | Transfer receipt only on guest hash/postcondition success | 1 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B10 | Install MSI/Python quietly; handle exit code 3010 requiring reboot | PARTIAL | Multi-profile orchestration and explicit `REBOOT_REQUIRED` | 1,2,3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B11 | Resolve installed `pwsh.exe`/Python paths after PATH change | EXISTING | Regression and real verification; no stale PATH false failure | 0,6 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B12 | Create venv and install requirements offline from wheelhouse | EXISTING | Multi-command profile plus actual pinned dependency check, no online fallback | 1 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B13 | Check imports for anyio/httpx/starlette/uvicorn/psutil/yaml/rich/pytest/resource_metrics | PROJECT | Generic `guest.exec` with explicit import probe/pinned test command | 1,3 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| B14 | Verify archive integrity and extract immutable bundle without overwrite | MISSING | Trusted archive unpack action or pinned guest verifier and receipt | 1 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B15 | Verify manifest/components of extracted bundle, both old/new RC sources | PROJECT | Execute project verifier through trusted guest script; generic result receipt | 1,3 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| B16 | Write setup receipt on guest linking exact bundle SHA, paths, operation ID | MISSING | Durable typed stage receipt; project-specific fields supported as extra results | 3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B17 | Guest preflight with source manifest, test root and exact JSON status | MISSING | `guest.exec` stdout+stderr+exit code and structured project predicates | 1,3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| B18 | Avoid rerunning successful guest Setup and overwriting bundle directories | PARTIAL | Reconcile stage receipts and postconditions before retry | 3 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |

## C. Checkpoint, restart, guest readiness and failure recovery

| ID | H4 operation/problem | Coverage today | Required outcome | Phase | Evidence | Status |
|---|---|---|---|---|---|---|
| C01 | Preserve operation ID `20261115-143723-e58eb8ae` across Setup, Checkpoint, Acceptance | MISSING | Operation journal/immutable ID and stage linkage | 3 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C02 | Original Setup receipt reused by later acceptance; never invent new Setup operation | MISSING | Receipt pinning + stale/forged mismatch rejection | 3 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C03 | Retry checkpoint after first failure without repeating setup | MISSING | Resume checkpoint stage, validate setup and live VM | 2,3 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C04 | `Stop-VM -Id` was invalid; need `-VM` with verified object | EXISTING basic | Correct adapter and real version/cmdlet signature tests | 2,6 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C05 | Close PS Direct session before graceful Stop-VM | PARTIAL | Lifecycle transaction state machine | 2 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C06 | Poll VM Off for up to bounded timeout, never hard shutdown | PARTIAL | Confirm Off or `PARTIAL`; checkpoint forbidden on unconfirmed state | 2 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C07 | Enforce Standard checkpoint; avoid Production/automatic substitutions | PARTIAL | Verify `CheckpointType` and snapshot type | 2 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C08 | Check duplicate name; record exact checkpoint ID/name/time | EXISTING | Checkpoint receipt with trustworthy live postcondition | 2,3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C09 | Checkpoint failure must be `FAIL`, not `NOT_RUN` | PARTIAL | Explicit stage statuses even after exceptions | 2,3 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C10 | Restart using verified `Start-VM -VM`, not `-Id` | PARTIAL | Start stage with exact object re-probe | 2 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C11 | Wait/retry PowerShell Direct after restart with deadline | PARTIAL | Guest readiness primitive with bounded heartbeat/auth probe | 2 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C12 | Resume after host session died / user PowerShell console closed | MISSING | Persistent journal, operation lock and recovery doctor | 3,4 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C13 | Preserve evidence in distinct roots for setup/checkpoint/acceptance | PARTIAL | Unified evidence index without overwriting per-stage source data | 3 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| C14 | Detect ongoing versus stale lock without auto-deletion | EXISTING basic | Lock lease/process verification and safe recovery guidance | 3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |

## D. Project acceptance execution, rollback and evidence

| ID | H4 operation/problem | Coverage today | Required generic infrastructure | Phase | Evidence | Status |
|---|---|---|---|---|---|---|
| D01 | Run offline/read-only profile against fresh guest test root | MISSING | Generic `guest.exec` typed command, JSON/exit parsing | 1,3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| D02 | Run real Task Scheduler helper profile; skip count must be zero | PROJECT | Allow project-defined result predicate; reject false passes | 3 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| D03 | Run full install/upgrade profile RC 0.14.0 → RC 1.0.0 | PROJECT | Pinned command descriptor; timeout, evidence and authorization | 1,3 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| D04 | Historically test compatibility with RC 0.11.3, separate from upgrade | PROJECT | Support additional project profile and source proof; not generic logic | 3 | HISTORY | PROJECT_SPECIFIC (synthetic runner tested) |
| D05 | Run rollback with 5 fault stages | PROJECT | Parameterized matrix expansion, fail fast and per-run receipt | 3 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| D06 | Exact five fault labels: `after_prepared_receipt`, `after_old_service_stopped`, `before_task_replacement`, `after_task_replacement`, `after_new_service_ready` | PROJECT | Preserve project-supplied enumeration and validation; do not hardcode labels in vm_lab core | 0,3 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| D07 | Ensure guest-side test root prefix `h4-rc-*` and clean inventories | PROJECT | Stage policy + project validation callback, no names in core | 3 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| D08 | Require separate application-level guest mutation authorization phrase | PROJECT | Generic capability gate; forward project-specific authorized value only within guest process | 3,4 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| D09 | Inject `PYTHONPATH`, temporary authorization env, `cwd`, args array | MISSING | Environment-allowlisted guest command executor | 1 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| D10 | Capture JSON `status`, raw stdout/stderr, process exit code, elapsed time | MISSING | Reliable guest command receipts, fail if malformed | 1,3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| D11 | On phase failure run scoped project cleanup but retain original FAIL | PROJECT | Conditional external cleanup stage; never mask original failure | 3 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| D12 | Copy entire evidence directory back from guest using `Copy-Item -FromSession -Recurse` | MISSING | Recursive evidence collector, path containment and manifest | 1,3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| D13 | Evidence copy fails -> INCOMPLETE + retry hint, not PASS | MISSING | Per-file durable download receipts and recovery | 1,3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| D14 | Save `matrix-summary.json`, `final-summary.json`, guest identity and output files | MISSING | Stable evidence index and host-side journal projections | 3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| D15 | Parse `status=passed` with exit 0; reject real Task Scheduler skipped tests | PROJECT | Policy predicates separate from generic process completion | 3 | SOURCE | PROJECT_SPECIFIC (synthetic runner tested) |
| D16 | Stop acceptance on failure or incomplete evidence; preserve guest artifacts | MISSING | Dependency policies, stop-on-failure and resume evidence-only stage | 3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| D17 | Distinguish FAIL/BLOCKED/INCOMPLETE/NOT_RUN and infrastructure vs app failure | MISSING | Structured error taxonomy + exit mapping | 3 | SOURCE | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| D18 | Use different host evidence roots for checkpoint retry and acceptance retry | PARTIAL | One operation with separate immutable stage attempts | 3 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |

## E. Agent-execution ergonomics, safety and operations

| ID | Observed pain point | Coverage today | Required outcome | Phase | Evidence | Status |
|---|---|---|---|---|---|---|
| E01 | Local Codex agent could not run elevated Hyper-V; user manually copied scripts | MISSING | Bounded foreground elevated runner, plan approval and result receipt | 4 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| E02 | Command blocks manually inserted into admin pwsh, repeated credentials | MISSING | Single approved runner, secure interactive guest credential prompt per session | 4 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| E03 | Agent needed to know when user intervention was required | MISSING | `AWAITING_INTERACTION`/authorization reason and next action; optional notification integration later | 3,4 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| E04 | Model worker must not silently start WSL/LM Studio or local LLM inference | PROHIBITED | Explicit no-inference/no-unrelated-workload constraint in execution policy | 0–6 | HISTORY | SUPPORTED_AND_TESTED |
| E05 | Preserve running production RC/KRig and avoid disrupting GPU/mining | PROHIBITED | Read-only resource checks, safe host reserves, no service stop | 0–6 | BOTH | SUPPORTED_AND_TESTED |
| E06 | Need short/long aliases, JSON and launcher invocation telemetry | EXISTING | Extend current API and regression test through `scripts_help`/`script_logging` | 0,3,6 | BOTH | SUPPORTED_AND_TESTED |
| E07 | Avoid untrusted local script/version drift; hash verify exact wrapper and bundle | PARTIAL | Pinned plan/script SHA and provenance inspection | 1,4 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| E08 | Retry safety: no duplicate checkpoint, copied artifact or acceptance mutation | MISSING | Stage idempotency classes and postcondition re-probe | 3 | BOTH | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| E09 | Need detailed persistent phase plan, test/log/commit evidence for cross-agent handoffs | MISSING | Status/journal/evidence templates, validated checkpoints | 0,3,6 | HISTORY | SUPPORTED_AND_TESTED |
| E10 | Prefer next disposable VM, not modifying current H4 in parallel | PROHIBITED | Protected VM registry by exact ID and namespace; live test separate | 0,6 | BOTH | SUPPORTED_AND_TESTED |
| E11 | Need to know whether Setup/OS boot succeeded; VHDX 4-MiB size misleading | MISSING | Evidence-based install readiness and confidence/status | 5 | HISTORY | SUPPORTED_AND_TESTED (mocked); NOT_TESTED_REAL_VM |
| E12 | No deployment without source merge and real Hyper-V acceptance | PARTIAL | Separate source-integration vs operational qualification gates | 6 | HISTORY | PARTIAL; NOT_TESTED_REAL_VM |

## Coverage accounting rule

The implementer must maintain a machine-readable or markdown status column (`SUPPORTED_AND_TESTED`, `PARTIAL`, `UNSUPPORTED`, `PROJECT_SPECIFIC`, `NOT_TESTED_REAL_VM`) for **each ID** as phases are completed. Every `PROJECT` row needs a generic workflow demonstration that invokes a *synthetic project runner* with the same exit/status/evidence characteristics. Do not claim the module implements RC upgrade/rollback logic; it must make their *execution* reusable.

**Historical guard:** the H4 operation ID, guest paths and protected VM ID listed here are examples/context, **not credentials, deployment defaults or targets for new tests**. The underlying Worker-ResourceCoordinator conversation may have progressed; consult latest evidence before mentioning live state.

**Post-review contract note:** `Get-VmLabOperationCapabilityPolicy` enforces mandatory per-operation capabilities (including `evidence.collect` -> `host_mutation` and `vm.connect` -> `vm_lifecycle`), and checkpoint reconciliation (`C03`, `C07`, `C08`, `E08`) is aligned with the actual `Get-VmLabCheckpoint` (`name`, `id`, `snapshot_type`, `vm_name`, `created_at`) and `New-VmLabCheckpoint` (`checkpoint_created`, `snapshot_type`) contracts. Real Hyper-V VM lifecycle rows remain `NOT_TESTED_REAL_VM` until separately authorized live qualification.

## Source anchors

- H4 host qualification: `modules/resource_coordinator/tools/h4_qualification/Invoke-H4GuestQualification.ps1` inspected at `a1b9a3a4de5260e3614e42118a30c4a648bfb98d` (notably stages ~276–765).
- H4 VM creation: `modules/resource_coordinator/tools/h4_qualification/Provision-H4TestVM.ps1` inspected at accessible main, ~330 lines.
- H4 bundle bootstrap: `modules/resource_coordinator/tools/h4_qualification/Bootstrap-H4GuestBundle.ps1` ~106 lines.
- H4 guest acceptance: `modules/resource_coordinator/tools/h4_qualification/windows_acceptance.py` ~1095 lines.
- Current vm-lab: `modules/vm_lab/README.md`, `src/{Provisioning,Guest,Bootstrap,Checkpoints,Inventory,Lifecycle,Recovery,Output}.ps1`, smoke harness, tests at inspected `main`.
