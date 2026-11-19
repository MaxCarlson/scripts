"""Independent M2 review regression tests covering subprocess E2E, A->B->A repurposing, and rollback safety."""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_continuity.errors import ContinuityError, ErrorCode
from agent_continuity.installer import install_hooks, rollback_hooks
from agent_continuity.service import ContinuityService
from agent_continuity.shim import MAX_SHIM_STDIN_BYTES, process_hook_stdin

MODULE_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(home: Path, *args: str, stdin_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agent_continuity", "-H", str(home), *args],
        cwd=MODULE_ROOT,
        input=stdin_text,
        capture_output=True,
        text=True,
        check=False,
    )


def test_subprocess_e2e_hook_shim_find_and_rebuild_roundtrip(tmp_path: Path) -> None:
    home = tmp_path / "e2e_home"
    r_wf = _run_cli(home, "wf", "add", "-w", "alpha", "-t", "Alpha", "-a", "-j")
    assert r_wf.returncode == 0
    wf_id = json.loads(r_wf.stdout)["details"]["workflow_id"]

    # Codex startup -> tagged prompt -> Stop via real subprocesses
    for payload in (
        {"session_id": "sub-c1", "hook_event_name": "SessionStart", "source": "startup", "cwd": str(MODULE_ROOT)},
        {
            "session_id": "sub-c1",
            "hook_event_name": "UserPromptSubmit",
            "turn_id": "t-1",
            "prompt": f"Workflow-ID: {wf_id}\r\nUnicode check: café — ✓\r\n",
        },
        {"session_id": "sub-c1", "hook_event_name": "Stop", "turn_id": "t-1"},
    ):
        proc = _run_cli(home, "hook-shim", "-p", "codex", stdin_text=json.dumps(payload))
        assert proc.returncode == 0
        assert json.loads(proc.stdout) == {}

    # AGY PreInvocation (v1.2 minimal without hookEventName) + Stop
    for payload in (
        {"conversationId": "sub-a1", "invocationNum": 1, "lastUserInput": "Workflow-ID: alpha\nRun checks."},
        {"conversationId": "sub-a1", "hookEventName": "Stop", "terminationReason": "NO_TOOL_CALL"},
    ):
        proc = _run_cli(home, "hook-shim", "-p", "agy", stdin_text=json.dumps(payload))
        assert proc.returncode == 0
        assert json.loads(proc.stdout) == {}

    r_find1 = _run_cli(home, "find", "-w", "alpha", "-j")
    assert r_find1.returncode == 0
    before = json.loads(r_find1.stdout)
    assert len(before["sessions"]) == 2
    assert before["continuity"]["latest_validated_checkpoint"] is None

    # Rebuild SQLite from scratch and confirm identical query state
    (home / "index.sqlite").unlink()
    r_rb = _run_cli(home, "rebuild", "-a", "-j")
    assert r_rb.returncode == 0
    assert json.loads(r_rb.stdout)["issues"] == []

    r_find2 = _run_cli(home, "find", "-w", "alpha", "-j")
    assert r_find2.returncode == 0
    after = json.loads(r_find2.stdout)
    assert len(after["sessions"]) == 2
    assert {s["session"]["native_session_id"] for s in after["sessions"]} == {"sub-c1", "sub-a1"}


