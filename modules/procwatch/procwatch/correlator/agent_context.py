"""Agent attribution context parsing (PROCWATCH_CONTEXT and heuristic markers)."""

from __future__ import annotations

import json
from typing import Mapping

from procwatch.models import AgentContext, ProcessObservation


def parse_procwatch_context(raw_value: str | None) -> AgentContext | None:
    """Parse an explicit PROCWATCH_CONTEXT JSON payload into an AgentContext."""
    if not raw_value or not raw_value.strip():
        return None
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    agent_kind = _opt_str(payload.get("agent_kind") or payload.get("agent"))
    agent_session = _opt_str(payload.get("agent_session") or payload.get("session"))
    correlation_id = _opt_str(payload.get("correlation_id"))
    if not (agent_kind or correlation_id or agent_session):
        return None

    return AgentContext(
        version=_opt_str(payload.get("version")) or "1",
        correlation_id=correlation_id,
        agent_kind=agent_kind,
        agent_session=agent_session,
        phase=_opt_str(payload.get("phase")),
        repo=_opt_str(payload.get("repo")),
        worktree=_opt_str(payload.get("worktree")),
        branch=_opt_str(payload.get("branch")),
        producer=_opt_str(payload.get("producer")) or "procwatch_context",
        trust_level="instrumented",
    )


def infer_agent_context_from_env(environ: Mapping[str, str] | None) -> AgentContext | None:
    """Extract instrumented PROCWATCH_CONTEXT or heuristic agent markers from an env mapping."""
    if not environ:
        return None

    explicit = parse_procwatch_context(environ.get("PROCWATCH_CONTEXT"))
    if explicit is not None:
        return explicit

    if environ.get("CODEX_THREAD_ID") or environ.get("CODEX_CI"):
        return AgentContext(
            agent_kind="codex",
            agent_session=_opt_str(environ.get("CODEX_THREAD_ID")),
            producer="env_heuristic",
            trust_level="heuristic",
        )
    if environ.get("CLAUDECODE") or environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return AgentContext(
            agent_kind="claude_code",
            agent_session=_opt_str(environ.get("CLAUDE_CODE_SESSION")),
            producer="env_heuristic",
            trust_level="heuristic",
        )
    if environ.get("ANTIGRAVITY_AGENT") or environ.get("ANTIGRAVITY_CONVERSATION_ID"):
        return AgentContext(
            agent_kind="antigravity",
            agent_session=_opt_str(environ.get("ANTIGRAVITY_CONVERSATION_ID")),
            producer="env_heuristic",
            trust_level="heuristic",
        )
    return None


def read_process_agent_context(
    pid: int,
    *,
    ancestry: list[ProcessObservation] | None = None,
) -> AgentContext | None:
    """Best-effort live agent context inspection for a process or its ancestry."""
    try:
        import psutil  # type: ignore[import-untyped]

        env = psutil.Process(pid).environ()
        ctx = infer_agent_context_from_env(env)
        if ctx is not None:
            return ctx
    except Exception:
        pass

    if ancestry:
        for ancestor in ancestry:
            name = (ancestor.image_name or "").lower()
            if name in ("codex.exe", "claude.exe", "antigravity.exe"):
                return AgentContext(
                    agent_kind=name.removesuffix(".exe"),
                    producer="ancestry_heuristic",
                    trust_level="heuristic",
                )
    return None


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
