# Local agent CLI and setup ownership design

Date: 2026-10-17 (America/Los_Angeles). Status: approved; installer stage implemented.

## Intent and decisions

Provide one `local_agent` command for installing agent resources and operating
the existing local model bridge. Move ownership of the tracked LLM assets from
`dotfiles/symlinked/llms` into this module. A repeated setup must converge without
duplicating instructions or replacing independent user changes.

The user prefers subcommands and does not trust the unreviewed `agent_abilities`
implementation enough to merge with it. Consequently:

- Keep the existing `modules/local_agent_bridge` package boundary for this work.
- Implement a small installer in this package; do not import, depend on, merge,
  invoke or silently register resources with `agent_abilities` or `agent_skills`.
- Leave those existing modules and their user-created resources intact. Their
  source-path assumptions and overlapping destinations are migration conflicts to
  identify, not permission to rewrite their registries or prune their resources.
- Existing code is reference material only. No claim that either manager is
  generally broken or safe has been established by this investigation.
- Use native execution for planning; no subagents or model calls are needed.

## Current evidence

- The module is version 1.1.0 and exposes `local-agent-bridge`. Its existing
  `cli.py` combines argument parsing, model management, config writes and the
  foreground OpenCode server workflow.
- Codex's active `~/.codex/AGENTS.md` is a file symlink to
  `C:/Users/mcarls/src/dotfiles/symlinked/llms/codex/AGENTS.md`.
- `~/.gemini/GEMINI.md` is a regular file with newer/different instructions than
  the tracked dotfiles Gemini template. The active Codex config and Gemini settings
  are also regular files. Do not assume the intended dotfiles links exist.
- The inspected OpenCode config has provider/model settings but no named agents.
- Dotfiles has Windows and shell installers, wrappers, instruction sources,
  settings, resource templates and custom agents/prompts/instructions/skills.
  Both installers currently own some of the same destinations as the resource managers.
- `agent_abilities` hardcodes a dotfiles source path, uses older Codex skill
  destinations, lacks an agy adapter, and its copy helper removes existing
  destinations. This is insufficient evidence of safe adoption for this installer.

All profile locations must be re-inspected immediately before implementation or
apply. This is a snapshot, not an installation receipt.

## Public CLI

The executable is spelled `local_agent`, as requested. Retain
`local-agent-bridge` and `python -m local_agent_bridge` with their legacy argument
behavior. Adding the new entry point requires release **2.0.0** under the scripts
repository's wrapper/reinstall rules; synchronize package and help-registry versions.

```text
local_agent
  setup
    plan       Inspect targets and preview installation/update operations
    apply      Install/update the selected profiles and bridge integration
    status     Report managed, missing, changed and conflicting resources
    remove     Preview removal; --apply removes only unchanged owned contributions
    recover    Recover an interrupted installation without overwriting new edits
  model
    list       Existing model/variant/loaded-instance/alias inventory
    rename     Preview alias rename; --apply performs the existing rename operation
    remove     Preview unregister/unload; --apply performs it (does not delete weights)
  run          Existing configure/load/start workflow, including foreground server
```

Bare `local_agent`, `setup` or `model` prints relevant help without mutations.
Unknown commands return an argument error. There is no automatic model load,
inference, dependency installation or server restart from a setup command.

Examples (proposed interface; not implemented commands):

```powershell
local_agent setup plan -c codex agy -s auto
local_agent setup apply -c codex agy -s auto
local_agent setup status -j
local_agent setup remove -c codex agy
local_agent setup remove -c codex agy -a
local_agent model list
local_agent model rename old-alias new-alias -a
local_agent model remove old-alias -a
local_agent run -M qwen38_23GB
```

Setup options, scoped to applicable subcommands:

| Option | Meaning |
| --- | --- |
| `-c`, `--clients` | One or more explicit clients; default `codex agy` |
| `-m`, `--mode` | `generic` or `local`; local adds separate capability fragments |
| `-s`, `--strategy` | `auto`, `link` or `copy` for applicable resources |
| `-H`, `--home` | Target home root, including isolated validation profiles |
| `-S`, `--state-dir` | Receipt/backup root; default `~/.local/share/local-agent` |
| `-o`, `--output` | Save a versioned JSON plan from `setup plan` |
| `-i`, `--input-plan` | Apply a saved plan, rejecting changed input fingerprints |
| `-A`, `--adopt` | Explicit resource IDs whose existing ownership may be transferred |
| `-a`, `--apply` | Execute `setup remove` or model rename/remove; otherwise preview |
| `-j`, `--json` | Versioned machine-readable plan/status/result |

