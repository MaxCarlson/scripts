# Dotfiles ownership migration

The original `dotfiles/symlinked/llms` folder was copied into the package under
`resources/dotfiles_llms`. The copy has a source/destination SHA256 manifest. One
credential-shaped value in `claude/settings.json` was replaced with
`REDACTED_LOCAL_CREDENTIAL`. It must not be used as a live credential/config value.
Original source files are still present and unchanged.

The installer uses a separate generic instruction source plus optional local
fragments. Archived Codex settings and Gemini settings supply only missing defaults;
existing values are preserved. Archived custom skills are installed for both clients.
Other archived agents, prompts, instructions, wrappers and Claude settings are
retained for later client-specific migration; they are not all automatically
executed or installed into unrelated clients.

## Existing machine

Codex's global `AGENTS.md` currently points into dotfiles. agy's global `GEMINI.md`
is a regular file with different/newer rules. The default plan patches only the
local instruction block; it does not claim those entire files. To transfer full
instruction ownership, explicitly adopt those resources. The active content becomes
the baseline; setup does not replace it with an older template.

The inspected machine also has `test-verify` in Codex's legacy skill directory.
Without adoption the plan reports the duplicate and apply performs no installation.
Explicit adoption updates the existing location in place and preserves a backup;
it does not create another discovery entry.

Review a concrete adoption plan:

```powershell
local_agent setup plan -c codex agy -s auto -m local -A codex.instructions agy.instructions codex.custom-skill.test-verify -o migration-plan.json
local_agent setup apply -i migration-plan.json
```

The same IDs are valid for generic mode. These commands are examples of the
reviewed transfer; the real apply has not been run. Paths and fingerprints are
rechecked before writes, including the source of the Codex link. File linking on
Windows may fall back to copies in auto mode; explicit link mode fails visibly.
Backups retain the original link/file for removal. If the old dotfiles target is
later deleted, restoring that old link would make it broken; retain the old sources
or reconcile that rollback target before requesting removal.

## Dotfiles bootstrap

Module-owned replacement hooks are `integrations/setup-agents.ps1` and
`integrations/setup-agents.sh`. They default to generic mode and invoke the new
installer, returning failures. The PowerShell hook supports `-WhatIf` for planning.
These hooks have not been connected to dotfiles setup; no dotfiles installer was
changed. Replace its duplicate destination writers only after the supported
clients' real migration is verified. Existing Claude/Cursor wiring still needs
coverage before the entire old source tree can be retired.

The older agent_abilities/agent_skills managers are not invoked or reconfigured.
Their source assumptions may still refer to dotfiles. Avoid running their old
sync operations against the same adopted resources until their ownership has been
reconciled. This setup detects overlapping discovery entries rather than pruning
another manager's data.

## Isolated validation

Use `-H/--home` and optionally `-S/--state-dir`. All default client/state paths
then derive from that target home, without inheriting the real user's config-path
overrides. Client config roots must be unambiguous; OpenCode JSONC/custom override
layouts currently require reconciliation. JSON settings must be strict JSON;
TOML updates use tomlkit to preserve comments and unrelated fields.
