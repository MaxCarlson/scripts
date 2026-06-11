"""CopilotAdapter compatibility wrapper."""

from agent_sync.adapters.command import CommandAdapter


class CopilotAdapter(CommandAdapter):
    """Command-backed adapter for copilot."""