`setup apply` is already the explicit write action and needs no second `--apply`.
Input-plan selection is mutually exclusive with target/strategy/adoption changes.
Every new optional argument has short and long spellings. `run` preserves the
loader's existing option spellings and meanings; model-management options route
to the new model group rather than appearing as actions under `run`.

`setup apply` handles the selected instructions, skills, worker roles and MCP
configuration in one operation. `run` checks resource readiness and reports the
setup command when installation is missing; it does not implicitly adopt globals.
Its model/MCP config updates must share the new format-preserving writer instead
of leaving two implementations that overwrite each other's settings.

Initial client adapters are Codex and agy. Migrated Claude/Cursor/custom resource
destinations must retain their current working arrangement until equivalent
adapters are explicitly implemented and checked. Merely accepting a client name
or copying a generic resource into a directory does not establish client support.

Exit codes: 0 success/no change; 1 operational failure; 2 usage error; 3 ownership
conflict; 4 stale plan/input; 5 incomplete apply requiring reported recovery.
Status returns 3 for drift/conflicts or missing required installation resources;
it does not treat a deliberately stopped model/server as installation corruption.
With `--home`, default client paths and the default state directory derive from
that target root; isolated validation must never fall back to the real user's home.

## Ownership and instruction composition

The module owns authored instruction fragments, profile templates, resource
definitions and installation rules. Live authentication, conversation history,
model weights and client-generated state remain with their clients.

Package authored assets under `local_agent_bridge/resources/`, accessed through
`importlib.resources`. Keep profiles, custom resources, wrappers and bridge assets
in separate subdirectories. Preserve one canonical worker prompt. The existing
root skill/reference files move with their references updated; installed wheels
must contain the same assets as editable installs.

Compose global instructions from a shared base, explicit client additions, and
enabled feature fragments such as local delegation. The delegate snippet appears
exactly once in the rendered output. Removing the integration removes its
contribution while preserving the client's base instructions.

For an unmanaged installation, support a marked delegation block in an existing
global file rather than assuming ownership of the entire document. Exact existing
unmarked snippet content is recognized without appending a duplicate. Ambiguous
or edited blocks require reconciliation. Full-file composition becomes active only
after explicit adoption of that instruction resource.

Render complete managed profiles into the module's user state directory and
install links or copies into the real client locations. Authored templates remain
the source of truth; generated files never become checked-in source templates.
Local changes to a generated destination are drift, never silently overwritten.

Codex uses one effective global instruction file, including detection of
`CODEX_HOME` and an active `AGENTS.override.md`. agy uses one effective global
instruction contribution; do not install both a standalone block and an always-on
rule for the same snippet. Existing additional instructions are reported and
preserved. Do not assume file includes have identical semantics across clients.

## Resource/config installation

- Install the entire shared skill at one discovery location per client. Detect
  duplicate discovery through legacy paths or registries before adding another.
- `auto` uses directory junctions on Windows for eligible local directories,
  symlinks on supported Unix paths, and copies where file linking is unavailable.
  Explicit `link` failures are reported; copy fallback never hides a conflicting
  existing destination. Record the actual method for every installed resource.
- For full managed instructions, update the generated target and retain its link.
  For a managed block in an existing symlinked file, resolve and validate the final
  target before writing it. Atomic replacement of the link itself would sever it.
- Install `local-worker.md` and `local-reviewer.md` under OpenCode's `agents/`
  directory, rendered from role metadata and the canonical worker prompt. This
  replaces the earlier proposal to merge their definitions into the main JSON.
- Preserve provider/model settings and unrelated agents. Detect competing JSON
  definitions of those names. Leave model selection explicit in dispatch so a
  later model switch does not require regenerating hardcoded role aliases.
- Manage only the `opencode_worker` MCP contribution in each selected client.
  Preserve unrelated config and existing extra options. If no model alias is
  configured, report model readiness as pending; do not invent a usable alias.
