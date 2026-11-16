# Phase 5 — Windows Installation Assistance, OOBE Handoff, and Prepared Guest Reuse

**Depends on:** Phase 0 and baseline workflow interface; integrates best after Phase 3.  
**Execution constraint:** no new real VM boot/ISO mutation without separately authorized disposable test target.  
**Non-goal:** bypass Windows licensing/activation or silently store local Administrator passwords.

## Objective

Reduce the manual work encountered during H4: initial ISO selection, the `SCSI DVD boot loader failed` / missed "Press any key" prompt, Windows 11 disconnected-network OOBE, first local-account setup, ambiguity about whether Windows is installed, and separate restart/PowerShell Direct readiness commands.

## 1. Installation state model

Define precise, confidence-aware states:

- `vm_missing`, `vm_off`, `boot_configuration_invalid`, `dvd_attached`, `vm_started`.
- `windows_setup_unobserved`, `windows_setup_possible`, `awaiting_console_input`, `oobe_pending` (only if supported evidence exists), `guest_account_unavailable`.
- `guest_heartbeat_seen`, `ps_direct_credentials_needed`, `ps_direct_authenticated`, `guest_os_verified`, `prerequisites_ready`.
- `installation_blocked`, `reboot_required`, `manual_step_required`.

Use actual Hyper-V VM, firmware/DVD, integration service and authenticated guest signals. **Never assert "Windows installation has not started" merely because VHDX is small or timestamp unchanged.** Account prompts and OOBE progress may be opaque without GUI; report uncertainty and offer VMConnect, not false facts.

## 2. ISO and firmware verification

Validate local ISO size, readability, trusted expected digest (if supplied), compatible architecture, selected Windows edition and build where inspectable. Verify Gen2, DVD attachment, boot order, Secure Boot MicrosoftWindows and vTPM. Connect via VMConnect in interactive session; non-interactive agent receives an actionable blocker. Do not change firmware or disable Secure Boot as speculative boot fix.

Offer controlled "retry DVD boot" guidance with **explicit** user restart/start capability, not automatic forced reset of an active Setup guest. Show the short DVD keyboard prompt requirement. Record source ISO digest and target VM ID.

## 3. Supported answer-file media delivery

Current vm_lab only generates `Autounattend.xml`. Extend to safe *delivery*:

1. Generate supported answer-file fields (locale, keyboard, edition, approved disk targeting only for new empty owned VHDX).
2. Validate XML schema with documented Windows SIM tooling when available; fail with explicit limitation if not.
3. Prepare a separate read-only answer-file ISO or supported removable medium with `Autounattend.xml` at the root, using a verified toolchain. Avoid modifying original Windows ISO.
4. Attach to an approved additional DVD device, verify discovery path/firmware order and source hashes.
5. Observe Windows Setup/OOBE handoff and later guest readiness; do not declare answer-file application merely because media attached.
6. Remove/reattach media only with explicit configuration mutation authorization; preserve original ISO and any logs.

Source: Microsoft [Automate Windows Setup](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/automate-windows-setup) and [Automation Overview](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/windows-setup-automation-overview). The `/unattend` CLI switch is not a universal fallback for installed Windows; see Microsoft Setup command-line limitations.

## 4. Local account and offline OOBE

For a disconnected guest, prefer a documented setup answer-file policy and explicit interactive account-creation fallback. Do not rely on unverified build-specific OOBE shortcuts (`BypassNRO`, `ms-cxh:localonly`). Do not add auto-login, password-in-XML or plaintext installer scripts to a standard template.

The user may need to create a dedicated guest-local administrator manually. After that, PowerShell Direct can authenticate using its credentials without a network. The workflow must stop at `AWAITING_INTERACTION` with the specific next action and then resume the same operation; do not re-create VM or rerun setup.

## 5. Guest readiness and idempotent continuation

After interactive OOBE, poll for VM Running, heartbeat and a valid guest account. Prompt for guest credentials only in an interactive authorized operator session. Verify OS build, architecture, hostname, virtualization, expected local-admin token and optionally clean-inventory guard. Continue with Phase 1 artifact staging and Phase 3 setup receipts. Wrong password must not become "OS not installed"; transport disconnect must not trigger an extra VM reset.

## 6. Optional prepared guest image workflow

If repeated full Windows installation becomes dominant, implement **optional** generalized reusable image packaging:

- Start from a separate disposable reference guest, never H4's active acceptance VM.
- Document `Sysprep /generalize /oobe /shutdown` (and `/mode:vm` where applicable), app provisioning caveats, activation/licensing and VM generation/hardware compatibility.
- Prepare read-only parent VHDX and derived test disks where supported, with documented parent-chain ownership and rollback constraints; no silent source disk mutation.
- Verify cloned images obtain unique guest identity after OOBE; do not carry local passwords, test receipts, RC artifacts or secrets into templates.
- Preserve published generalized image hash/source/OS patch level and expiration; do not claim perfect reuse across different Windows builds.

Image reuse should be deferred if it introduces excessive complexity or unsupported Windows licensing assumptions. Core success does **not** depend on this feature.

## 7. Tests and negative paths

- Gen2/ISO/boot-order mismatch caught before start; non-interactive VMConnect reports blocker.
- Current Windows OOBE behavior simulated; no hardcoded UI bypass dependency.
- Answer-file XML is structurally valid and accepted by available documented validator; invalid locale/edition/disk fields rejected.
- No existing VHDX can be selected for destructive Setup disk partitioning through this feature.
- Media build failures preserve originals; no silently attached credentials.
- Missing guest user produces interaction-needed; heartbeat without credentials not counted as ready.
- Wrong credentials, disabled PS Direct service, stalled OOBE, guest reboot and remote session loss classified correctly.
- Prepared image must fail if not generalized, missing trust metadata or referencing original H4 VHDX.
- Resume after OOBE cannot re-provision an existing VM.
- Functional test against new disposable Windows guest reserved for Phase 6, not active H4.

## Deliverables

- Installation-oriented workflow operation(s), setup/boot diagnostics and `-WhatIf` plan.
- Answer-file media preparation and integrity validation (or explicit justified deferral with implementation-ready tested design).
- Reliable user handoff to VMConnect/OOBE and continuing PowerShell Direct after guest account creation.
- Optional generalized image proof-of-concept only if security and supported behavior are validated.
- Tests, docs, status updates and new operations integrated into toolkit launcher.

## Acceptance gate

- [ ] On a **fresh authorized** VM, installation steps are observable or marked uncertain, not guessed from VHD size.
- [ ] The user can move through unavoidable OOBE, return to agent, and resume *same operation ID* automatically.
- [ ] Local account/password handling has no plaintext persistence.
- [ ] Answer-file delivery is real (not merely XML generation), with independently verified setup behavior when live tested.
- [ ] H4-like offline VM remains disconnected without need for guest networking.
- [ ] No existing VM disk can be overwritten by optional automated Setup.
