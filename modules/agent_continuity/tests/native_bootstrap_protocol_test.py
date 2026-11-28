"""Guarded offline tests exercising native_bootstrap.py for Codex app-server, AGY ACP, and Claude (LLMD-60)."""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from agent_continuity.native_bootstrap import (
    NativeAllocationStatus,
    NativeBootstrapRequest,
    allocate_native_session,
    provider_native_bootstrap_readiness,
)


def _py_server_cmd(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def test_codex_app_server_allocation_notifications_context_and_persistence_gate(tmp_path: Path) -> None:
    rollout_path = tmp_path / "rollout-2026-11-27-thr_123.jsonl"
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    server_script = (
        "import json, sys\n"
        f"rollout = {str(rollout_path)!r}\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('method') == 'initialize':\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'method': 'server/ready', 'params': {'ok': True}}), flush=True)\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'userAgent': 'codex-app-server/0.172.0'}}), flush=True)\n"
        "    elif msg.get('method') == 'thread/start':\n"
        "        params = msg['params']\n"
        "        assert params['ephemeral'] is False\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'method': 'thread/allocated', 'params': {'pending': True}}), flush=True)\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {\n"
        "            'approvalPolicy': 'on-request',\n"
        "            'cwd': params['cwd'],\n"
        "            'model': 'gpt-5',\n"
        "            'modelProvider': 'openai',\n"
        "            'sandbox': {'type': 'workspaceWrite'},\n"
        "            'thread': {'id': '01900000-0000-7000-8000-000000000001', 'ephemeral': False, 'path': rollout}\n"
        "        }}), flush=True)\n"
    )

    # 1. Allocated without persistence on disk -> cannot authorize interactive resume
    res = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            codex_home=codex_home,
            live_resume_qualified=True,
            command_override=_py_server_cmd(server_script),
        )
    )
    assert res.status == NativeAllocationStatus.ALLOCATED
    assert res.native_session_id == "01900000-0000-7000-8000-000000000001"
    assert res.persisted is False
    assert res.interactively_resumable is False
    assert res.can_authorize_interactive_resume is False
    assert res.fallback_prohibited is True
    assert len(res.notifications) == 2
    assert res.effective_provider_context["model"] == "gpt-5"
    assert res.effective_provider_context["user_agent"] == "codex-app-server/0.172.0"
    assert res.prompt_delivery_contract == {
        "requires_bootstrap_model_turn": False,
        "initial_prompt_deferred_to_attach": True,
        "workflow_init_mode": "additive_without_extra_turn",
    }

    # 2. Persistence evidence present (rollout + state_5.sqlite), but live_resume_qualified=False -> still blocked
    rollout_path.write_text(json.dumps({"type": "session_meta", "id": res.native_session_id}) + "\n", encoding="utf-8")
    with closing(sqlite3.connect(codex_home / "state_5.sqlite")) as conn:
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO threads(id) VALUES (?)", (res.native_session_id,))
        conn.commit()

    res_persisted_unqualified = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            codex_home=codex_home,
            live_resume_qualified=False,
            command_override=_py_server_cmd(server_script),
        )
    )
    assert res_persisted_unqualified.persisted is True
    assert res_persisted_unqualified.persistence_evidence["rollout_exists"] is True
    assert res_persisted_unqualified.persistence_evidence["state_db_row"] is True
    assert res_persisted_unqualified.interactively_resumable is False
    assert res_persisted_unqualified.can_authorize_interactive_resume is False

    # 3. Both persistence evidence AND live_resume_qualified=True -> authorized
    res_qualified = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            codex_home=codex_home,
            live_resume_qualified=True,
            command_override=_py_server_cmd(server_script),
        )
    )
    assert res_qualified.can_authorize_interactive_resume is True


def test_agy_acp_and_claude_allocation_contracts(tmp_path: Path) -> None:
    server_script = (
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('method') == 'initialize':\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'method': 'acp/status', 'params': {'phase': 'init'}}), flush=True)\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'protocolVersion': 1}}), flush=True)\n"
        "    elif msg.get('method') == 'session/new':\n"
        "        assert msg['params']['cwd']\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'sessionId': 'agy-conv-acp-0001'}}), flush=True)\n"
    )
    agy_res = allocate_native_session(
        NativeBootstrapRequest(
            provider="agy",
            cwd=str(tmp_path),
            live_resume_qualified=True,
            command_override=_py_server_cmd(server_script),
        )
    )
    assert agy_res.status == NativeAllocationStatus.ALLOCATED
    assert agy_res.native_session_id == "agy-conv-acp-0001"
    assert agy_res.persisted is False
    assert agy_res.can_authorize_interactive_resume is False
    assert len(agy_res.notifications) == 1
    assert agy_res.effective_provider_context["protocol_version"] == 1

    claude_res = allocate_native_session(NativeBootstrapRequest(provider="claude", cwd=str(tmp_path)))
    assert claude_res.status == NativeAllocationStatus.ALLOCATED
    assert claude_res.native_session_id is not None
    assert claude_res.effective_provider_context["launch_flag"] == "--session-id"
    assert claude_res.prompt_delivery_contract["requires_bootstrap_model_turn"] is False

    readiness = provider_native_bootstrap_readiness()
    assert readiness["claude"]["safe_to_enable_now"] is True
    assert readiness["codex"]["safe_to_enable_now"] is False
    assert readiness["agy"]["safe_to_enable_now"] is False


