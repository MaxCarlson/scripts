# Phase 1 — Generic Guest Execution, Verified Artifacts, and Evidence Transfer

**Depends on:** Phase 0 contracts. **May run parallel to Phase 2 in isolated worktrees with distinct source ownership.**  
**Primary ownership:** `src/Guest.ps1`, new `src/GuestExec.ps1`, `src/Artifacts.ps1`, `src/Evidence.ps1`, tests and CLI dispatch (coordinate shared dispatch changes).  
**No real H4 or host mutation.**

## Objective

Replace the repeated `Invoke-H4GuestScript`, `Copy-H4ToGuest`, `Copy-H4FromGuest` and bespoke installer/bundle transfer logic with reusable, strongly typed and verifiable vm_lab operations. Ensure an RC-like acceptance script can be executed inside a Windows guest with exact process status and independently retrievable evidence.

## 1. Guest identity and credentialed session

Create an externally callable, bounded operation that validates Hyper-V exact VM ID/ownership, running state, guest identity and approved guest-root policy. Include optional expected hostname, OS/build/arch, local Administrator token, Hyper-V virtual manufacturer/model, required integration service and project-configurable inventory conditions.

Do not infer installation from VHDX allocation. PowerShell Direct requires running Windows and an existing guest account; no network needed. Keep session cleanup (`finally`) and distinguish auth failure, transport failure, OOBE pending, host permission failure, timeout and required guest reboot. Do not persist credentials.

In tests, fake the PS Direct transport but run real validation, timeouts, state transitions and error classification. Avoid on-host execution of guest scriptblocks that could modify XERES.

## 2. Typed guest command executor

Expose a stable public function and `vm-lab` CLI operation (e.g. `guest-exec`) with:

- Exact owned VM ID/name/path, selected guest account and required capability.
- Executable path pinned to a previously verified guest artifact or explicit trusted built-in allowlist.
- Argument **array**, not command-line string interpolation.
- Guest cwd, per-key allowlisted environment assignments and no secret logging.
- Run ID, optional operation/stage ID and `read_only/replayable/non_repeatable` idempotency class.
- Bounded timeouts, stdout/stderr capture, output size cap and separate JSON result parse.
- Native exit code preservation even when PS command itself completes; report terminating PowerShell error distinctly.
- Recorded guest OS identity, script digest, execution duration, result state, host+guest evidence locations.
- An interruption-reconciliation strategy: after session loss or timeout, do **not** rerun a possibly running non-repeatable script. Prefer a bounded remote process marker/receipt and explicit `UNKNOWN/NEEDS_RECONCILIATION`.

**Security note:** a typed guest executable can still be powerful. Require explicit guest-execution approval separate from VM startup and use digest/path restrictions; no arbitrary shell from untrusted workflow definitions.

### Project acceptance emulator

Provide a *synthetic* guest test runner with profiles `offline`, `task`, `full`, `rollback` and `cleanup`, deterministic PASS/FAIL, skipped-test count, artificial delay and distinct fault stages. Test `guest-exec` against its JSON status and exit code. Do not import Resource Coordinator's business logic into vm_lab.

## 3. Batch artifact manifest and deployment

Implement trusted `artifact.deploy` with manifest `schema_version=1`:

- Each file: trusted SHA-256, length, host path, guest-relative destination and optional publisher evidence.
- Directory trees: recursive enumeration, canonical relative paths, per-file checks, no UNC/absolute path entry, no `..`, symlink or junction into another root.
- Exact guest destination root configured/authorized and not pointing to system/production paths by default.
- File-level staging (`.vm_lab_tmp.<id>`), verify digest on guest, atomic same-volume commit, no silent overwrite of unowned data.
- On resume: skip already committed files only after content hash verification; preserve any partial staged bytes for bounded retransfer or safe cleanup of *this operation's* temp files.
- Error reporting per item, bytes expected/transferred/verified, immutable manifest digest, source and guest inventory.
- Verify trusted release hash independently of transfer-computed hash. A shipped hash file with no independent trust is not publisher proof.

H4 regression fixture: Python x64 installer, PowerShell x64 MSI, multiple pinned `.whl` files + digest manifest, bundle ZIP, bootstrap script. Include paths with spaces/Unicode and cross-drive roots. Preserve offline-only policy unless expressly requested otherwise.

## 4. Safe bundle unpack and prerequisite workflows

