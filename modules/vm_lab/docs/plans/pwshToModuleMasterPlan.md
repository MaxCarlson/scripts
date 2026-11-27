# Master Implementation Plan: vm_lab Python Migration and CLI Feature Completion

**Status:** PLANNED — implementation not started under this plan  
**Repository:** `MaxCarlson/scripts`  
**Primary module:** `modules/vm_lab`  
**Target operating system:** Windows 11 / PowerShell 7 / Hyper-V  
**Canonical CLIs:** `vm`, `vm-lab`  
**Source baseline:** Published main plus explicitly reported local uncommitted changes; verify both before implementation.

## 1. Mission

Convert the existing PowerShell-based `modules/vm_lab` directory into a properly packaged Python module with first-class command-line entry points `vm` and `vm-lab`.

Preserve the existing PowerShell Hyper-V implementation as the operational backend.

Extend the module so that generic VM provisioning, installation, troubleshooting, guest operations, lifecycle control, qualification orchestration and evidence management formerly performed through custom PowerShell in the Resource Coordinator H4 Windows workflow can instead be accessed through the Python CLI.

The outcome must be a coherent, installable, documented, agent-operable VM management application, not another collection of one-off launchers and scripts.

## 2. Success criteria

A successful implementation must satisfy all of the following:

1. `modules/vm_lab` is recognized as a Python distribution by the repository's ordinary installation pipeline.
2. Both `vm` and `vm-lab` install as console-script entry points and dispatch to the same Python application.
3. Running `bootstrap_latest.ps1` in a clean supported Windows environment discovers and installs both commands without any vm_lab-specific special case.
4. All existing PowerShell backend functionality remains available.
5. Existing PowerShell APIs and compatibility entry points remain functional.
6. Users can inspect and operate VMs through normal CLI subcommands, without constructing PowerShell invocation scripts.
7. The H4-derived generic VM operations identified in the coverage matrix have CLI support and appropriate tests.
8. Workflow execution honors every accepted security-relevant configuration field.
9. All mutating commands are dry-run by default and require explicit authorization.
10. VM identities, owner manifests, checkpoints, credentials and operation receipts are guarded against cross-VM or stale-state confusion.
11. The CLI returns meaningful exit codes, structured JSON, useful help and actionable failure diagnostics.
12. The Python distribution works as an editable installation and as an independently installed wheel.
13. Full regression validation passes before integration.
14. Real Hyper-V qualification is conducted only after separate authorization for a new disposable VM.

## 3. Architecture

### 3.1 Preserve the existing directory

Keep `modules/vm_lab` as the module's source directory.

Prefer the repository's existing `system_manager` packaging pattern: map the Python package name to the module's directory using setuptools `package-dir`.

This avoids having to relocate the PowerShell backend unnecessarily.

Proposed structure:

    modules/vm_lab/
        pyproject.toml
        __init__.py
        __main__.py
        cli.py
        backend.py
        commands.py
        exceptions.py
        results.py

        Invoke-VmLab.ps1
        Invoke-VmLabApprovedPlan.ps1
        vm_lab.psd1
        vm_lab.psm1

        src/
            ... existing PowerShell backend ...

        templates/
            ... existing templates ...

        examples/
            ... existing workflows ...

        tests/
            ... existing Pester tests ...
            test_cli.py
            test_backend.py
            test_packaging.py
            test_workflow_cli.py
            test_bootstrap_integration.py

        docs/
            ... existing documentation ...

The final file organization may be refined if packaging tests show a better approach.

Do not move existing PowerShell files solely for aesthetic consistency.

### 3.2 Python package metadata

Create a standards-compliant `pyproject.toml`.

Use setuptools, matching the existing repository's conventions.

Define both entry points:

    [project.scripts]
    vm = "vm_lab.cli:main"
    vm-lab = "vm_lab.cli:main"

Include PowerShell source files, module manifests, templates, and relevant workflow resources as package data.

Test the built wheel to ensure backend discovery works without relying on an editable source checkout or the developer's repository root.

Keep third-party Python dependencies minimal. Prefer the standard library for argument parsing, subprocess execution, JSON and path handling.

### 3.3 Python CLI

Use `argparse` with nested subcommands.

The CLI owns:

- Parsing, help and validation.
- User-facing command structure.
- Dry-run and approval options.
- Workflow selection and presentation.
- Structured results and exit-code mapping.
- Cross-platform environment detection.
- Secure backend invocation.
- Command logging and toolkit integration.

The Python CLI does not directly reimplement Hyper-V state mutation.