def test_a_to_b_to_a_repurposing_and_archived_workflow_guard(tmp_path: Path) -> None:
    home = tmp_path / "repurpose_home"
    svc = ContinuityService(home_dir=home)
    wf_a = svc.add_workflow(slug="wf-a", title="A", apply=True).details["workflow_id"]
    wf_b = svc.add_workflow(slug="wf-b", title="B", apply=True).details["workflow_id"]
    wf_arch = svc.add_workflow(slug="wf-arch", title="Archived", apply=True).details["workflow_id"]
    svc.archive_workflow(wf_arch, apply=True)

    # A -> B -> A turns on one session
    for tid, marker in (("t1", wf_a), ("t2", wf_b), ("t3", wf_a)):
        process_hook_stdin(
            "codex",
            raw_stdin=json.dumps(
                {
                    "session_id": "ses-aba",
                    "hook_event_name": "UserPromptSubmit",
                    "turn_id": tid,
                    "prompt": f"Workflow-ID: {marker}\nWork",
                }
            ),
            home_dir=home,
        )

    # Archived workflow marker must not link automatically
    process_hook_stdin(
        "codex",
        raw_stdin=json.dumps(
            {
                "session_id": "ses-arch",
                "hook_event_name": "UserPromptSubmit",
                "turn_id": "t-arch",
                "prompt": f"Workflow-ID: {wf_arch}\nShould not auto-link",
            }
        ),
        home_dir=home,
    )

    assert len(svc.find_sessions(workflow_identifier="wf-a")["sessions"]) == 1
    assert len(svc.find_sessions(workflow_identifier="wf-b")["sessions"]) == 0
    assert len(svc.find_sessions(workflow_identifier="wf-arch")["sessions"]) == 0

    with svc.materializer._connect_ro() as conn:  # type: ignore[union-attr]
        rows = conn.execute(
            "SELECT turn_id, workflow_id FROM turns WHERE native_session_id = 'ses-aba' ORDER BY started_at"
        ).fetchall()
        assert [(r["turn_id"], r["workflow_id"]) for r in rows] == [("t1", wf_a), ("t2", wf_b), ("t3", wf_a)]


def test_conflict_deduplication_and_oversized_stdin_fail_open(tmp_path: Path) -> None:
    home = tmp_path / "conflict_home"
    svc = ContinuityService(home_dir=home)
    wf_a = svc.add_workflow(slug="wf-a", title="A", apply=True).details["workflow_id"]
    wf_b = svc.add_workflow(slug="wf-b", title="B", apply=True).details["workflow_id"]
    svc.link_session(workflow_identifier=wf_a, provider="codex", native_session_id="ses-locked", apply=True)

    for i in range(2):
        process_hook_stdin(
            "codex",
            raw_stdin=json.dumps(
                {
                    "session_id": "ses-locked",
                    "hook_event_name": "UserPromptSubmit",
                    "turn_id": f"tc-{i}",
                    "prompt": f"Workflow-ID: {wf_b}\nAttempt {i}",
                }
            ),
            home_dir=home,
        )

    assert len(svc.list_inbox(workflow_identifier="wf-b")["conflict_associations"]) == 1

    # Oversized payload fails open with {} and does not record an event
    huge = "{" + (" " * (MAX_SHIM_STDIN_BYTES + 100)) + "}"
    resp, outcome = process_hook_stdin("codex", raw_stdin=huge, home_dir=home)
    assert resp == {}
    assert outcome.recorded is False


def test_concurrent_hook_shim_writers(tmp_path: Path) -> None:
    home = tmp_path / "conc_shim"

    def _fire(i: int) -> bool:
        resp, out = process_hook_stdin(
            "codex",
            raw_stdin=json.dumps({"session_id": f"s-{i}", "hook_event_name": "Stop"}),
            home_dir=home,
        )
        return resp == {} and out.recorded

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_fire, range(12)))
    assert all(results)

    svc = ContinuityService(home_dir=home)
    sync = svc.materializer.sync_from_spools()
    assert sync.issues == []
    assert len(svc.materializer.list_sessions()) == 12


def test_rollback_protects_post_backup_unrelated_changes_and_custom_command(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "hooks.json").write_text(json.dumps({"Stop": [{"type": "command", "command": "old"}]}), encoding="utf-8")

    # Verify custom -C/--command option works in install_hooks
    res = install_hooks("codex", config_dir=codex_dir, shim_command="custom-agents hook-shim -p codex", apply=True)
    installed = json.loads((codex_dir / "hooks.json").read_text(encoding="utf-8"))
    assert any(h.get("command") == "custom-agents hook-shim -p codex" for h in installed["UserPromptSubmit"])

    # Simulate user adding a newer unrelated hook after backup creation
    installed["Stop"].append({"type": "command", "command": "newer-user-hook"})
    (codex_dir / "hooks.json").write_text(json.dumps(installed), encoding="utf-8")

    with pytest.raises(ContinuityError) as exc_info:
        rollback_hooks("codex", config_dir=codex_dir, backup_path=res["backup_path"], apply=True)
    assert exc_info.value.code == ErrorCode.ASSOCIATION_CONFLICT

    # Force rollback overwrites when explicitly requested
    rb_force = rollback_hooks("codex", config_dir=codex_dir, backup_path=res["backup_path"], force=True, apply=True)
    assert rb_force["applied"] is True
    assert rb_force["forced"] is True

    # Missing backup raises METADATA_INACCESSIBLE
    with pytest.raises(ContinuityError) as exc_missing:
        rollback_hooks("agy", config_dir=tmp_path / "empty_cfg", apply=True)
    assert exc_missing.value.code == ErrorCode.METADATA_INACCESSIBLE


