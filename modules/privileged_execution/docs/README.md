# PrivExec Module (`modules/privileged_execution`)

Privileged execution session broker (`PrivExecBroker`, C# / .NET 10) and non-elevated client CLI (`privexec`, Python) for narrowly authorized Windows administrative operations, with initial integration for Resource Coordinator H4 qualification.

## Architecture

- **Agent CLI (`privexec`)**: Python package under `privexec/` providing `status`, `run`, `result`, and operator-only `broker start` / `broker stop`. Has zero privilege authority.
- **Session Broker (`broker/PrivExecBroker`)**: C# / .NET 10 process started by the operator. Listens on a local Windows named pipe, verifies client Windows SID server-side, checks operator-approved in-memory grants (capability, exact target, mode, expiry), verifies capability descriptor & script SHA-256 digests + reparse-point safety, executes fixed scripts without a shell, persists operation state/idempotency/results in SQLite (`winsqlite3.dll`), and sanitizes output.
- **Capability Descriptors & Staged Adapters**: Protected JSON descriptors and PowerShell/Python adapters installed outside agent-writable directories via `scripts/Install-PrivExec.ps1` (dry-run by default).

## Security Notice

- **Same-user UAC mode** (elevated and non-elevated processes under the same Windows user account) provides only **accidental-misuse containment**, not malicious-agent isolation.
- **Cross-account isolation** requires separate operator and agent Windows accounts, explicit pipe ACLs, and protected filesystem ACLs verified on Windows with real identities.

## Doc Map

- [docs/AGENT_INTEGRATION.md](AGENT_INTEGRATION.md) — Normal-agent invocation, ACLs, and broker session lifecycle
- [docs/HANDOFF.md](HANDOFF.md) — Current module state and next action
- [docs/plans/HANDOFF.md](plans/HANDOFF.md) — Plan index
- [00_implementation-plan.md](plans/20261119-privexec-session-broker/00_implementation-plan.md) — Master implementation plan
- [01_interface-contract-and-architecture.md](plans/20261119-privexec-session-broker/01_interface-contract-and-architecture.md) — Phase 0 contract & architecture
- [STATUS.md](plans/20261119-privexec-session-broker/STATUS.md) — Execution & verification ledger
- [checklist.md](plans/20261119-privexec-session-broker/checklist.md) — Phase & acceptance checklist
