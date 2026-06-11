"""Markdown renderers for generated docs."""

from agent_sync.docs_gen.templates import AGENT_CONTRACT


def render_agent_contract() -> str:
    """Render the static agent contract."""
    return AGENT_CONTRACT
