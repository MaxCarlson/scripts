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

`local-agent setup status` is a read-only sync audit. It leads with the overall
state and counts for current, outdated, missing, and conflicting resources, then
shows each resource's destination, copy/link method, verification type, and source
path. It uses terminal colors only for interactive output and respects `NO_COLOR`.
JSON status keeps the existing `operations` records and adds a summary, optional
feature selections, and provenance for the active package and resource sources.
Files and copied trees are compared byte for byte; managed JSON/TOML values are
compared semantically, so line-ending or formatting differences alone are not
reported as setup drift. Disabled optional features are reported as disabled, not
as failed installations. Status never applies changes; use the displayed plan and
apply commands when updates are needed.

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

## Read-only source retrieval

Use the additive **local-agent code** commands to find paths, search source, and fetch
an exact line range without starting OpenCode or LM Studio:

    local-agent code locate retrieval -C "C:\src\my project" -j
    local-agent code search "def build_parser" -p local_agent_bridge/commands.py -C "C:\src\my project" -j
    local-agent code search "build_parser\(" -r -p local_agent_bridge/commands.py -C "C:\src\my project" -j
    local-agent code context modules/local_agent_bridge/local_agent_bridge/commands.py 37 80 -C "C:\src\my project" -j

By default, path discovery uses Git tracked files and nonignored untracked files.
Repeat **-p/--path** to explicitly include selected ignored or untracked files.
Outside a Git worktree, discovery uses a sorted filesystem scan. Generated,
cache, dependency, and VCS directories are excluded. Paths supplied to **context**
are workspace-relative; absolute paths, traversal, and resolved paths outside
the workspace are rejected.

Literal search is the default. **-r/--regex** opts into Python regular-expression
syntax. Search examines at most 200 candidate files by default; repeat **-p/--path**
or raise **-f/--max-files** to focus it. Responses preserve workspace-relative path and line provenance. JSON
includes the discovery/search engine, status, truncation state, and any errors.
The default budgets are 200 returned paths / 8 KiB, 80 matches across up to 200
files / 12 KiB, and 200 context lines / 16 KiB. Match and excerpt lines are
limited to 4 KiB. Search skips files larger than 2 MiB and stops scanning at
32 MiB per request. **-b/--max-bytes** and the operation-specific limit flags
adjust these bounds; truncation is explicit.

This retrieval interface is read-only and has no dependency on a model server.
The CLI alone adds no setup-managed files or configuration.

For Python repositories, `symbols` returns imports, definitions, classes,
methods, signatures, exact line ranges, and a source SHA-256. `map` ranks
symbols against a task description and builds a fresh bounded map:

```powershell
local-agent code symbols modules/local_agent_bridge/local_agent_bridge/commands.py -C "C:\src\scripts" -j
local-agent code map "add checkpoint CLI command" -C "C:\src\scripts" --max-files 80 --max-results 80 --max-tokens 3000 -j
```

AST maps are rebuilt on each request, so there is no persistent index to go
stale. Each result includes its file hash for provenance. `--max-tokens` is a
conservative UTF-8 byte upper bound, not a provider tokenizer measurement; the
serialized output is also constrained by `--max-bytes`. Non-Python files remain
available through lexical retrieval.

## Durable task checkpoints

Save a validated task envelope to an atomic, versioned checkpoint, then build
a recovery packet after an interruption:

```powershell
local-agent checkpoint save -C "C:\src\my project" -i task.json -j
local-agent checkpoint show task-42 -C "C:\src\my project" -j
local-agent checkpoint recover task-42 -C "C:\src\my project" -j
local-agent checkpoint recover-session ses_01example -C "C:\src\my project" -j
```

The JSON input contains `task_id`, `objective`, `authorized_scope`, and
`next_action`, with optional `identities`, `confirmed_sources`, decisions,
assumptions, modified paths, verification, pending checks, and blockers. By
default state is stored under `~/.local/share/local-agent/checkpoints`; use
`-S/--state-dir` to select another directory outside the Git working tree.
Checkpoints store hashes and line ranges for confirmed sources, not source
contents. Recovery marks changed or unavailable revisions and source evidence
stale, retains session/job/message identities, and never resubmits work.

### Optional OpenCode compaction context

OpenCode 1.19.3 exposes the experimental
`experimental.session.compacting` plugin hook. The optional bridge plugin adds
a fresh recovery packet for the matching session to the default compaction
context; it does not replace the summary prompt or change auto-continue. The
task checkpoint must include the exact `identities.session_id` for lookup. The
hook only runs the local `local-agent checkpoint recover-session` CLI with
direct argv and a five-second timeout; absent or invalid local state leaves
normal compaction unchanged. Its context is capped below 4 KiB and preserves
the no-resubmission rule.

Install it through the receipt-managed setup planner:

```powershell
local-agent setup plan --checkpoint-compaction -o compaction-plan.json
local-agent setup apply -i compaction-plan.json
```

The plugin is off by default and can be planned for removal with
`--no-checkpoint-compaction`. OpenCode must be using version 1.19.3-compatible
plugin APIs, and its server process must have `local-agent` on `PATH`. This
experimental hook is version-specific; no live OpenCode session was used to
validate runtime loading.

## Optional OpenCode retrieval tools

OpenCode can expose the same bounded retrieval API through two read-only custom
tools: `code_locate` and `code_context`. They are opt-in and are not installed by
default. Review a plan, then apply the exact saved plan:

```powershell
local-agent setup plan --code-retrieval -o retrieval-plan.json
local-agent setup apply -i retrieval-plan.json
```