Add a generic typed archive action or allow verified guest runner to extract an immutable ZIP to a unique operation-bound path. Before extraction: verify trusted archive hash, entry canonical paths, max files/decompressed size, no path traversal/reparse escape, and expected manifest. After extraction: verify component digests or require external project verifier. Never `Remove-Item -Recurse -Force` existing extraction roots automatically.

Reuse existing `guest-bootstrap` Python/PowerShell profiles and dependency constraints. Support a named setup recipe of multiple verified actions: install MSI/Python, handle installer exit 3010 (`REBOOT_REQUIRED`), create venv, install pinned packages offline, run explicit import/`pip check` verification, and write verified per-profile receipts. No hardcoded H4 Python path, bundle name or app dependencies in generic core.

## 5. Recursive evidence collection

Implement `evidence.collect`:

1. Accept only approved guest evidence roots/globs and an operation-owned host destination.
2. Enumerate files recursively (including nested directories), disallow symlinks/junction escapes, calculate guest file digests and lengths.
3. Copy incrementally to staged host location, verify hash and size, then atomically finalize each file.
4. Preserve guest files even on partial failure; produce detailed retry hints and missing-file manifest.
5. Persist command output, parsed result JSON, OS query output and transfers from a failed stage.
6. Distinguish `EVIDENCE_COMPLETE`, `EVIDENCE_PARTIAL`, `EVIDENCE_FAILED`; no PASS if required evidence is incomplete.

This specifically replaces H4's `Copy-Item -FromSession -Recurse` plus `matrix-summary.json` transfer bookkeeping. Host evidence structure must retain stage/attempt identity rather than flatten all runs into one directory.

## 6. CLI integration

Add operations to `Invoke-VmLab`/`Invoke-VmLab.ps1` with short/long arguments, `-Apply` and `-WhatIf`, compatible JSON stdout and structured error codes. Reuse central launcher logging; do not bypass existing `vm-lab.cmd`. No headless interactive prompting. Provide `guest-command-plan`, `guest-exec`, `artifact-plan/deploy`, `evidence-plan/collect` as candidate names; finalize exact names in Phase 0.

## 7. Test plan

**Unit/property/fault cases:**

- Incorrect VM ID, untrusted manifest, path traversal, symlink/junction, foreign destination, invalid guest account, missing PS Direct, unauthenticated guest.
- Output with valid JSON but exit nonzero; exit zero but project status FAIL; malformed JSON; missing/skipped tests; timeout/transport loss; multi-arg quoting; environment variable injection; Unicode.
- Wrong artifact hash, source changed during copy, guest hash differs, archive ZIP slip, ZIP bomb, incompatible installer, mismatched wheel manifest.
- Transfer interruption before/after guest commit, re-run avoids duplicate copies and never overwrites foreign files.
- Recursive evidence with nested directories, large file, empty directory, partially inaccessible child, changed source while copying, missing critical file.
- Dry-run does not copy files or create guest directories; `-Apply` without guest-execution capability refuses mutations.

**Mock coverage:** actual orchestration logic and local filesystem mechanics execute; Hyper-V `Get-VM`, session creation and guest I/O are boundaries. Include controlled fake guest tree where possible and isolated CLI subprocess verification. **No live H4 VM use.**

## Deliverables

- Public guest command and artifact/evidence APIs and CLI.
- Documented strict manifest schema, profile recipe contract and trust model.
- Synthetically executable RC-like guest acceptance fixture.
- Pester regression suite including failure/incomplete cases.
- Compatibility tests for existing guest-copy/bootstrap functions and launcher.
- Evidence/status schema in `ARCHITECTURE.md`, phase commit and `STATUS.md` update.

## Acceptance criteria

- [ ] A project runner can be executed using only vm_lab generic guest operations; no custom host PS Direct wrapper is required.
- [ ] Every installer/wheel/ZIP hash and destination is checked before use; transfer resumes without corrupting prior artifacts.
- [ ] Guest child process exit, JSON status, stdout/stderr and evidence are independently represented.
- [ ] Remote evidence tree retrieval is resumable and incomplete retrieval blocks final success.
- [ ] Deliberately failed guest script cannot be reported as PASS after project cleanup.
- [ ] Existing module CLI and ownership tests still pass.

**Phase exit:** validated source commit, test/evidence list and no real VM mutation. Phase 2 may proceed independently; Phase 3 depends on both.
