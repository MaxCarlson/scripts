from agent_sync.hooks.normalize import HookEvent, normalize_payload

CLAUDE_SESSION_START = {
    "session_id": "abc123",
    "cwd": "/repo",
    "transcript_path": "/home/.claude/projects/.../transcript.jsonl",
}

CLAUDE_PRE_TOOL = {
    "session_id": "abc123",
    "cwd": "/repo",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf /"},
}

CLAUDE_POST_TOOL = {
    "session_id": "abc123",
    "cwd": "/repo",
    "tool_name": "Write",
    "tool_input": {"file_path": "/repo/src/auth/token.py"},
    "tool_response": {"success": True},
}

CLAUDE_STOP = {
    "session_id": "abc123",
    "cwd": "/repo",
    "stop_reason": "end_turn",
}


def test_normalize_session_start() -> None:
    event = normalize_payload("claude", "SessionStart", CLAUDE_SESSION_START)
    assert event.provider == "claude"
    assert event.event == "SessionStart"
    assert event.vendor_session_id == "abc123"
    assert event.cwd == "/repo"
    assert event.tool is None


def test_normalize_pre_tool() -> None:
    event = normalize_payload("claude", "PreToolUse", CLAUDE_PRE_TOOL)
    assert event.event == "PreToolUse"
    assert event.tool is not None
    assert event.tool["name"] == "Bash"
    assert event.tool["input"]["command"] == "rm -rf /"


def test_normalize_post_tool() -> None:
    event = normalize_payload("claude", "PostToolUse", CLAUDE_POST_TOOL)
    assert event.tool is not None
    assert event.tool["name"] == "Write"
    assert event.tool["response"]["success"] is True


def test_normalize_stop() -> None:
    event = normalize_payload("claude", "Stop", CLAUDE_STOP)
    assert event.stop_reason == "end_turn"


def test_normalize_codex_maps_same_fields() -> None:
    event = normalize_payload("codex", "PreToolUse", CLAUDE_PRE_TOOL)
    assert event.provider == "codex"
    assert event.tool is not None
    assert event.tool["name"] == "Bash"


def test_pre_tool_blocks_git_push() -> None:
    from pathlib import Path
    from agent_sync.hooks.handlers.pre_tool import handle

    event = normalize_payload("claude", "PreToolUse", {
        "session_id": "x",
        "cwd": "/repo",
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
    })
    result = handle(event, Path("/repo/agent_sync/db/state.sqlite3"))
    assert result.get("type") == "block"


def test_pre_tool_allows_safe_commands() -> None:
    from pathlib import Path
    from agent_sync.hooks.handlers.pre_tool import handle

    event = normalize_payload("claude", "PreToolUse", {
        "session_id": "x",
        "cwd": "/repo",
        "tool_name": "Bash",
        "tool_input": {"command": "uv run pytest tests/ -v"},
    })
    result = handle(event, Path("/repo/agent_sync/db/state.sqlite3"))
    assert result == {}
