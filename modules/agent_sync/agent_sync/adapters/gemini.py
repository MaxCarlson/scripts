"""GeminiAdapter compatibility wrapper."""

from agent_sync.adapters.command import CommandAdapter


class GeminiAdapter(CommandAdapter):
    """Command-backed adapter for gemini."""
