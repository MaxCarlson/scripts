# Agent Instruction Discovery Research

## Question

Should the setup system place complete instructions directly in each native instruction file, or keep short entry files that point to shared documentation?

## Findings

### OpenAI Codex

Codex automatically applies `AGENTS.md` files by directory scope. A file governs its containing directory and descendants, and more deeply nested files take precedence for conflicts. Root and applicable scoped instructions are supplied to the agent automatically.

Codex does not currently document a general `@file` import syntax for `AGENTS.md`. A plain sentence telling Codex to read another file is useful navigation, but it should not be treated as equivalent to automatic context injection.

Primary source:

- https://github.com/openai/codex/blob/main/codex-rs/protocol/src/prompts/base_instructions/default.md

### Claude Code

Claude Code automatically loads project and nested `CLAUDE.md` files according to directory scope. It also explicitly supports `@path/to/file` imports, including recursive imports with a bounded depth.

Primary source:

- https://code.claude.com/docs/en/memory

### Gemini CLI

Gemini CLI supports hierarchical `GEMINI.md` context, including scoped files discovered for relevant subdirectories. It explicitly supports `@path/to/file.md` imports and provides `/memory show` to inspect the final loaded context.

Primary source:

- https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/gemini-md.md

### GitHub Copilot

Copilot supports repository-wide `.github/copilot-instructions.md`, path-specific `.github/instructions/*.instructions.md`, and agent instruction files such as `AGENTS.md`. Copilot CLI explicitly supports `@` references in repository instruction files. Other Copilot environments document automatic loading of their native instruction files but do not uniformly guarantee the same import behavior.

Primary sources:

- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions
- https://docs.github.com/en/copilot/how-tos/configure-custom-instructions-in-your-ide/add-repository-instructions-in-your-ide

## Design decision

Use a hybrid instruction layout:

1. Put the essential safety, planning, evidence, and branch-ownership rules directly in managed `AGENTS.md` blocks.
2. Create nested `AGENTS.md` files at every independent planning scope so Codex receives scoped rules automatically.
3. Create `CLAUDE.md` and `GEMINI.md` files that import the local `AGENTS.md` and shared detailed workflow using their documented native import syntax.
4. Put essential rules directly in `.github/copilot-instructions.md` and path-specific Copilot files, while also adding imports where supported.
5. Keep detailed protocol in `docs/agent/DEVELOPMENT_LEDGER_WORKFLOW.md` to avoid duplicating a long workflow in every native file.
6. Never make a critical local-agent rule available only through ChatGPT general Custom Instructions.

This balances instruction reliability against context size. Essential rules are always present in native context; detailed rules are automatically imported where the tool guarantees imports and explicitly referenced elsewhere.

## Operational implication

After changing instruction files during an active coding-agent session, start a new session or explicitly reload memory where the tool supports it. Instruction discovery commonly occurs at session startup or when a relevant subtree is first accessed, so an existing session may retain stale context.