- Inspect supported config-path overrides and reject unsupported formats or
  ambiguous precedence rather than rewriting them as plain JSON/TOML. Preserve
  comments in any config format that is edited.
- Refresh/restart guidance is reported after apply. Installing files is distinct
  from client discovery, runtime tool availability and actual local-model use.

## Minimal implementation boundaries

Keep the distribution/package name for compatibility; add the new public entry
point without renaming the whole checkout.

| Planned code area | Responsibility |
| --- | --- |
| `commands.py` | New argparse tree and dispatch |
| `cli.py` | Legacy entry point; thin compatibility adapter during extraction |
| `runtime.py` | Existing model/server orchestration extracted without redesign |
| `setup/manifest.py` | Typed resource IDs, client capabilities and exact target rules |
| `setup/planner.py` | Read-only discovery, conflicts and operation fingerprints |
| `setup/installer.py` | Validated writes, links/copies, backups and recovery journal |
| `setup/profiles.py` | Instruction composition and owned config contributions |
| `resources/` | Packaged authored assets and canonical prompt |

Use stdlib facilities where sufficient. Declare a focused format-preserving
dependency only when the supported configuration edits require one. Avoid
extracting a new general-purpose framework or copying the old managers wholesale.

## Apply, update and recovery contract

Preflight the whole selected plan before writes. Unknown ownership blocks apply
unless exact resource IDs are adopted. Save before/after fingerprints, link targets,
backups and operation results in a versioned receipt. Recheck each input immediately
before mutation; concurrent changes invalidate that operation.

Use atomic writes per file and a journal for the multi-file operation; do not
claim filesystem-wide atomicity. Restore completed operations on failure only when
their current contents still match this run's writes. Otherwise preserve the new
user changes, report incomplete recovery and retain backups. Serialize competing
setup operations with a lock, including recovery after an interrupted process.

Repeated apply of unchanged input is a no-op. Copy updates compare recorded
fingerprints. Removal acts only on unchanged owned files/blocks/config keys/links;
it never recursively deletes an unrelated target or replaces newer user work.

## Migration stages and acceptance

1. Implement the new CLI/compatibility seam and package the existing bridge assets.
   Prove help/plan/status require no running model or installed runtime services.
2. Implement installer/composition against isolated profile trees. Check repeated
   apply, input drift, adoption, malformed config, source-link preservation,
   link/copy methods, permissions, cancellation/interruption, rollback and removal.
3. Inventory every tracked dotfiles LLM asset and each existing managed destination.
   Preserve a source/destination/hash map and lossless source copies in the module.
   Reconcile the newer active Gemini instructions and Codex overrides explicitly.
   Build coverage for existing destinations before retiring their old installers;
   unsupported clients retain their working arrangement during the transition.
4. Add thin Windows and shell dotfiles hooks that invoke this module's setup for
   supported migrated clients. Remove their duplicate destination-writing logic
   only after replacement coverage is demonstrated. Handle the scripts repository
   being absent with an actionable result, not silent successful installation.
5. Review a real-machine plan, apply the reconciled migration, then confirm both
   clients discover the skill and tools and use the intended worker/role/model in
   a disposable project. No token-savings claim without measurement.

Retire original dotfiles sources after lossless copies and replacement coverage
are verified against the reviewed migration map. Preserve independent live profile
content, secrets and unrelated modules. Execute the migration with backups and a
recovery path. Temporary compatibility references must have a recorded retirement
condition.

## Sources and next step

This design supersedes manual activation in the
[earlier integration plan](../20261017-1540_coordinator-worker-integration/plan.md).
Its authored worker/skill resources and pending behavioral scenarios still apply.

Primary references: [Codex instruction discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[Codex skill discovery](https://learn.chatgpt.com/docs/build-skills),
[Antigravity rules](https://www.antigravity.google/docs/rules),
[Antigravity CLI skills](https://www.antigravity.google/docs/skills), and
[OpenCode agent files](https://opencode.ai/docs/agents/).

Installer implementation and source copying are complete. Next: review and apply
the real profile migration, validate runtime handoffs and retire old wiring only
after replacement coverage. Original dotfiles sources remain.
