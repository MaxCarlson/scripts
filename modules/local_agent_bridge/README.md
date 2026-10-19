# Local agent setup and bridge

`local-agent` installs Codex/Antigravity (`agy`) profiles and runs the LM Studio /
OpenCode bridge. It is independent of `agent_abilities` and `agent_skills`.

## Setup

```powershell
local-agent setup plan -c codex agy -s auto -m generic
local-agent setup apply -c codex agy -s auto -m generic
local-agent setup plan -c codex agy -s auto -m local
local-agent setup apply -c codex agy -s auto -m local
local-agent setup status
```

`plan` previews changes without installing anything. `apply` writes them. `generic`
installs generic instructions, applicable settings defaults and copied custom
skills. `local` adds the delegation skill/snippet, worker roles, MCP connections and
agy's bridge permission. Existing settings take precedence over template defaults.
Later user edits to seeded defaults are preserved and released from installer
ownership. Known legacy settings misplaced under Codex `[history]` are moved to
the root while preserving explicit root values; uninstall restores their baseline.
Switch modes with another apply; only owned contributions are removed or updated.
Known pre-existing module bridge entries are disabled in generic mode rather than
deleting an independent original connection.

Generic instructions are authored in
[resources/profiles/AGENTS.md](local_agent_bridge/resources/profiles/AGENTS.md).
Local delegation stays in the separate
[coordinator fragment](local_agent_bridge/resources/instructions/coordinator.snippet.md).
Named insertion anchors control placement; see [composition](docs/COMPOSITION.md).
The copied original dotfiles templates remain available for comparison.

`auto` chooses directory links/junctions where possible and copies when linking
is unavailable. It records the actual method and reuses it on later applies.
`link` requires linking to succeed; `copy` always copies. Updating authored sources
requires another apply for copied/rendered resources. Linked skill changes appear
immediately; apply acknowledges the updated canonical source. Changed link targets
and independently edited copies are reported as drift.

For existing files, setup can own just its marked instruction block/config fields.
Whole instruction ownership or existing skill replacement requires exact adoption
IDs shown by the plan. Unrelated edits are preserved. Review the migration guide
before adopting your current global files:
[dotfiles migration](docs/MIGRATION.md).

```powershell
local-agent setup plan -o agent-plan.json
local-agent setup apply -i agent-plan.json
local-agent setup remove                 # preview
local-agent setup remove -a              # restore owned contributions
local-agent setup recover               # inspect/recover an interrupted apply
```

Saved plans contain fingerprints and operation metadata, not complete config text.
Stale plans fail before application. A receipt, private backups and a recovery
journal live under `~/.local/share/local-agent/`. Remove refuses changed resources
and preserves unrelated config keys. Do not delete that state before removal.

## Models and bridge

```powershell
local-agent model list
local-agent model rename old-alias new-alias -a
local-agent model remove old-alias -a
local-agent run -M qwen38_23GB
local-agent run -m qwen/qwen3.8-27b@q6_k -c 32768
```

`rename` and `remove` preview unless `-a/--apply` is supplied. Remove unregisters
and unloads an alias; it does not delete downloaded weights. `run` retains the
existing configure/load/foreground-server workflow and options. Runtime config
writers preserve comments, unrelated fields, extra bridge options and file links.
Setup never starts servers, calls models or installs external runtime tools.

Version 3.0.0 standardizes on `local-agent`, retains `local_agent` as an alias,
and removes the `local-agent-bridge` entry point. Reinstall the package and refresh
repository wrappers when upgrading; the entry point change requires a major version.
`python -m local_agent_bridge` retains the original loader interface. The package
and folder remain `local_agent_bridge`; the modern module interface is
`python -m local_agent_bridge.commands`.

## Resources and status

- [Shared skill](local_agent_bridge/resources/skills/local-agent-handoff/SKILL.md)
- [Canonical worker prompt](local_agent_bridge/resources/skills/local-agent-handoff/resources/local-worker.md)
- [Integration details](docs/INTEGRATION.md), [settings](docs/SETTINGS.md), [research](docs/RESEARCH.md)
- [Validation](docs/VALIDATION.md) and [current handoff](docs/HANDOFF.md)
- [Active plan (Argon)](docs/plans/20261017-1650_host-adoption-and-runtime-handoff/plan.md) and [plan handoff](docs/plans/20261017-1650_host-adoption-and-runtime-handoff/HANDOFF.md)
- [Installer design](docs/plans/20261017-1602_local-agent-setup/design.md) and [installer stage plan](docs/plans/20261017-1602_local-agent-setup/plan.md)

All 26 original dotfiles LLM assets were copied under
`local_agent_bridge/resources/dotfiles_llms/`; one credential-shaped value in
Claude settings was redacted. Hashes and the exception are recorded in
[the migration manifest](local_agent_bridge/resources/migration.json).
The 2026-10-17 adoption updated host profiles and dotfiles wiring. The independent
2026-10-19 audit changed repository code only; see [AUDIT.md](docs/AUDIT.md).
Claude/Cursor and non-skill custom resources are retained as migration material;
installation adapters currently target Codex and agy only. Do not retire their
existing wiring until replacement adapters are ready.

Bootstrap hooks preserve a uniform recorded client mode. Mixed modes require
explicit client selection or a mode. Both hooks honor `DOTFILES_DRY_RUN=1`;
POSIX forwarding preserves quoted paths. `run` refuses to restart an existing
unusable OpenCode server automatically; stop/restart it explicitly.