### 3.4 PowerShell backend

Retain the current `vm_lab.psm1` implementation for:

- Hyper-V provisioning.
- VM ownership verification.
- VM lifecycle management.
- Firmware, disk and checkpoint operations.
- PowerShell Direct.
- Guest bootstrap and execution.
- Artifact verification and transfer.
- Durable workflow execution and receipts.
- Elevated approved-plan execution.

Keep the backend independently testable with Pester.

### 3.5 Backend communication

Implement a small typed Python-to-PowerShell adapter.

Requirements:

- Invoke PowerShell with subprocess argument arrays, never untrusted shell command strings.
- Use `shell=False`.
- Resolve the packaged backend through an explicit, tested resource-location strategy.
- Keep passwords and credentials out of command-line arguments and persistent logs.
- Preserve interactive credential prompting when explicitly requested.
- Distinguish interactive and noninteractive operation modes.
- Emit a single machine-readable result when `--json` is enabled.
- Capture and propagate actual process exit codes.
- Map backend operation results into stable Python exceptions and result models.
- Avoid duplicate execution when a backend call is interrupted.
- Do not silently fall back to arbitrary PowerShell execution.

Windows-only operations must return clear unsupported-platform errors on Linux/macOS, while package import and help remain usable.

## 4. CLI interface specification

### 4.1 Command naming

Both entry points must behave identically:

    vm --help
    vm-lab --help

The canonical spelling in documentation may be `vm`.

Retain `vm-lab` indefinitely as a supported alias.

The legacy PowerShell syntax must remain accessible for compatibility, including existing `-o` operation usage. Document its status and test backward compatibility.

### 4.2 Required command groups

Proposed public interface:

    vm
    vm --help
    vm version
    vm doctor

    vm list
    vm inspect <name-or-id>
    vm create <name>
    vm start <name-or-id>
    vm stop <name-or-id>
    vm restart <name-or-id>
    vm connect <name-or-id>

    vm host doctor
    vm host resources

    vm media iso verify <path>
    vm media iso attach <vm> <path>
    vm boot inspect <vm>
    vm boot prepare <vm>
    vm boot troubleshoot <vm>

    vm setup plan <vm>
    vm setup status <vm>
    vm setup answer-media <vm>
    vm setup guide <vm>

    vm guest status <vm>
    vm guest wait <vm>
    vm guest identity <vm>
    vm guest inventory <vm>
    vm guest bootstrap <vm>
    vm guest exec <vm>
    vm guest run-script <vm>
    vm guest reboot <vm>

    vm artifact plan <vm>
    vm artifact deploy <vm>
    vm evidence collect <vm>
    vm evidence inspect <operation-id>

    vm checkpoint create <vm>
    vm checkpoint list <vm>
    vm checkpoint inspect <vm>
    vm checkpoint transaction <vm>

    vm workflow validate <file>
    vm workflow plan <file>
    vm workflow run <file>
    vm workflow status <operation-id>
    vm workflow resume <operation-id>
    vm workflow doctor <operation-id>
    vm workflow results <operation-id>

    vm approval request <file>
    vm approval inspect <request>
    vm approval execute <request>

These names are the proposed target, not existing verified commands.

The implementation agent must reconcile names with current public APIs before finalizing them.

### 4.3 CLI conventions

All commands must support:

- Contextual `-h` and `--help`.
- Appropriate short and long options such as `-n/--name`, `-i/--iso`, `-f/--file`, `-j/--json`, `-a/--apply`.
- Predictable subcommand parsing.
- Actionable input errors.
- Machine-readable JSON.
- Stable nonzero exit codes for failures and blocked operations.
- Explicit user approval for mutations.
- Proper Windows path quoting.
- Noninteractive execution when supported.
- No accidental interactive prompts in automation mode.

Use one documented exit-code taxonomy. Distinguish success, input error, authorization required, interaction required, execution failure, and incomplete evidence.

## 5. Feature requirements based on H4 qualification

### H01 — Exact VM targeting and identity

Support name and GUID lookup.

Verify a supplied name/ID pair against live Hyper-V inventory before mutation.

Expose ownership, configuration location, power state, guest identity, and checkpoint details through the CLI.

Reject protected or unmanaged VMs unless an explicitly designed ownership policy allows the requested read-only operation.

### H02 — Trusted ISO and VM provisioning

Add explicit expected ISO SHA-256 verification.

Preserve storage collision checks, vTPM, Secure Boot, Generation 2, dynamic memory and disconnected networking.

