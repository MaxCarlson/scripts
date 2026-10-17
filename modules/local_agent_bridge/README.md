# Local agent setup and bridge

`local_agent` installs Codex/Antigravity (`agy`) profiles and runs the LM Studio /
OpenCode bridge. It is independent of `agent_abilities` and `agent_skills`.

## Setup

```powershell
local_agent setup plan -c codex agy -s auto -m generic
local_agent setup apply -c codex agy -s auto -m generic
local_agent setup plan -c codex agy -s auto -m local
local_agent setup apply -c codex agy -s auto -m local
local_agent setup status
```

`plan` previews changes without installing anything. `apply` writes them. `generic`
installs generic instructions, applicable settings defaults and copied custom
skills. `local` adds the delegation skill/snippet, worker roles, MCP connections and
agy's bridge permission. Existing settings take precedence over template defaults.
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
local_agent setup plan -o agent-plan.json
local_agent setup apply -i agent-plan.json
local_agent setup remove                 # preview
local_agent setup remove -a              # restore owned contributions
local_agent setup recover               # inspect/recover an interrupted apply
```

Saved plans contain fingerprints and operation metadata, not complete config text.
Stale plans fail before application. A receipt, private backups and a recovery
journal live under `~/.local/share/local-agent/`. Remove refuses changed resources
and preserves unrelated config keys. Do not delete that state before removal.

## Models and bridge

```powershell
local_agent model list
local_agent model rename old-alias new-alias -a
local_agent model remove old-alias -a
local_agent run -M qwen38_23GB
local_agent run -m qwen/qwen3.8-27b@q6_k -c 32768
```

`rename` and `remove` preview unless `-a/--apply` is supplied. Remove unregisters
and unloads an alias; it does not delete downloaded weights. `run` retains the
existing configure/load/foreground-server workflow and options. Runtime config
writers preserve comments, unrelated fields, extra bridge options and file links.
Setup never starts servers, calls models or installs external runtime tools.

The legacy `local-agent-bridge` command and `python -m local_agent_bridge` retain
the original interface. The package and folder are still `local_agent_bridge`.
Version 2.0.0 adds the `local_agent` entry point; repository setup must regenerate
wrappers. For direct module execution use `python -m local_agent_bridge.commands`.

## Resources and status

- [Shared skill](local_agent_bridge/resources/skills/local-agent-handoff/SKILL.md)
- [Canonical worker prompt](local_agent_bridge/resources/skills/local-agent-handoff/resources/local-worker.md)
- [Integration details](docs/INTEGRATION.md), [settings](docs/SETTINGS.md), [research](docs/RESEARCH.md)
- [Validation](docs/VALIDATION.md) and [current handoff](docs/HANDOFF.md)
- [Design](docs/plans/20261017-1602_local-agent-setup/design.md) and [implementation plan](docs/plans/20261017-1602_local-agent-setup/plan.md)

All 26 original dotfiles LLM assets were copied under
`local_agent_bridge/resources/dotfiles_llms/`; one credential-shaped value in
Claude settings was redacted. Hashes and the exception are recorded in
[the migration manifest](local_agent_bridge/resources/migration.json).
Original dotfiles files and real profiles have not been changed by this work.
Claude/Cursor and non-skill custom resources are retained as migration material;
installation adapters currently target Codex and agy only. Do not retire their
existing wiring until replacement adapters are ready.
