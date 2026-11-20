# PrivExec Gates 1–2 Acceptance Evidence

- **Acceptance Decision:** **Gate 1 PASSED / Gate 2 PASSED** (synthetic cross-account validation only; permanent production agent identity binding and Gates 3–4 remain pending)
- **Passing Run ID:** `20261119-193433-fb3d1c6e`
- **Window (UTC):** `2026-11-19T19:34:33.5153749Z` to `2026-11-19T19:34:44.5359051Z`
- **Source Commit Tested:** `288ee8a3` (`feat/privexec-session-broker-20261119`)
- **Archived Raw Evidence Path (ACL-protected):** `C:\ProgramData\PrivExec\state\gate1-2-evidence-20261119-193433-fb3d1c6e.json`
- **Original Evidence SHA-256:** `eb582ea927ca73826f502f7cde51a03166b40a45f69795aa234f118a7f16c73b`

## Summary of Passing Checks (`20261119-193433-fb3d1c6e`)

- **Gate 1 (`Install-PrivExec.ps1 -Apply -Mode CrossAccountIsolated`):**
  - `exit_code: 0`, `ok: true`, `verified: true`, `stage: "completed"`
  - `creates_service: false`, `creates_task: false`, `modifies_accounts: false`
  - Staged H4 script digests verified:
    - `Invoke-H4GuestQualification.ps1`: `b636da4e69918d6620de9768806819f94bf822da06e2f341b62f6a6e292a5481`
    - `Invoke-H4GuestRecovery.ps1`: `ed2aae967bc72df5176daec1efcce2362ea1eaae27fb9ccd7809597f633e8b54`
    - `Bootstrap-H4GuestBundle.ps1`: `57b95576444971b5e39972e33b329e94d3b9f1a06728e196749184619ca718f0`
  - `acl_state`: `NT AUTHORITY\SYSTEM:(OI)(CI)(F)`, `BUILTIN\Administrators:(OI)(CI)(F)`, `XERES\mcarls:(OI)(CI)(F)` (zero agent access)
  - `acl_descriptors`: `SYSTEM`, `Administrators`, `XERES\mcarls`, and `XERES\PrivExecAg_bd371e:(OI)(CI)(RX)` only
- **Gate 2 Authorized Agent (`XERES\PrivExecAg_bd371e`, temporary standard user):** 11/11 checks passed:
  1. `isolated_temp_environment` (`C:\ProgramData\PrivExec-Gate2Run\20261119-193433-fb3d1c6e\agent_temp`)
  2. `status` (`session_id: 9f2ca33e386c456893bb4ec907e7852a`)
  3. `synthetic_read_only` (`op-daef5d7b6da4452e`, `synthetic.echo` `dry_run`)
  4. `synthetic_mutate_dry_run` (`op-94482cc8f96646c4`, `synthetic.mutate` `dry_run`)
  5. `synthetic_mutate_apply` (`op-505c36cd7a454f2b`, `synthetic.mutate` `apply`)
  6. `synthetic_mutate_apply_and_result` (`op-505c36cd7a454f2b` retrieved from SQLite ledger)
  7. `idempotency_mismatch_denied`
  8. `forgery_denied`
  9. `agent_shutdown_denied`
  10. `wrong_target_denied`
  11. `filesystem_write_and_state_denied` (4 protected targets verified write-denied)
- **Gate 2 Unauthorized Account (`XERES\PrivExecUn_be893f`, temporary standard user):**
  - `passed: true`, `connection_outcome: "pipe_access_denied"`, `observed: "pipe_access_denied"` (rejected at OS named-pipe DACL boundary)
- **Gate 2 Session Expiration (`ExpiredGrantCheck`, `XERES\PrivExecAg_bd371e`):**
  - `passed: true`, `state: "denied"`, `diagnostic_category: "session_expired"`
- **Cleanup & Isolation:**
  - `accounts_removed`: `["PrivExecAg_bd371e", "PrivExecUn_be893f"]`
  - `temp_dir_removed: true`, `temp_agent_acl_cleaned: true`, `errors: []`
  - `services_or_tasks: 0`, `h4_executed: false`
  - Post-run observation: `C:\ProgramData\PrivExec` root had the temporary SID removed, while `bin`/`descriptors`/`adapters`/`client`/`h4_scripts` retained the deleted SID `S-1-5-21-...-1019` with `(RX)` (purged automatically on the next `Install-PrivExec.ps1` run).

## Historical Diagnostic Runs Preserved

| Run ID | Failing Step | Root Cause Identified & Fixed |
|---|---|---|
| Prior unnumbered run | `gate2_agent` | Child process inherited operator `%TEMP%`; fixed via per-run isolated temp dirs and pipe error logging (`344bd9e2`). |
| `20261119-155802-1d596a9a` | `prepare_accounts` | Temporary user description (65 chars) exceeded Windows 48-char `New-LocalUser -Description` limit (`96c85d1d`). |
| `20261119-161632-11cc62d5` | `gate2_agent` | Async ThreadPool continuation carried client impersonation across `await` on `WriteSanitizedEvidence` (`84a1118a`). |
| `20261119-184515-5819f80d` | `gate1_install` | In-process `Install-PrivExec.ps1` left `$LASTEXITCODE` as `$null` (`$null -ne 0` true); fixed exit code, `FileSystemAclExtensions` DACL-only updates, and child-process diagnostics (`0170deae`). |
| `20261119-190051-5e0fceb1` | `gate2_agent` | `SqliteOperationStore.ReadRecord` swapped `RequestId` and `ClientSid` constructor arguments (`009d5959`). |
| `20261119-191942-ea536bb8` | `gate2_unauthorized` | `UnauthorizedAccount` could not read `C:\ProgramData\PrivExec\client\Test-PrivExecCrossAccount.ps1` (exit 64); staged isolated client copy and added `gate2_expiry_check` (`288ee8a3`). |