Provide preflight reports for host capacity, privileges, disk availability, ISO readability and Hyper-V service availability.

Never overwrite an existing VM or VHDX.

### H03 — Boot and installation troubleshooting

Expose read-only firmware, DVD and boot-order diagnostics.

Provide guarded media attachment/detachment and firmware boot preparation.

Detect common installation states where possible and explain whether user interaction is required.

Handle missed DVD boot prompts with a safe recovery procedure.

Do not disable Secure Boot or bypass Windows security requirements automatically.

### H04 — Windows Setup/OOBE integration

Extend current answer-file staging into a working setup-media workflow.

Support documenting and preparing offline Windows installation, guest account creation and guest-readiness checks.

Implement media attachment and verify whether the generated answer file is actually consumed.

Keep password handling secure.

Do not advertise unattended installation unless it is validated end to end.

### H05 — Guest credentials and connectivity

Support secure guest credential prompting and reusable session configuration within an authorized operation.

Validate PowerShell Direct availability, authentication failures and guest readiness.

Provide bounded retries, timeouts and helpful diagnostics.

Do not store plaintext passwords.

### H06 — Guest identity, inventories and safety checks

Expose read-only guest inventory commands for:

- Hostname, OS, architecture, local administrator status.
- Running processes.
- Windows services.
- Scheduled Tasks.
- Relevant system/runtime versions.

Allow caller-supplied identity policies and forbidden-resource checks.

Keep Resource Coordinator-specific process/task/service names outside vm_lab.

### H07 — Artifact and installer management

Expose trusted manifest-based deployment of files, directories, archives, Python wheels and installers.

Verify size and digest on both host and guest.

Support separate immutable source bundles, versioned destinations and setup receipts.

Allow an installer step to return REBOOT_REQUIRED without misclassifying it as success or unrecoverable failure.

### H08 — Generic guest execution

Support execution of trusted executables and verified script files.

Preserve exact argument arrays, working directories, allowed environment variables, stdout/stderr, exit codes and optional JSON results.

Provide a verified script digest or equivalent immutable artifact reference.

Implement bounded execution and honor configured timeouts.

Reject unsupported execution parameters rather than silently ignoring them.

### H09 — Guest reboot and readiness lifecycle

Expose a general graceful reboot operation.

Handle installer-required reboots, readiness polling, failed authentication, session cleanup and timeout recovery.

Bind the operation to the exact VM ID.

### H10 — Checkpoint operations

Expose named Standard checkpoints, powered-off checkpoint transactions, restart and readiness checks.

Allow inspection and verification using checkpoint ID as well as name.

Preserve checkpoint receipts and distinguish duplicate/conflicting checkpoints.

Do not add automatic checkpoint restoration or deletion in this scope.

### H11 — Durable workflow semantics

Complete support for:

- Stage-level timeouts.
- Idempotency classes.
- Guest identity policies.
- Conditional failure actions.
- Explicit pause/resume.
- VMConnect handoff.
- Exact operation and stage receipts.
- Typed failure classifications.

Unknown or unimplemented workflow fields must fail schema validation.

Recovery must verify real external state before replaying a potentially mutating operation.

### H12 — Acceptance and cleanup orchestration

Allow reusable matrices of project-specific guest execution stages.

Support conditional execution, stop-on-failure, skip policies and guarded cleanup.

Support generic JSON assertions including expected statuses, exit codes and required test outcomes.

Preserve the distinction between a failed acceptance test and an incomplete evidence transfer.

Never silently rerun an installer or destructive cleanup after ambiguous interruption.

### H13 — Evidence management

Expose guest evidence collection, transfer retries, digest verification and local inspection.

Support selecting an operation ID and identifying incomplete or missing artifacts.

Provide a concise summary of failed phases, relevant reason codes, evidence paths and next safe recovery actions.

Do not hardcode Resource Coordinator evidence schemas.

### H14 — Elevated operator and agent integration

Expose the existing approved-plan runner through the Python CLI.

Support request generation, digest presentation, capability review, expiration and single-use execution.

Keep UAC and authorization under operator control.

No permanent privileged service, UAC bypass or unrestricted host-shell endpoint.

## 6. Implementation phases

### Phase 0 — Baseline audit and working-tree preservation

**Objective:** Establish a reliable starting point without disturbing the existing repository.

Tasks:

