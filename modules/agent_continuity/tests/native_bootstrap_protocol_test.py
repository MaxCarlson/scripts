"""Guarded offline tests exercising hardened native_bootstrap.py (LLMD-60 & LLMD-62 contract)."""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from agent_continuity.native_bootstrap import (
    MAX_INTERNAL_QUEUE_ITEMS,
    MAX_NOTIFICATIONS,
    MAX_RPC_FRAME_BYTES,
    MAX_STDERR_LINES,
    NativeAllocationStatus,
    NativeBootstrapRequest,
    VerifiedLiveQualification,
    allocate_native_session,
    provider_native_bootstrap_readiness,
)


def _py_server_cmd(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def _runtime_kind() -> str:
    if os.name == "nt":
        return "windows"
    if platform.system().lower() == "darwin":
        return "macos"
    return "linux"


def test_codex_strict_sequence_exact_persistence_and_bound_qualification(tmp_path: Path) -> None:
    rollout_path = tmp_path / "rollout-2026-11-27-thr_123.jsonl"
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    server_script = (
        "import json, sys\n"
        f"rollout = {str(rollout_path)!r}\n"
        "stage = 'init'\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    method = msg.get('method')\n"
        "    if stage == 'init':\n"
        "        assert method == 'initialize' and 'id' in msg\n"
        "        stage = 'wait_initialized'\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'method': 'server/ready', 'params': {'ok': True}}), flush=True)\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'userAgent': 'codex-app-server/0.172.0'}}), flush=True)\n"
        "    elif stage == 'wait_initialized':\n"
        "        assert method == 'initialized' and 'id' not in msg\n"
        "        stage = 'wait_thread_start'\n"
        "    elif stage == 'wait_thread_start':\n"
        "        assert method == 'thread/start' and 'id' in msg\n"
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
        "        stage = 'done'\n"
    )

    qual = VerifiedLiveQualification(
        provider="codex",
        provider_version="codex-app-server/0.172.0",
        runtime_kind=_runtime_kind(),
        mechanism="codex app-server --stdio",
        qualified=True,
    )

    # 1. Arbitrary non-empty rollout file with wrong/missing thread ID does NOT count as persisted
    rollout_path.write_text('{"type": "noise", "id": "other-id"}\n', encoding="utf-8")
    res_noise = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            codex_home=codex_home,
            expected_approval_policy="on-request",
            expected_sandbox_type="workspaceWrite",
            live_qualification=qual,
            command_override=_py_server_cmd(server_script),
        )
    )
    assert res_noise.status == NativeAllocationStatus.ALLOCATED
    assert res_noise.native_session_id == "01900000-0000-7000-8000-000000000001"
    assert res_noise.persistence_evidence["shutdown_mode"] == "graceful_eof"
    assert res_noise.persistence_evidence["helper_exit_code"] == 0
    assert res_noise.persistence_evidence["rollout_exists"] is True
    assert res_noise.persistence_evidence["rollout_id_verified"] is False
    assert res_noise.persisted is False
    assert res_noise.can_authorize_interactive_resume is False
    assert res_noise.requested_context["expected_approval_policy"] == "on-request"
    assert res_noise.effective_provider_context["approval_policy"] == "on-request"
    assert res_noise.prompt_delivery_contract == {
        "requires_bootstrap_model_turn": False,
        "instruction_delivery_performed": False,
        "supports_ordered_instruction_snapshots": True,
        "workflow_init_mode": "additive_without_extra_turn",
        "initial_prompt_delivery": "one_time_on_attach",
    }

    # 2. Valid rollout session_meta + state_5.sqlite cwd match, but mismatched version qualification -> blocked
    rollout_path.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": res_noise.native_session_id}}) + "\n",
        encoding="utf-8",
    )
    with closing(sqlite3.connect(codex_home / "state_5.sqlite")) as conn:
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, cwd TEXT)")
        conn.execute("INSERT INTO threads(id, cwd) VALUES (?, ?)", (res_noise.native_session_id, str(tmp_path)))
        conn.commit()

    wrong_ver_qual = VerifiedLiveQualification(
        provider="codex",
        provider_version="codex-app-server/0.171.0",
        runtime_kind=_runtime_kind(),
        mechanism="codex app-server --stdio",
        qualified=True,
    )
    res_wrong_ver = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            codex_home=codex_home,
            live_qualification=wrong_ver_qual,
            command_override=_py_server_cmd(server_script),
        )
    )
    assert res_wrong_ver.persisted is True
    assert res_wrong_ver.persistence_evidence["rollout_id_verified"] is True
    assert res_wrong_ver.persistence_evidence["state_db_cwd_verified"] is True
    assert res_wrong_ver.can_authorize_interactive_resume is False

    # 3. Matching bound qualification + verified persistence -> authorized
    res_ok = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            codex_home=codex_home,
            live_qualification=qual,
            command_override=_py_server_cmd(server_script),
        )
    )
    assert res_ok.can_authorize_interactive_resume is True


