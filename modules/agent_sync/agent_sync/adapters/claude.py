"""ClaudeAdapter compatibility wrapper."""

from agent_sync.adapters.command import CommandAdapter


class ClaudeAdapter(CommandAdapter):
    """Command-backed adapter for claude."""
