"""CodexAdapter compatibility wrapper."""

from agent_sync.adapters.command import CommandAdapter


class CodexAdapter(CommandAdapter):
    """Command-backed adapter for codex."""
