# Integration decisions from primary sources

Reviewed 2026-10-17. These are documentation-backed design decisions, not evidence
that the installed clients or local model have passed behavioral evaluation.

| Mechanism | Decision and source |
| --- | --- |
| Persistent policy | Keep coordinator routing short. Current [Antigravity rules](https://www.antigravity.google/docs/rules/) support AGENTS.md directly; no separate policy copy is needed. [Codex](https://learn.chatgpt.com/docs/agent-configuration/agents-md) combines global and repository instruction files. |
| Shared skill | One portable SKILL.md handles the procedure. [Codex](https://learn.chatgpt.com/docs/build-skills) and [Antigravity](https://www.antigravity.google/docs/skills/) both disclose metadata first, then load relevant instructions. Codex metadata adds implicit invocation policy and an MCP dependency. |
| Local roles | [OpenCode agents](https://opencode.ai/docs/agents/) support named prompts and per-agent permissions. Use the example local-worker/local-reviewer roles, with one canonical prompt and explicit model parameters from the coordinator. |
| Recursion | [OpenCode discovers shared skills](https://opencode.ai/docs/skills/) and repository instructions too. Deny the coordinator skill and task tool for these workers; do not make the worker redispatch itself. |
| Jobs and timeouts | [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp) documents a 60-second tool timeout. The [pinned bridge reference](https://github.com/AlaeddineMessadi/opencode-mcp/blob/v3.0.0/docs/tools.md) documents fire/check/wait and a 600-second default run observation. Prefer dispatch plus bounded observation and preserve exact job correlation. |
| Tool catalog | The [3.0.0 configuration](https://github.com/AlaeddineMessadi/opencode-mcp/blob/v3.0.0/docs/configuration.md) describes essential as a smaller discovery catalog, not a security boundary. Retain it and use OpenCode permissions for actual capability limits. |
| Results/recovery | The bridge exposes structured job state and optional JSON Schema results. [Architecture](https://github.com/AlaeddineMessadi/opencode-mcp/blob/v3.0.0/docs/architecture.md) distinguishes observation timeout, cancellation and handle expiry. No timeout-driven resubmission. |
| Plugins | Later package the same resources with separate [Codex](https://developers.openai.com/plugins/build/plugins) and [Antigravity](https://www.antigravity.google/docs/plugins?tab=cli) manifests/MCP wiring. Avoid duplicated skill sources and duplicate MCP registration. A plugin installs resources; it does not by itself improve task selection. |
| Hooks | Optional [Codex](https://learn.chatgpt.com/docs/hooks) and [Antigravity](https://www.antigravity.google/docs/hooks/) hooks can check readiness and record job state. Use deterministic checks; avoid launching model work on every session start. Hook formats and events must be adapted per client. |
| MCP wrapper | [Server/tool metadata](https://developers.openai.com/plugins/build/mcp-server) can guide selection and a wrapper could enforce required directory/model parameters. Defer new infrastructure until the existing skill/tool workflow exposes a concrete gap. |
| Native subagents | [Codex custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents) cannot override the parent's model_provider; [Antigravity native subagents](https://www.antigravity.google/docs/subagents/) document inherit/flash/pro tiers. Neither establishes a direct LM Studio subagent for the current cloud coordinator. Keep the existing MCP route. |
| Alternative SDK | [Antigravity SDK](https://www.antigravity.google/docs/sdk/local-models/) explicitly supports LM Studio through LocalOpenAIAgentConfig and a lightweight preset. This is a separate future framework comparison, not a required bridge replacement. |
| Legacy workflows | Prefer skills. Google's [migration guidance](https://www.antigravity.google/docs/migration/workflows-to-skills/) describes retirement of the legacy workflow system. |
| Model behavior | Preserve load/inference settings. [LM Studio tools](https://lmstudio.ai/docs/developer/openai-compat/tools) and [templates](https://lmstudio.ai/docs/app/advanced/prompt-template) explain why instruction prompts and chat templates have different responsibilities. |

The module remains the resource source of truth. Global profiles or future plugin
packages consume those resources; they do not create another maintained copy.
Actual cloud-token savings, local task quality and installed-client compatibility
remain measurements for the live stage.