def test_agy_exact_metadata_and_claude_readiness(tmp_path: Path) -> None:
    agy_home = tmp_path / ".agy"
    (agy_home / "brain" / "agy-conv-acp-0001").mkdir(parents=True)
    server_script = (
        "import json, sys\n"
        "stage = 'init'\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if stage == 'init':\n"
        "        assert msg.get('method') == 'initialize'\n"
        "        stage = 'new'\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {\n"
        "            'protocolVersion': 1, 'agentInfo': {'name': 'agy', 'version': 'agy 1.5.18'}\n"
        "        }}), flush=True)\n"
        "    elif stage == 'new':\n"
        "        assert msg.get('method') == 'session/new' and msg['params']['cwd']\n"
        "        stage = 'done'\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'sessionId': 'agy-conv-acp-0001'}}), flush=True)\n"
    )
    qual = VerifiedLiveQualification(
        provider="agy",
        provider_version="agy 1.5.18",
        runtime_kind=_runtime_kind(),
        mechanism="agy acp --stdio",
        qualified=True,
    )

    # Bare directory without matching metadata file -> not persisted
    res_dir_only = allocate_native_session(
        NativeBootstrapRequest(
            provider="agy",
            cwd=str(tmp_path),
            agy_home=agy_home,
            live_qualification=qual,
            command_override=_py_server_cmd(server_script),
        )
    )
    assert res_dir_only.persistence_evidence["conversation_dir_exists"] is True
    assert res_dir_only.persistence_evidence["metadata_id_verified"] is False
    assert res_dir_only.persisted is False
    assert res_dir_only.can_authorize_interactive_resume is False

    # Matching session.json -> persisted + authorized under bound qualification
    (agy_home / "brain" / "agy-conv-acp-0001" / "session.json").write_text(
        json.dumps({"sessionId": "agy-conv-acp-0001"}), encoding="utf-8"
    )
    res_verified = allocate_native_session(
        NativeBootstrapRequest(
            provider="agy",
            cwd=str(tmp_path),
            agy_home=agy_home,
            live_qualification=qual,
            command_override=_py_server_cmd(server_script),
        )
    )
    assert res_verified.persisted is True
    assert res_verified.effective_provider_context["provider_version"] == "agy 1.5.18"
    assert res_verified.can_authorize_interactive_resume is True

    # ACP protocolVersion alone without installed/reported provider version -> never authorizes resume
    no_ver_script = (
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    res = {'protocolVersion': 1} if m['method'] == 'initialize' else {'sessionId': 'agy-conv-acp-0001'}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': res}), flush=True)\n"
    )
    res_proto_only = allocate_native_session(
        NativeBootstrapRequest(
            provider="agy",
            cwd=str(tmp_path),
            agy_home=agy_home,
            live_qualification=VerifiedLiveQualification(
                provider="agy",
                provider_version="acp-v1",
                runtime_kind=_runtime_kind(),
                mechanism="agy acp --stdio",
                qualified=True,
            ),
            command_override=_py_server_cmd(no_ver_script),
        )
    )
    assert res_proto_only.persisted is True
    assert res_proto_only.can_authorize_interactive_resume is False

    readiness = provider_native_bootstrap_readiness()
    assert readiness["claude"]["safe_to_enable_now"] is True
    assert readiness["codex"]["safe_to_enable_now"] is False
    assert readiness["agy"]["safe_to_enable_now"] is False


def test_saturated_stderr_stalled_stdin_descendant_pipes_and_bounds(tmp_path: Path) -> None:
    # 1. Saturated stderr (>300 KB with ANSI) + notification flood (>MAX_INTERNAL_QUEUE_ITEMS)
    flood_count = MAX_INTERNAL_QUEUE_ITEMS + 64
    noisy_script = (
        "import json, sys\n"
        "for i in range(4000):\n"
        "    sys.stderr.write(f'\\x1b[31mwarn-{i:04d} ' + ('x' * 80) + '\\n')\n"
        "sys.stderr.flush()\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    if m.get('method') == 'initialize':\n"
        f"        for n in range({flood_count}):\n"
        "            print(json.dumps({'jsonrpc': '2.0', 'method': 'n/tick', 'params': {'i': n}}), flush=True)\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {'protocolVersion': 1}}), flush=True)\n"
        "    elif m.get('method') == 'session/new':\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {'sessionId': 'agy-noisy-1'}}), flush=True)\n"
    )
    noisy_res = allocate_native_session(
        NativeBootstrapRequest(
            provider="agy",
            cwd=str(tmp_path),
            timeout_seconds=5.0,
            command_override=_py_server_cmd(noisy_script),
        )
    )
    assert noisy_res.status == NativeAllocationStatus.ALLOCATED
    assert len(noisy_res.notifications) == MAX_NOTIFICATIONS
    assert noisy_res.persistence_evidence["dropped_notifications"] == flood_count - MAX_NOTIFICATIONS
    assert len(noisy_res.persistence_evidence["stderr_tail"]) <= MAX_STDERR_LINES
    assert all("\x1b" not in line for line in noisy_res.persistence_evidence["stderr_tail"])

    # 2. Stalled stdin / unresponsive child respects bounded timeout
    t0 = time.monotonic()
    stalled = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            timeout_seconds=0.2,
            command_override=_py_server_cmd("import time; time.sleep(10)"),
        )
    )
    assert stalled.status == NativeAllocationStatus.TIMED_OUT
    assert (time.monotonic() - t0) < 3.0

    # 3. Descendant holding inherited stdout/stderr pipes does not hang transport cleanup
    descendant_script = (
        "import json, subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3)'])\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    res = {'protocolVersion': 1} if m['method'] == 'initialize' else {'sessionId': 'agy-desc-1'}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': res}), flush=True)\n"
    )
    t1 = time.monotonic()
    desc_res = allocate_native_session(
        NativeBootstrapRequest(
            provider="agy",
            cwd=str(tmp_path),
            timeout_seconds=3.0,
            command_override=_py_server_cmd(descendant_script),
        )
    )
    assert desc_res.status == NativeAllocationStatus.ALLOCATED
    assert (time.monotonic() - t1) < 2.0

    # 4. Oversized RPC frame rejected without unbounded buffering
    oversized_script = (
        "import sys; sys.stdin.readline(); "
        f"print('{{' + '\"x\":\"' + ('a' * ({MAX_RPC_FRAME_BYTES} + 100)) + '\"}}', flush=True)"
    )
    oversized = allocate_native_session(
        NativeBootstrapRequest(
            provider="agy",
            cwd=str(tmp_path),
            command_override=_py_server_cmd(oversized_script),
        )
    )
    assert oversized.status == NativeAllocationStatus.UNCERTAIN
    assert "Oversized JSON-RPC frame" in (oversized.error_message or "")