1. Inspect `main`, `origin/main`, branches and active worktrees.
2. Inspect all uncommitted changes involving `bootstrap_latest.py`, `scripts_setup/launcher_generator.py` and `Invoke-VmLab.ps1`.
3. Preserve these modifications without resetting or overwriting the main checkout.
4. Create an isolated implementation branch/worktree from the latest validated checkpoint.
5. Inventory existing PowerShell exports, CLI operations, tests and launcher behavior.
6. Reconcile the H4-derived coverage matrix against actual source.
7. Run baseline Pester and Python suites.
8. Record design decisions and remaining uncertainties.

**Exit gate:** Verified baseline, preserved local changes, confirmed feature inventory and isolated worktree.

### Phase 1 — Convert vm_lab into an installable Python package

**Objective:** Make `modules/vm_lab` a real Python distribution.

Tasks:

1. Create Python package metadata and entry points.
2. Implement `__init__.py`, `__main__.py` and minimal CLI entry point.
3. Add package-data handling for PowerShell scripts, templates and workflows.
4. Implement reliable backend resource resolution.
5. Validate editable and wheel installation.
6. Verify both `vm` and `vm-lab` commands are generated.
7. Test imports, version reporting, help and unsupported-platform behavior.
8. Preserve the original PowerShell entry point.

**Exit gate:** Both commands install from package metadata without module-specific launcher registration.

### Phase 2 — Bootstrap migration and CLI compatibility

**Objective:** Fully integrate the Python package with the scripts toolkit.

Tasks:

1. Implement argparse command groups and subcommands for existing operations.
2. Add the typed PowerShell subprocess adapter.
3. Preserve legacy `-o` invocation compatibility.
4. Ensure output, errors and exit codes are propagated correctly.
5. Remove obsolete vm_lab-specific launcher-generator exceptions after proving normal entry-point discovery.
6. Reconcile the previously created `vm.cmd` and `vm-lab.cmd` wrappers.
7. Preserve unmanaged user wrappers.
8. Ensure missing-only bootstrap and full setup both discover the package.
9. Verify script_logging and scripts_help integration.
10. Test PowerShell command precedence and PATH lookup for `vm`.

**Exit gate:** Fresh bootstrap installs and resolves both commands. All existing operations are callable through Python subcommands.

**Milestone M1:** Python module and CLI migration complete.

### Phase 3 — Host VM creation, identity, media and boot features

**Objective:** Eliminate custom host-side PowerShell for VM provisioning and boot troubleshooting.

Implement H01, H02 and H03.

Add:

- VM-ID targeting.
- Strong host/VM preflight.
- ISO SHA-256 verification.
- Media management.
- Firmware and boot diagnostics.
- Guided boot recovery.
- Reliable state reporting.

Test the historical incompatible `New-VM` parameter case to prevent regression.

**Exit gate:** All observed H4 host provisioning and boot-management actions have a CLI equivalent or a documented interaction boundary.

### Phase 4 — Guest setup, identity, execution and lifecycle

**Objective:** Eliminate repetitive PowerShell Direct scripts for generic guest administration.

Implement H05–H10.

Add:

- Guest identity and inventory CLI.
- Trusted script execution.
- Installer/reboot semantics.
- Improved guest readiness and timeout handling.
- Guest reboot operation.
- Checkpoint ID inspection.
- Reusable setup profiles and receipts.

Keep H4-specific installation and acceptance scripts external.

**Exit gate:** A CLI-driven workflow can transfer pinned dependencies, prepare the guest, execute verified programs, inspect its state and create a clean checkpoint.

### Phase 5 — Workflow semantics, acceptance and evidence

**Objective:** Make declarative workflows capable of replacing H4's generic orchestration.

Implement H11–H14 except Windows Setup specifics.

Resolve accepted-but-unused schema fields.

Implement conditional failure handling and safe cleanup semantics.

Ensure `vm.connect` either executes correctly or is removed from the supported workflow operation set.

Implement guest identity-policy application, stage timeouts, meaningful idempotency handling, generic result assertions and evidence summaries.

Expose approved-plan management through Python subcommands.

**Exit gate:** A synthetic H4-like workflow can execute, pause, resume, encounter a failed acceptance stage, invoke appropriately authorized cleanup, recover evidence and report a correct final result without custom host orchestration PowerShell.

**Milestone M2:** Generic H4 orchestration coverage complete.

### Phase 6 — Windows installation and OOBE completion

**Objective:** Make Windows installation reproducible and minimize manual intervention.

Implement H04 and integrate with H03.

Add:

