"""Markdown templates written by agent-sync init."""

AGENTS_MD_SECTION = """

## agent_sync

External LLM CLIs and local models must not be invoked unless the user explicitly enables delegation for the session or command. When enabled, use `agent-sync delegate`, `agent-sync review`, or `agent-sync verify` so prompts, outputs, and audit metadata are recorded under `.agent_sync/audit/`.

Prefer delegation for bounded, token-heavy, or independently verifiable tasks where the final result matters more than preserving the full primary conversation history. Keep repo-editing work in the primary agent unless `agent-sync dispatch` has created isolated worktrees and claim locks.
"""

CLAUDE_MD_SECTION = AGENTS_MD_SECTION
GEMINI_MD_SECTION = AGENTS_MD_SECTION

AGENT_CONTRACT = """# agent_sync Agent Contract

1. Do not call other LLM CLIs unless the user explicitly allows it.
2. Use `agent-sync delegate` for bounded subtasks.
3. Use `agent-sync review` for high-stakes critique.
4. Use `agent-sync verify` for independent validation.
5. Treat `.agent_sync/audit/` as the canonical record of delegated prompts and outputs.
6. Do not silently edit files through delegated workers unless an isolated worktree/dispatch flow is active.
"""
