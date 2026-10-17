# Integration notes

These resources are stored in the module only. Nothing here has been installed
into Codex, Antigravity, OpenCode or LM Studio.

## Coordinator resources

The [shared skill](../skills/local-agent-handoff/SKILL.md) can later be linked from:

| Client | User skill target | Instruction addition |
| --- | --- | --- |
| Codex | `~/.agents/skills/local-agent-handoff/` | Add the [coordinator snippet](../instructions/coordinator.snippet.md) to its effective global AGENTS.md |
| Antigravity CLI | `~/.gemini/antigravity-cli/skills/local-agent-handoff/` | Add the same snippet to one effective global AGENTS.md or GEMINI.md |

Keep the whole skill directory together: its relative references include the
worker prompt. Check existing targets before linking and preserve other skills.
Do not add a second Codex link that causes duplicate discovery.
Antigravity's current rules documentation supports AGENTS.md directly. Choose one
effective rule source per client; do not install the same paragraph through both
AGENTS.md and GEMINI.md imports or through a second plugin rule. Existing project
instruction entry points need no edits just to author these resources.

The skill's `agents/openai.yaml` keeps implicit discovery enabled and declares
the existing `opencode_worker` MCP dependency. This metadata neither installs an
MCP server nor configures its local model. Antigravity uses the shared SKILL.md;
the OpenAI metadata is a client-specific addition.

The existing dotfiles installer can link to this module as the canonical source.
Standalone Gemini CLI and App/IDE deployment are outside this scope.

## Worker prompt

The [example config](../integrations/opencode-agent.example.json) adds an OpenCode
agent named `local-worker` and an inspection role named `local-reviewer`.
Their prompt-file references are relative to the example
config's directory. If you merge the example into another config, resolve that
path to the canonical prompt and update the reference for the destination.
Do not overwrite the user's complete OpenCode config with this fragment.

The example does not select the active model or default agent. Both roles deny
OpenCode's `task` tool and the coordinator's `local-agent-handoff` skill to prevent
recursive delegation. The reviewer also denies built-in edits and shell execution.
Other tools and global permission rules remain inherited: these are agent tool
restrictions, not a separate operating-system sandbox. Inspect any configured MCP
or custom tools before relying on a profile for a review requiring no writes.

The handoff selects `local-worker` and the intended `lmstudio` provider/model
explicitly. Verify the named agent is present before selecting it. A prompt file
in this module does not configure the running server by itself.

Keep one canonical [worker prompt](../skills/local-agent-handoff/resources/local-worker.md).
If the resources later move, update the reference. Do not assume the LM Studio GUI
system prompt is included in API calls. A prompt specifies desired behavior;
existing runtime/tool permissions determine actual capability.

OpenCode reads repository AGENTS.md and can discover `.agents/skills`, including a
coordinator skill installed there. The worker prompt explicitly identifies its
role, and the example blocks reusing the handoff skill. Keep worker-specific
domain skills separate from the coordinator's delegation procedure.

## Existing bridge

Run the bridge through `local-agent-bridge` or `python -m local_agent_bridge`.
Its MCP server name is
`opencode_worker`; its current transport is pinned to `opencode-mcp@3.0.0`.
The configured default provider/model pair must refer to the loaded API alias.
The `essential` tool profile reduces the tool catalog; it does not make the worker
read-only. No bridge settings or permissions are changed by these resource files.

## Timeouts, results and lifecycle

Prefer `opencode_fire` for coding jobs, then observe by `jobId` with the same
absolute directory. A 30-second `opencode_wait` fits under Codex's documented
60-second default MCP tool timeout with processing headroom. `opencode_run` has a
600-second default observation window; set a smaller `maxDurationSeconds` or
deliberately adjust the client's `tool_timeout_sec` before using a longer wait.
An observation timeout does not stop inference. Follow
[results and recovery](../skills/local-agent-handoff/references/results-and-recovery.md).

Codex also supports server startup timeout, tool allow/deny lists, per-tool
approval policy and output budgets. Treat these as optional client settings,
verified against the installed client. Avoid truncating job IDs or required-input
details. The existing loader can rebuild its Codex MCP table when defaults change;
recheck extra settings after reconfiguration. Bounded waits work with the existing
defaults and require no loader modification.

For machine-readable final results, see the optional
[result schema](../skills/local-agent-handoff/resources/result.schema.json).
OpenCode must permit StructuredOutput for schema-constrained output. Start with
plain text if runtime support is uncertain; source/diff review remains required.

Keep the externally managed OpenCode server running while work is in progress.
The bridge does not guarantee that an idle coordinator is awakened by completion.
Avoid closing its foreground server until jobs finish or are explicitly cancelled.

## Optional next stages

The [current plan](plans/20261017-1540_coordinator-worker-integration/plan.md)
separates local resource authoring, live activation/evaluation, and optional plugin
or hook packaging. The [research decisions](RESEARCH.md) explain the alternatives.
No plugin, hook, installer command or additional orchestration service is introduced
by this resource update.

## Later verification

Check skill discovery in each client, the running server's agent/model selection,
and the effective prompt. Then exercise the scenarios in [VALIDATION.md](VALIDATION.md)
when worker use is enabled. Keep current working settings until a concrete problem
justifies changing them.

Sources: [Codex skills](https://learn.chatgpt.com/docs/build-skills),
[Antigravity skills](https://www.antigravity.google/docs/skills),
[OpenCode agent prompts](https://opencode.ai/docs/agents/).
