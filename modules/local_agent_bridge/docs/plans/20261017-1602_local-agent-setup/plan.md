# Local agent setup implementation plan

Goal: implement the approved [design](design.md) in the existing module with a
`local_agent` subcommand CLI and an independent, reversible profile installer.

Execution: native in this feature checkout; no model/subagent delegation. User
approved implementation and copying the complete dotfiles LLM folder. Original
dotfiles files remain for manual retirement. No commit/push permission is inferred
from the earlier completed publication request.

## Tasks

- [x] 1. Add focused installer/CLI failure tests; package the bridge assets and a
  hash-verified copy of `dotfiles/symlinked/llms`. Keep the module/package name;
  add `local_agent` and release 2.0.0 for regenerated repository wrappers.
- [x] 2. Implement typed discovery and plan summaries: client paths, profiles,
  instruction blocks/adoption, skills, OpenCode roles and owned MCP/settings keys.
  Saved plans expose hashes and operations, not full config contents. Use tomlkit
  for TOML preservation and reject unsupported JSONC/ambiguous config sources.
- [x] 3. Implement preflight, install locking, ownership receipts, private backups,
  journaled application, drift checks, recovery and owned-contribution removal.
  Validate with temporary homes: repeat apply, symlink targets, unrelated edits,
  explicit adoption, stale plans, interrupted/failed writes, copies and links.
- [x] 4. Implement the CLI tree and legacy runtime seam; preserve existing model
  behavior and share preserving config writes. Keep setup independent of runtime
  services. Run checks report missing installation rather than adopting globals.
- [x] 5. Build a wheel and verify packaged resources and entry points in isolation;
  update help registry, README, migration notes and handoffs. Prepare an actual-home
  read-only plan. Report live discovery/inference separately from installer checks.

Focused verification: `.venv/Scripts/python.exe -m pytest
modules/local_agent_bridge/tests -q --basetemp
modules/local_agent_bridge/.pytest_tmp_root/setup`; CLI help and isolated
plan/apply/status/remove; wheel metadata/assets; scoped diff checks.

## Implementation rulings

- Source copy and destination migration are separate operations. Copy all authored
  files now without deleting original sources or changing dotfiles installers.
  Ship module-owned replacement hooks for later adoption; unsupported clients
  retain their existing working links until adapters are verified.
- Do not split the entire legacy runtime merely for file size. Add an argv seam
  and replace its shared config writers; keep unrelated runtime logic stable.
- No real-profile application or model calls are needed to prove the installer.
  A read-only real-home plan makes the remaining migration concrete.

Stage 1 completed. Real activation and dotfiles hook wiring remain the next stage.
Generic/local mode separation and named insertion were added at the user's request.