def test_context_validation_unclean_shutdown_cancel_and_concurrent_recovery(tmp_path: Path) -> None:
    # 1. Invalid cwd fails closed
    bad_cwd = allocate_native_session(
        NativeBootstrapRequest(provider="claude", cwd=str(tmp_path / "does-not-exist"))
    )
    assert bad_cwd.status == NativeAllocationStatus.FAILED

    # 2. Codex policy conflict (server broadens approvalPolicy) fails closed
    broadened_script = (
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    if m.get('method') == 'initialize':\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {'userAgent': 'codex'}}), flush=True)\n"
        "    elif m.get('method') == 'thread/start':\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {\n"
        "            'approvalPolicy': 'never', 'cwd': m['params']['cwd'],\n"
        "            'thread': {'id': 'thr-broad', 'ephemeral': False}\n"
        "        }}), flush=True)\n"
    )
    broad = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            expected_approval_policy="on-request",
            command_override=_py_server_cmd(broadened_script),
        )
    )
    assert broad.status == NativeAllocationStatus.FAILED
    assert broad.native_session_id is None

    # 2b. Missing expected permission evidence (omitted approvalPolicy/sandbox) fails closed
    missing_perm_script = (
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    if m.get('method') == 'initialize':\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {'userAgent': 'codex'}}), flush=True)\n"
        "    elif m.get('method') == 'thread/start':\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {\n"
        "            'cwd': m['params']['cwd'], 'thread': {'id': 'thr-noperm', 'ephemeral': False}\n"
        "        }}), flush=True)\n"
    )
    missing_perm = allocate_native_session(
        NativeBootstrapRequest(
            provider="codex",
            cwd=str(tmp_path),
            expected_approval_policy="on-request",
            command_override=_py_server_cmd(missing_perm_script),
        )
    )
    assert missing_perm.status == NativeAllocationStatus.FAILED
    assert missing_perm.native_session_id is None

    # 3. Non-zero exit on shutdown after returning ID -> UNCERTAIN with uncertain_native_session_id preserved
    dirty_exit_script = (
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    res = {'protocolVersion': 1} if m['method'] == 'initialize' else {'sessionId': 'agy-dirty-1'}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': res}), flush=True)\n"
        "sys.exit(3)\n"
    )
    dirty = allocate_native_session(
        NativeBootstrapRequest(
            provider="agy",
            cwd=str(tmp_path),
            command_override=_py_server_cmd(dirty_exit_script),
        )
    )
    assert dirty.status == NativeAllocationStatus.UNCERTAIN
    assert dirty.native_session_id is None
    assert dirty.fallback_prohibited is True
    assert dirty.persistence_evidence.get("uncertain_native_session_id") == "agy-dirty-1"
    assert dirty.persistence_evidence.get("helper_exit_code") == 3

    # 4. Cancel event aborts cleanly
    cancel_ev = threading.Event()
    timer = threading.Timer(0.1, cancel_ev.set)
    timer.start()
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
        timer.cancel()
    assert cancelled.status == NativeAllocationStatus.CANCELLED

    # 5. Concurrent independent allocations succeed after uncertain/cancelled attempts
    def _run_one(idx: int) -> tuple[str, str | None, str]:
        sid = f"agy-conc-{idx}"
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
        results = list(pool.map(_run_one, range(8)))
    for expected_sid, actual_sid, status in results:
        assert status == NativeAllocationStatus.ALLOCATED
        assert actual_sid == expected_sid
