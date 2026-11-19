# Status — `20261119-privexec-session-broker`

- **Current Phase:** **Gates 1–2 PASSED** (`run_id: 20261119-193433-fb3d1c6e`, commit `288ee8a3`); security review & Gate 3 read-only H4 preflight proposal complete; awaiting operator authorization for production identity binding and Gate 3 (`h4.preflight`).
- **Branch:** `feat/privexec-session-broker-20261119`
- **Worktree:** `C:\Users\mcarls\src\scripts-privexec`
- **Base Commit:** `e7b9f36d5296d8b8fe301ef47e9f35adc64f886b`

## Acceptance Summary
- **Gate 1 (Elevated Installation & ACL Isolation):** **PASSED** (`20261119-193433-fb3d1c6e`).
- **Gate 2 (Real Windows Cross-Account Isolation):** **PASSED** (`20261119-193433-fb3d1c6e`, 11/11 authorized-agent checks, `pipe_access_denied` for `PrivExecUn_be893f`, `session_expired` after 2s TTL, clean temp account/dir removal, 0 services/tasks, `h4_executed: false`).
- **Evidence Snapshot:** [gate1-2-acceptance-evidence.md](gate1-2-acceptance-evidence.md) (SHA-256 `eb582ea927ca73826f502f7cde51a03166b40a45f69795aa234f118a7f16c73b`; archived raw JSON at `C:\ProgramData\PrivExec\state\gate1-2-evidence-20261119-193433-fb3d1c6e.json`).
- **Distinction from Production Deployment:** Gates 1–2 used temporary test accounts that were deleted after testing. PrivExec is **not yet bound to a permanent coding-agent identity** and **not yet validated against live H4** (Gates 3–4).

## Key Defects Resolved During Gate 1–2 Validation
1. Cross-account `TEMP`/`USERPROFILE` inheritance & pipe error observability (`344bd9e2`).
2. Windows `New-LocalUser -Description` 48-char limit (`96c85d1d`).
3. Async ThreadPool `WindowsIdentity` impersonation leak across `await` + stale-SID ACL reconciliation (`84a1118a`).
4. In-process `Install-PrivExec.ps1` `$LASTEXITCODE` `$null` false-failure + `FileSystemAclExtensions` DACL-only updates (`0170deae`).
5. `SqliteOperationStore.ReadRecord` `RequestId`/`ClientSid` positional parameter swap (`009d5959`).
6. Isolated `UnauthorizedAccount` client staging + strict pipe boundary check + `gate2_expiry_check` (`288ee8a3`).

## Residual Risks & Limitations Documented
- Subdirectories under `C:\ProgramData\PrivExec` (`bin`, `descriptors`, `adapters`, `client`, `h4_scripts`) retained the deleted temporary SID `S-1-5-21-...-1019` `(RX)` after root cleanup; `Install-PrivExec.ps1` (`Set-StrictDirectoryAcl`) purges it on the next install/rebind.
- `SessionGrant` enforces a single session-level `ExpiresAtUtc` (`session_expired`), not independent per-capability TTLs.
- `executable_sha256` for `pwsh.exe` is `null` in descriptors (relying on `Program Files` ACLs and reparse-point checks).
- `Invoke-H4GuestQualification.ps1 -Stage Preflight` verifies `Get-VM` but not `Get-VMSnapshot`; the Gate 3 proposal includes a manual read-only `Get-VMSnapshot` pre-check.

## Next Actionable Step
- Operator reviews [gate3-read-only-proposal.md](gate3-read-only-proposal.md) and decides whether to authorize permanent agent identity binding and Gate 3 (`h4.preflight`).