def test_16_independent_subprocesses_concurrent_init_materialize_and_rebuild(tmp_path: Path) -> None:
    for trial in range(2):
        home = tmp_path / f"mp_home_{trial}"

        def _invoke(i: int, target_home: Path = home, t: int = trial) -> subprocess.CompletedProcess[str]:
            payload = json.dumps({"session_id": f"mp-ses-{t}-{i}", "hook_event_name": "Stop"})
            return _run_cli(target_home, "hook-shim", "-p", "codex", stdin_text=payload)

        with ThreadPoolExecutor(max_workers=16) as pool:
            procs = list(pool.map(_invoke, range(16)))

        assert all(p.returncode == 0 and json.loads(p.stdout) == {} for p in procs)
        assert not (home / "environment.json.lock").exists()
        assert list(home.glob(".environment.*.tmp")) == []

        env_data = json.loads((home / "environment.json").read_text(encoding="utf-8"))
        persisted_env_id = env_data["environment_id"]
        spool_files = list((home / "events").rglob("*.json"))
        assert len(spool_files) == 16
        assert {json.loads(f.read_text(encoding="utf-8"))["environment_id"] for f in spool_files} == {persisted_env_id}

        # Stability across subsequent CLI invocation
        proc_next = _run_cli(
            home,
            "hook-shim",
            "-p",
            "agy",
            stdin_text=json.dumps({"conversationId": f"mp-agy-{trial}", "hookEventName": "Stop"}),
        )
        assert proc_next.returncode == 0
        assert json.loads((home / "environment.json").read_text(encoding="utf-8"))["environment_id"] == persisted_env_id

        # Materialize & rebuild verify all 17 sessions under one environment_id
        r_doc = _run_cli(home, "doctor", "-j")
        assert r_doc.returncode == 0
        svc = ContinuityService(home_dir=home)
        sync = svc.materializer.sync_from_spools()
        assert sync.issues == []
        sessions_before = {(s.provider, s.environment_id, s.native_session_id) for s in svc.materializer.list_sessions()}
        assert len(sessions_before) == 17
        assert {k[1] for k in sessions_before} == {persisted_env_id}

        (home / "index.sqlite").unlink()
        rb = svc.rebuild_index(apply=True)
        assert rb["issues"] == []
        sessions_after = {(s.provider, s.environment_id, s.native_session_id) for s in svc.materializer.list_sessions()}
        assert sessions_after == sessions_before


def test_subprocess_hook_failure_isolation_modes(tmp_path: Path) -> None:
    home = tmp_path / "fail_open_home"
    # 1. Malformed JSON, missing ID, oversized input -> exit 0 with {}
    for bad_in in (
        "{not-json",
        json.dumps({"hook_event_name": "Stop"}),
        "{" + (" " * (MAX_SHIM_STDIN_BYTES + 100)) + "}",
    ):
        proc = _run_cli(home, "hook-shim", "-p", "codex", stdin_text=bad_in)
        assert proc.returncode == 0
        assert json.loads(proc.stdout) == {}

    # 2. Inaccessible home_dir (regular file blocking directory creation) -> exit 0 with {}
    blocked_home = tmp_path / "file_not_dir"
    blocked_home.write_text("not a directory", encoding="utf-8")
    proc_blocked = _run_cli(
        blocked_home,
        "hook-shim",
        "-p",
        "agy",
        stdin_text=json.dumps({"conversationId": "c1", "hookEventName": "Stop"}),
    )
    assert proc_blocked.returncode == 0
    assert json.loads(proc_blocked.stdout) == {}
