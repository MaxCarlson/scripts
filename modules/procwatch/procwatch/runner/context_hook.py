"""Opt-in PROCWATCH_CONTEXT propagation helper for agent/orchestrator launchers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping
import uuid

from procwatch.correlator.peb_git import resolve_git_context

_MAX_FIELD_LEN = 256


def _clip(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:_MAX_FIELD_LEN] if text else None


def build_instrumented_env(
    base_env: Mapping[str, str] | None = None,
    *,
    execution_id: str | None = None,
    agent_kind: str | None = None,
    agent_session: str | None = None,
    phase: str | None = None,
    cwd: str | Path | None = None,
    producer: str = "procwatch_exec",
    parent_execution_id: str | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Return an env copy with validated, non-secret PROCWATCH_CONTEXT JSON injected."""
    env = dict(os.environ if base_env is None else base_env)
    exec_id = _clip(execution_id) or str(uuid.uuid4())
    git_ctx = resolve_git_context(cwd or os.getcwd())

    # Preserve existing heuristic/instrumented parent hints only if explicit values omitted.
    inferred_agent = _clip(agent_kind)
    inferred_session = _clip(agent_session)
    if not inferred_agent:
        if env.get("CODEX_THREAD_ID") or env.get("CODEX_CI"):
            inferred_agent = "codex"
            inferred_session = inferred_session or _clip(env.get("CODEX_THREAD_ID"))
        elif env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
            inferred_agent = "claude_code"
            inferred_session = inferred_session or _clip(env.get("CLAUDE_CODE_SESSION"))
        elif env.get("ANTIGRAVITY_AGENT") or env.get("ANTIGRAVITY_CONVERSATION_ID"):
            inferred_agent = "antigravity"
            inferred_session = inferred_session or _clip(env.get("ANTIGRAVITY_CONVERSATION_ID"))

    context_payload: dict[str, Any] = {
        "version": "1",
        "correlation_id": exec_id,
        "execution_id": exec_id,
        "agent_kind": inferred_agent,
        "agent_session": inferred_session,
        "phase": _clip(phase),
        "repo": _clip(git_ctx.repo_root if git_ctx else None),
        "worktree": _clip(git_ctx.worktree_path if git_ctx else None),
        "branch": _clip(git_ctx.branch if git_ctx else None),
        "producer": _clip(producer) or "procwatch_exec",
        "parent_execution_id": _clip(parent_execution_id),
        "trust_level": "instrumented",
    }
    clean_payload = {k: v for k, v in context_payload.items() if v is not None}
    env["PROCWATCH_CONTEXT"] = json.dumps(clean_payload, separators=(",", ":"))
    return env, clean_payload
