"""Tests for Phase 2 automatic association, lineage, repurposing, and native discovery."""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

from agent_continuity.cli import main
from agent_continuity.models import AssociationStatus
from agent_continuity.providers.agy import AgyAdapter
from agent_continuity.providers.codex import CodexAdapter
from agent_continuity.service import ContinuityService
from agent_continuity.shim import run_hook_shim


def test_automatic_marker_association_and_untagged_continuation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    svc = ContinuityService(home_dir=home)
    wf_id = svc.add_workflow(slug="procwatch", title="ProcWatch", apply=True).details["workflow_id"]

    # 1. Codex SessionStart (startup)
    assert (
        run_hook_shim(
            "codex",
            stdin_stream=io.StringIO(
                json.dumps(
                    {
                        "session_id": "codex-ses-1",
                        "hook_event_name": "SessionStart",
                        "source": "startup",
                        "cwd": r"C:\Users\mcarls\src\scripts",
                    }
                )
            ),
            stdout_stream=io.StringIO(),
            home_dir=home,
        )
        == 0
    )

    # 2. Codex UserPromptSubmit with Workflow-ID marker
    assert (
        run_hook_shim(
            "codex",
            stdin_stream=io.StringIO(
                json.dumps(
                    {
                        "session_id": "codex-ses-1",
                        "hook_event_name": "UserPromptSubmit",
                        "turn_id": "turn-1",
                        "cwd": r"C:\Users\mcarls\src\scripts",
                        "prompt": f"Workflow-ID: {wf_id}\n\nBuild feature.",
                    }
                )
            ),
            stdout_stream=io.StringIO(),
            home_dir=home,
        )
        == 0
    )

    # 3. Native resume + untagged follow-up turn inherits unambiguous association
    assert (
        run_hook_shim(
            "codex",
            stdin_stream=io.StringIO(
                json.dumps(
                    {
                        "session_id": "codex-ses-1",
                        "hook_event_name": "SessionStart",
                        "source": "resume",
                        "cwd": r"C:\Users\mcarls\src\scripts",
                    }
                )
            ),
            stdout_stream=io.StringIO(),
            home_dir=home,
        )
        == 0
    )
    assert (
        run_hook_shim(
            "codex",
            stdin_stream=io.StringIO(
                json.dumps(
                    {
                        "session_id": "codex-ses-1",
                        "hook_event_name": "UserPromptSubmit",
                        "turn_id": "turn-2",
                        "prompt": "Now run the tests.",
                    }
                )
            ),
            stdout_stream=io.StringIO(),
            home_dir=home,
        )
        == 0
    )
    assert (
        run_hook_shim(
            "codex",
            stdin_stream=io.StringIO(
                json.dumps(
                    {
                        "session_id": "codex-ses-1",
                        "hook_event_name": "Stop",
                        "turn_id": "turn-2",
                    }
                )
            ),
            stdout_stream=io.StringIO(),
            home_dir=home,
        )
        == 0
    )

    found = svc.find_sessions(workflow_identifier="procwatch")
    assert len(found["sessions"]) == 1
    item = found["sessions"][0]
    assert item["association"]["evidence_level"] == "strong"
    assert item["session"]["created_at"] is not None
    assert item["session"]["last_turn_at"] is not None
    assert item["session"]["last_completed_turn_at"] is not None
    assert found["continuity"]["latest_validated_checkpoint"] is None

    # Verify turns table recorded both tagged and inherited turns
    with svc.materializer._connect_ro() as conn:  # type: ignore[union-attr]
        turns = conn.execute("SELECT turn_id, workflow_id, completed_at FROM turns ORDER BY started_at").fetchall()
        assert len(turns) == 2
        assert turns[0]["workflow_id"] == wf_id
        assert turns[1]["workflow_id"] == wf_id
        assert turns[1]["completed_at"] is not None


