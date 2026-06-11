"""Compatibility routing API for agent_sync."""

from enum import Enum
import sqlite3
from typing import FrozenSet


class AgentCapability(str, Enum):
    """Static capability labels used by dispatch manifests."""

    CODE_WRITE = "code_write"
    CODE_REVIEW = "code_review"
    TEST_GENERATE = "test_generate"
    DOC_WRITE = "doc_write"
    LOCAL_ONLY = "local_only"
    RESEARCH = "research"
    VERIFY = "verify"


_AGENT_CAPABILITIES: dict[str, frozenset[AgentCapability]] = {
    "claude": frozenset({
        AgentCapability.CODE_WRITE,
        AgentCapability.CODE_REVIEW,
        AgentCapability.TEST_GENERATE,
        AgentCapability.DOC_WRITE,
        AgentCapability.RESEARCH,
        AgentCapability.VERIFY,
    }),
    "codex": frozenset({
        AgentCapability.CODE_WRITE,
        AgentCapability.CODE_REVIEW,
        AgentCapability.TEST_GENERATE,
        AgentCapability.VERIFY,
    }),
    "gemini": frozenset({
        AgentCapability.CODE_REVIEW,
        AgentCapability.DOC_WRITE,
        AgentCapability.RESEARCH,
        AgentCapability.VERIFY,
    }),
    "copilot": frozenset({AgentCapability.CODE_WRITE, AgentCapability.TEST_GENERATE}),
    "local": frozenset({
        AgentCapability.DOC_WRITE,
        AgentCapability.LOCAL_ONLY,
        AgentCapability.RESEARCH,
    }),
    "local-lmstudio": frozenset({
        AgentCapability.DOC_WRITE,
        AgentCapability.LOCAL_ONLY,
        AgentCapability.RESEARCH,
    }),
}


def select_agent(
    *,
    conn: sqlite3.Connection,
    preferred: str,
    capabilities_required: FrozenSet[AgentCapability],
) -> str:
    """Return the best agent name for a task from the SQLite registry.

    This function preserves the planned Phase 3 API while the higher-level
    delegation CLI uses JSON worker config.
    """
    rows = conn.execute("SELECT agent_name FROM agents").fetchall()
    known = {row["agent_name"] if hasattr(row, "keys") else row[0] for row in rows}
    if preferred != "auto":
        if preferred not in known:
            raise ValueError(f"Unknown agent '{preferred}'. Registered: {sorted(known)}")
        missing = capabilities_required - _AGENT_CAPABILITIES.get(preferred, frozenset())
        if missing:
            raise ValueError(f"Agent '{preferred}' lacks required capabilities: {[item.value for item in missing]}")
        return preferred

    load: dict[str, int] = {name: 0 for name in known}
    try:
        load_rows = conn.execute(
            "SELECT agent_name, COUNT(*) AS n FROM runs WHERE status = 'active' GROUP BY agent_name"
        ).fetchall()
        for row in load_rows:
            agent_name = row["agent_name"] if hasattr(row, "keys") else row[0]
            n = row["n"] if hasattr(row, "keys") else row[1]
            load[agent_name] = int(n)
    except sqlite3.Error:
        pass

    candidates = [
        name for name in known
        if capabilities_required <= _AGENT_CAPABILITIES.get(name, frozenset())
    ]
    if not candidates:
        raise ValueError(f"No registered agent satisfies capabilities: {[item.value for item in capabilities_required]}")
    return min(candidates, key=lambda name: (load.get(name, 0), name))