- Answer-file media preparation and attachment.
- Windows Setup media validation.
- Boot and installation-state diagnostics.
- Secure local-account setup handoff.
- Explicit interaction states.
- Guest readiness after OOBE.
- Failure recovery without discarding VM evidence.

Do not rely on undocumented Windows Setup bypasses as the default installation method.

**Exit gate:** On a separately authorized disposable VM, Windows installation can be reliably driven to a known guest-ready state through the CLI and documented interactive steps.

### Phase 7 — Full validation, documentation and integration

**Objective:** Prove the new Python package and CLI are production-quality for disposable VM work.

Complete:

1. Full Python unit tests.
2. Full existing Pester suite.
3. Launcher and bootstrap integration tests.
4. Clean editable-install test.
5. Clean wheel-install test.
6. Windows PowerShell and CMD invocation tests.
7. CLI help, short/long flags and JSON tests.
8. Security and authorization negative tests.
9. Workflow crash/recovery tests.
10. H4-derived coverage-matrix verification.
11. Source documentation and CLI command reference.
12. Integration branch and final diff review.

Prepare a separately authorized live Hyper-V acceptance run covering provisioning, installation, PowerShell Direct, artifacts, checkpointing, acceptance and evidence.

The source may be ready to merge before live acceptance, but must remain explicitly marked as not operationally qualified until the real-VM tests pass.

**Milestone M3:** Integrated and operationally qualified.

## 7. Testing strategy

### Packaging

Test that `pyproject.toml` produces a valid editable install and wheel.

Verify the wheel includes all required PowerShell backend resources.

Verify `vm` and `vm-lab` resolve to the same Python entry point.

### Bootstrap

Exercise both bootstrap and standard setup in controlled environments.

Verify no special-case vm_lab registration is necessary.

Preserve unrelated commands and launchers.

### CLI

Test argument parsing, aliases, nested help, JSON, error exits and unsupported options.

Verify commands with paths containing spaces and Unicode.

Test PowerShell alias/cmdlet collisions and command lookup.

### Backend

Keep existing Pester tests and add tests for every new backend operation.

Mock only Hyper-V, PowerShell Direct and other external system boundaries.

### Security

Cover exact VM ID enforcement, protection of unmanaged VMs, approval integrity, dry-run safety, path traversal, reparse points, stale receipts, failed transfer recovery and interrupted operations.

### Live qualification

Use an explicitly authorized new disposable Windows 11 VM.

Retain evidence for every stage.

Do not modify or adopt the existing Resource Coordinator H4 VM.

## 8. Git and execution policy

Implementation agents must work in isolated branches/worktrees.

Before creating a branch, inspect current worktree ownership, active agents, dirty files and validated checkpoints.

Preserve the three previously reported uncommitted integration fixes on main.

Stage implementation in reviewable commits.

Update a durable project STATUS document after every validated phase.

Push feature branches when permitted.

Do not merge into main without user authorization.

Do not delete VM disks, checkpoints, branches or evidence as incidental cleanup.

Do not run local LLM inference.

Real Hyper-V mutations require a separate explicit authorization boundary.

## 9. Explicit non-goals

- Rewriting the Hyper-V backend in Python.
- Embedding Resource Coordinator-specific business logic in vm_lab.
- Automatic deletion of VMs/VHDXs.
- Automatic checkpoint rollback.
- Production VM management.
- Unrestricted administrative PowerShell execution.
- Bypassing Windows guest security or UAC.
- A permanent privileged service.
- A mandatory web UI or TUI.
- Expanding into remote Hyper-V fleet management.
- Changing working public APIs solely to improve naming consistency.

## 10. Final deliverables

The implementation agent must provide:

- Installable Python `vm_lab` distribution.
- Working `vm` and `vm-lab` console entry points.
- Full command-line help.
- Compatibility with existing PowerShell APIs.
- Normal bootstrap integration.
- Expanded VM and guest command groups.
- Completed H4-derived generic workflow coverage.
- Documented examples.
- Full test suites and reproducible validation evidence.
- Clean, reviewable source branch.
- Updated coverage matrix and project status.
- Separately gated real Hyper-V acceptance procedure.

## 11. Completion definition

This project is complete when a user can invoke `vm` or `vm-lab` to create a disposable Windows VM, diagnose its installation, configure the guest, deploy verified dependencies, execute project-specific acceptance programs, manage checkpoints, recover interrupted workflows and inspect evidence—without composing custom host-side PowerShell orchestration.

The remaining manual steps should be limited to genuine Windows Setup interaction, credential entry, and explicit authorization boundaries, not missing CLI capabilities.