The planner receipt owns the helper and each tool file separately under
`~/.config/opencode/tools/`, preserving other tools and OpenCode configuration.
The adapter calls the installed `local-agent` executable through a direct argv
process invocation and uses the active OpenCode project directory. Ensure that
executable is on the OpenCode server's `PATH`. To remove the optional tools,
review and apply a plan made with `--no-code-retrieval`. No server is started
and no model is requested by setup.

### Optional structural tools

For Python work, `code_symbols` returns a bounded AST outline for one file and
`code_map` ranks relevant symbols across the active workspace. Both include
source hashes and line provenance, and both reuse the same retrieval CLI and
receipt-managed installer. Structural retrieval includes the lexical tools;
enable all four with:

```powershell
local-agent setup plan --structural-retrieval -o structural-plan.json
local-agent setup apply -i structural-plan.json
```

The map is capped at 80 files and 40 symbols, and its `--max-tokens` option
uses serialized UTF-8 bytes as a conservative upper bound rather than claiming
provider-tokenizer accuracy. To retire the structural tools, apply a plan made
with `--no-structural-retrieval`. The lexical pair has separate receipt entries
and can also be retired with `--no-code-retrieval`. No OpenCode server or model
is started.


## Models and bridge

```powershell
local-agent model list
local-agent model rename old-alias new-alias -a
local-agent model remove old-alias -a
local-agent model verify qwen38_23GB -j
local-agent run -M qwen38_23GB -c 32768 -o 8192
local-agent run -M qwen38_23GB -c 65536 -o 8192 --update-model-limits
```

`rename` and `remove` preview unless `-a/--apply` is supplied. Remove unregisters
and unloads an alias; it does not delete downloaded weights. `run` retains the
existing configure/load/foreground-server workflow and options. `-c/--context-length`
sets both the LM Studio requested load context and the OpenCode alias context.
`-o/--output-tokens` sets OpenCode's output allowance; both limits must be positive
integers and output must be smaller than context. Existing incompatible limits
require `--update-model-limits`. Incompatible explicit LM Studio provider settings
require `--update-opencode-provider`. Unrelated model fields, provider options,
comments, other providers and file links are preserved.

The tested Q4_K_M `qwen38_23GB` profile uses 8,192 output tokens. That is a
profile-specific recommendation, not a universal default. Other aliases keep the
32,768 context default and need `-o` when an explicit context is configured. A
legacy alias without complete limits stays unchanged and is warned about.

`model verify` is read-only. It reports requested limits when supplied, static
alias metadata, OpenCode's effective `/config` and `/config/providers` resolution,
and LM Studio's `lms ps` loaded context separately. Use `-d/--directory` to check
project-level overrides. If OpenCode is offline, it reports static-only confidence;
if LM Studio cannot report the loaded context, that capacity is `null`/unknown.
Exit code 0 means no mismatch was found, 1 means a mismatch, and 2 means invalid
verification input. It never loads or unloads a model or starts a server.

The measured 64K run used Q4_K_M on an RTX 5090 and reported about 25.1 GiB total
device VRAM use with no CPU offload on that host. This does not establish that
64K fits other models or devices. No 64K profile is applied to user configuration
by this change. Setup never starts servers, calls models or installs external
runtime tools.

## OpenCode server status and TUI attachment

These commands inspect or connect to an OpenCode server that is already running;
they never start or restart it:

```powershell
local-agent opencode status
local-agent opencode ping
local-agent opencode status -j
local-agent opencode attach
local-agent opencode attach -s ses_example
local-agent opencode attach -d "C:\src\my project"
```

`status` and its `ping` alias request OpenCode's `/global/health` endpoint.
They report whether OpenCode itself is healthy; they do not check LM Studio or
claim that a model is loaded. `setup status` is different: it checks the files
and settings managed by the local-agent installer and does not contact the
OpenCode server.

The default endpoint is `http://127.0.0.1:4096`. `-p/--port` selects another
localhost port, `-u/--url` supplies an explicit `http` or `https` endpoint, and
`-t/--timeout` sets the health-check timeout (default 3 seconds, maximum 60).
Resolution order is explicit URL, explicit port, `OPENCODE_BASE_URL`, then the
default. URL and port cannot be supplied together. MCP config files are not
searched because Codex and agy can contain different worker endpoints. A custom
remote URL must be explicit; local OpenCode server authentication variables are
used only for loopback endpoints and are removed from the child environment for
remote attachment.

`attach` starts the installed OpenCode CLI's interactive TUI after a healthy
server check. It is not a read-only viewer: the command only connects and does
not submit prompts, cancel work, change models, or select a session for you, but
you can perform interactive actions in the TUI. Without `-s`, OpenCode shows its
normal session experience. Use `-s/--session SESSION_ID` to continue a specific
session and `-d/--dir DIRECTORY` to pass the project directory. For example,
copy the `sessionId` returned by an `opencode_fire` call, then run:

```powershell
local-agent opencode attach -s ses_01example -d "C:\src\delegated project"
```

If `status` reports `NOT RUNNING`, confirm the server is already running and
check the port it reports; `local-agent` will not install or restart it. An
authentication response means the server requires Basic auth; for a local
server, set `OPENCODE_SERVER_PASSWORD` and optionally
`OPENCODE_SERVER_USERNAME` in the environment before retrying. Connection
timeouts can be adjusted with `-t`. Install OpenCode and ensure `opencode` is on
`PATH` if `attach` reports that its executable is missing.

Version 3.0.0 standardized on `local-agent`, retains `local_agent` as an alias,
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