def test_session_repurposing_and_manual_confirmation_precedence(tmp_path: Path) -> None:
    home = tmp_path / "home"
    svc = ContinuityService(home_dir=home)
    wf_a = svc.add_workflow(slug="wf-a", title="Workflow A", apply=True).details["workflow_id"]
    wf_b = svc.add_workflow(slug="wf-b", title="Workflow B", apply=True).details["workflow_id"]

    # Case 1: AGY hook-derived strong association repurposed to wf_b
    run_hook_shim(
        "agy",
        stdin_stream=io.StringIO(
            json.dumps(
                {
                    "conversationId": "agy-conv-1",
                    "hookEventName": "PreInvocation",
                    "invocationNum": 1,
                    "lastUserInput": f"Workflow-ID: {wf_a}\nTask A",
                }
            )
        ),
        stdout_stream=io.StringIO(),
        home_dir=home,
    )
    run_hook_shim(
        "agy",
        stdin_stream=io.StringIO(
            json.dumps(
                {
                    "conversationId": "agy-conv-1",
                    "hookEventName": "PreInvocation",
                    "invocationNum": 2,
                    "lastUserInput": f"Workflow-ID: {wf_b}\nSwitch to Task B",
                }
            )
        ),
        stdout_stream=io.StringIO(),
        home_dir=home,
    )

    assert len(svc.find_sessions(workflow_identifier="wf-a")["sessions"]) == 0
    assert len(svc.find_sessions(workflow_identifier="wf-b")["sessions"]) == 1
    assocs = svc.materializer.list_associations(provider="agy", native_session_id="agy-conv-1")
    by_wf = {a.workflow_id: a.status for a in assocs}
    assert by_wf[wf_a] == AssociationStatus.SUPERSEDED.value
    assert by_wf[wf_b] == AssociationStatus.ACTIVE.value

    # Case 2: Manually confirmed session receives conflicting hook marker -> confirmed preserved, conflict flagged
    svc.link_session(
        workflow_identifier=wf_a,
        provider="codex",
        native_session_id="codex-manual",
        apply=True,
    )
    run_hook_shim(
        "codex",
        stdin_stream=io.StringIO(
            json.dumps(
                {
                    "session_id": "codex-manual",
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": f"Workflow-ID: {wf_b}\nAttempt switch",
                }
            )
        ),
        stdout_stream=io.StringIO(),
        home_dir=home,
    )
    assert len(svc.find_sessions(workflow_identifier="wf-a")["sessions"]) == 1
    assert len(svc.find_sessions(workflow_identifier="wf-b")["sessions"]) == 0
    assert len(svc.list_inbox(workflow_identifier="wf-b")["conflict_associations"]) == 1


def test_native_read_only_discovery_codex_and_agy(tmp_path: Path, capsys) -> None:
    fake_user_home = tmp_path / "user_home"
    codex_dir = fake_user_home / ".codex"
    codex_dir.mkdir(parents=True)
    with sqlite3.connect(str(codex_dir / "state_5.sqlite")) as c:
        c.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                cli_version TEXT NOT NULL DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0,
                attached_thread_parent_id TEXT
            )
            """
        )
        c.execute(
            "INSERT INTO threads VALUES ('codex-hist-1', 'C:\\repo', 'Fix bug', 1700000000, 1700001000, '0.170.0', 0, NULL)"
        )

    agy_dir = fake_user_home / ".gemini" / "antigravity-cli"
    agy_dir.mkdir(parents=True)
    with sqlite3.connect(str(agy_dir / "conversation_summaries.db")) as c:
        c.execute(
            """
            CREATE TABLE conversation_summaries (
                conversation_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                workspace_uris TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT '',
                parent_conversation_id TEXT NOT NULL DEFAULT '',
                last_modified_time TEXT NOT NULL DEFAULT '',
                last_user_input_time TEXT NOT NULL DEFAULT ''
            )
            """
        )
        c.execute(
            """
            INSERT INTO conversation_summaries VALUES (
                'agy-hist-1', 'Plan M2', '["file:///C:/repo"]', 'idle', '', '2026-11-19T09:00:00Z', '2026-11-19T08:59:00Z'
            )
            """
        )

    adapters = {
        "codex": CodexAdapter(home_dir=fake_user_home),
        "agy": AgyAdapter(home_dir=fake_user_home),
    }
    state_home = tmp_path / "state"
    svc = ContinuityService(home_dir=state_home, adapters=adapters)

    dry = svc.discover_native_sessions(apply=False)
    assert dry["discovered_count"] == 2
    assert dry["new_sessions_count"] == 2
    assert svc.materializer.list_sessions() == []

    applied = svc.discover_native_sessions(apply=True)
    assert applied["applied"] is True
    assert len(svc.materializer.list_sessions()) == 2
    assert len(svc.list_inbox()["unlinked_sessions"]) == 2

    # CLI discover dry-run works cleanly
    rc = main(["-H", str(state_home), "discover", "-j"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