def test_native_bootstrap_failure_injection_timeout_cancel_and_recovery(tmp_path: Path) -> None:
    # 1. Malformed JSON frame -> UNCERTAIN, no ID, fallback prohibited
    malformed = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            command_override=_py_server_cmd("import sys; sys.stdin.readline(); print('{bad-json', flush=True)"),
        )
    )
    assert malformed.status == NativeAllocationStatus.UNCERTAIN
    assert malformed.native_session_id is None
    assert malformed.fallback_prohibited is True
    assert malformed.can_authorize_interactive_resume is False

    # 2. Mismatched response id -> UNCERTAIN
    mismatched = allocate_native_session(
        NativeBootstrapRequest(
            provider="agy",
            cwd=str(tmp_path),
            command_override=_py_server_cmd(
                "import json, sys; sys.stdin.readline(); "
                "print(json.dumps({'jsonrpc': '2.0', 'id': 999, 'result': {'protocolVersion': 1}}), flush=True)"
            ),
        )
    )
    assert mismatched.status == NativeAllocationStatus.UNCERTAIN
    assert "Mismatched JSON-RPC response id" in (mismatched.error_message or "")

    # 3. JSON-RPC error response -> FAILED
    rpc_error = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            command_override=_py_server_cmd(
                "import json, sys; m = json.loads(sys.stdin.readline()); "
                "print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'error': {'code': -32000, 'message': 'denied'}}), flush=True)"
            ),
        )
    )
    assert rpc_error.status == NativeAllocationStatus.FAILED
    assert "denied" in (rpc_error.error_message or "")

    # 4. Conflicting ephemeral=True in Codex thread/start -> FAILED
    ephemeral_conflict = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            command_override=_py_server_cmd(
                "import json, sys\n"
                "for line in sys.stdin:\n"
                "    m = json.loads(line)\n"
                "    if m['method'] == 'initialize':\n"
                "        print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {}}), flush=True)\n"
                "    else:\n"
                "        print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {'thread': {'id': 't1', 'ephemeral': True}}}), flush=True)\n"
            ),
        )
    )
    assert ephemeral_conflict.status == NativeAllocationStatus.FAILED
    assert ephemeral_conflict.native_session_id is None

    # 5. Crash / EOF after request -> UNCERTAIN, fallback prohibited
    crashed = allocate_native_session(
        NativeBootstrapRequest(
            provider="agy",
            cwd=str(tmp_path),
            command_override=_py_server_cmd("import sys; sys.stdin.readline(); sys.exit(2)"),
        )
    )
    assert crashed.status == NativeAllocationStatus.UNCERTAIN
    assert crashed.fallback_prohibited is True

    # 6. Bounded timeout kills child process cleanly
    timed_out = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            timeout_seconds=0.15,
            command_override=_py_server_cmd("import time; time.sleep(5)"),
        )
    )
    assert timed_out.status == NativeAllocationStatus.TIMED_OUT
    assert timed_out.native_session_id is None

    # 7. Cancel event aborts allocation cleanly
    cancel_ev = threading.Event()
    cancel_timer = threading.Timer(0.1, cancel_ev.set)
    cancel_timer.start()
    try:
        cancelled = allocate_native_session(
            NativeBootstrapRequest(
                provider="agy",
                cwd=str(tmp_path),
                timeout_seconds=5.0,
                cancel_event=cancel_ev,
                command_override=_py_server_cmd("import time; time.sleep(5)"),
            )
        )
    finally:
        cancel_timer.cancel()
    assert cancelled.status == NativeAllocationStatus.CANCELLED
    assert cancelled.native_session_id is None

    # 8. Recovery after uncertain response: subsequent clean allocation succeeds without recency fallback
    recovered = allocate_native_session(
        NativeBootstrapRequest(
            provider="agy",
            cwd=str(tmp_path),
            command_override=_py_server_cmd(
                "import json, sys\n"
                "for line in sys.stdin:\n"
                "    m = json.loads(line)\n"
                "    res = {'protocolVersion': 1} if m['method'] == 'initialize' else {'sessionId': 'agy-recovered-1'}\n"
                "    print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': res}), flush=True)\n"
            ),
        )
    )
    assert recovered.status == NativeAllocationStatus.ALLOCATED
    assert recovered.native_session_id == "agy-recovered-1"


def test_concurrent_independent_allocations(tmp_path: Path) -> None:
    def _run_one(idx: int) -> tuple[str, str | None, str]:
        if idx % 2 == 0:
            sid = f"codex-thr-{idx}"
            cmd = _py_server_cmd(
                "import json, sys\n"
                f"sid = {sid!r}\n"
                "for line in sys.stdin:\n"
                "    m = json.loads(line)\n"
                "    res = {'userAgent': 'codex'} if m['method'] == 'initialize' else {'thread': {'id': sid, 'ephemeral': False}}\n"
                "    print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': res}), flush=True)\n"
            )
            res = allocate_native_session(NativeBootstrapRequest(provider="codex", cwd=str(tmp_path), command_override=cmd))
        else:
            sid = f"agy-sess-{idx}"
            cmd = _py_server_cmd(
                "import json, sys\n"
                f"sid = {sid!r}\n"
                "for line in sys.stdin:\n"
                "    m = json.loads(line)\n"
                "    res = {'protocolVersion': 1} if m['method'] == 'initialize' else {'sessionId': sid}\n"
                "    print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': res}), flush=True)\n"
            )
            res = allocate_native_session(NativeBootstrapRequest(provider="agy", cwd=str(tmp_path), command_override=cmd))
        return sid, res.native_session_id, res.status

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_run_one, range(10)))

    for expected_sid, actual_sid, status in results:
        assert status == NativeAllocationStatus.ALLOCATED
        assert actual_sid == expected_sid
