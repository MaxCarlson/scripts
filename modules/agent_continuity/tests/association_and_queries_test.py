"""Tests for Scenarios A, B, C, G and continuity pointer semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_continuity.errors import ContinuityError, ErrorCode
from agent_continuity.events import append_event
from agent_continuity.models import EventEnvelope, EventType
from agent_continuity.service import ContinuityService


def test_scenario_a_shared_repository_never_mixes_workflows(tmp_path: Path) -> None:
    svc = ContinuityService(home_dir=tmp_path / "state")
    shared_repo = r"C:\Users\mcarls\src\scripts"
    svc.add_workflow(slug="wf-one", title="Workflow One", repo_paths=[shared_repo], apply=True)
    svc.add_workflow(slug="wf-two", title="Workflow Two", repo_paths=[shared_repo], apply=True)

    svc.link_session(
        workflow_identifier="wf-one",
        provider="codex",
        native_session_id="ses-one",
        environment_selector="windows",
        cwd=shared_repo,
        apply=True,
    )
    svc.link_session(
        workflow_identifier="wf-two",
        provider="codex",
        native_session_id="ses-two",
        environment_selector="windows",
        cwd=shared_repo,
        apply=True,
    )

    res1 = svc.find_sessions(workflow_identifier="wf-one")
    res2 = svc.find_sessions(workflow_identifier="wf-two")
    assert [s["session"]["native_session_id"] for s in res1["sessions"]] == ["ses-one"]
    assert [s["session"]["native_session_id"] for s in res2["sessions"]] == ["ses-two"]


def test_scenario_b_and_c_multi_provider_and_cross_env_distinct_keys(tmp_path: Path) -> None:
    svc = ContinuityService(home_dir=tmp_path / "state")
    svc.add_workflow(slug="procwatch", title="ProcWatch", apply=True)

    # Identical native_session_id across different providers and environments
    shared_id = "019a0000-0000-7000-8000-000000000001"
    svc.link_session(
        workflow_identifier="procwatch",
        provider="codex",
        native_session_id=shared_id,
        environment_selector="windows",
        apply=True,
    )
    svc.link_session(
        workflow_identifier="procwatch",
        provider="codex",
        native_session_id=shared_id,
        environment_selector="wsl:Ubuntu",
        apply=True,
    )
    svc.link_session(
        workflow_identifier="procwatch",
        provider="agy",
        native_session_id=shared_id,
        environment_selector="windows",
        apply=True,
    )

    found = svc.find_sessions(workflow_identifier="procwatch")
    keys = {
        (s["session"]["provider"], s["session"]["environment_id"], s["session"]["native_session_id"])
        for s in found["sessions"]
    }
    assert len(keys) == 3
    assert set(found["continuity"]["latest_by_provider"].keys()) == {"agy", "codex"}


def test_scenario_g_conflict_detection_candidate_and_supersede(tmp_path: Path) -> None:
    svc = ContinuityService(home_dir=tmp_path / "state")
    wf_a = svc.add_workflow(slug="wf-a", title="Workflow A", apply=True).details["workflow_id"]
    wf_b = svc.add_workflow(slug="wf-b", title="Workflow B", apply=True).details["workflow_id"]

    svc.link_session(
        workflow_identifier=wf_a,
        provider="codex",
        native_session_id="ses-shared",
        environment_selector="windows",
        apply=True,
    )

    # Attempting confirmed link to wf-b without --supersede must fail with association_conflict
    with pytest.raises(ContinuityError) as exc_info:
        svc.link_session(
            workflow_identifier=wf_b,
            provider="codex",
            native_session_id="ses-shared",
            environment_selector="windows",
            apply=True,
        )
    assert exc_info.value.code == ErrorCode.ASSOCIATION_CONFLICT

    # Candidate link to wf-b flags conflict in inbox without overwriting wf-a
    cand = svc.link_session(
        workflow_identifier=wf_b,
        provider="codex",
        native_session_id="ses-shared",
        environment_selector="windows",
        evidence_level="candidate",
        note="Possible reuse",
        apply=True,
    )
    assert cand.details["status"] == "conflict"
    assert len(svc.find_sessions(workflow_identifier=wf_a)["sessions"]) == 1
    assert len(svc.find_sessions(workflow_identifier=wf_b)["sessions"]) == 0
    assert len(svc.list_inbox(workflow_identifier=wf_b)["conflict_associations"]) == 1

    # Explicit supersede transitions active ownership cleanly while preserving history
    svc.link_session(
        workflow_identifier=wf_b,
        provider="codex",
        native_session_id="ses-shared",
        environment_selector="windows",
        supersede=True,
        apply=True,
    )
    assert len(svc.find_sessions(workflow_identifier=wf_a)["sessions"]) == 0
    assert len(svc.find_sessions(workflow_identifier=wf_b)["sessions"]) == 1

    all_assocs = svc.materializer.list_associations(provider="codex", native_session_id="ses-shared")
    statuses = {(a.workflow_id, a.status) for a in all_assocs}
    assert (wf_a, "superseded") in statuses
    assert (wf_b, "active") in statuses


def test_continuity_pointers_distinguish_seen_turn_and_completed_turn(tmp_path: Path) -> None:
    home = tmp_path / "state"
    svc = ContinuityService(home_dir=home)
    wf_id = svc.add_workflow(slug="pointers", title="Pointers", apply=True).details["workflow_id"]

    link1 = svc.link_session(
        workflow_identifier=wf_id,
        provider="codex",
        native_session_id="c-older-completed",
        environment_selector="windows",
        apply=True,
    )
    env_id = link1.details["environment_id"]
    svc.link_session(
        workflow_identifier=wf_id,
        provider="agy",
        native_session_id="a-newer-seen-only",
        environment_selector=env_id,
        apply=True,
    )

    # Emit observed events with distinct turn/seen/completed timestamps newer than registration
    append_event(
        home,
        EventEnvelope(
            event_id="evt_c_turn",
            event_schema_version=1,
            event_type=EventType.SESSION_OBSERVED.value,
            provider="codex",
            environment_id=env_id,
            native_session_id="c-older-completed",
            source_timestamp="2099-01-01T08:00:00Z",
            observed_timestamp="2099-01-01T08:00:01Z",
            source_adapter_version="0.1.0",
            payload={
                "native_created_at": "2026-11-19T07:50:00Z",
                "last_seen_at": "2099-01-01T08:00:00Z",
                "last_turn_at": "2099-01-01T08:00:00Z",
                "last_completed_turn_at": "2099-01-01T08:01:00Z",
            },
        ),
    )
    append_event(
        home,
        EventEnvelope(
            event_id="evt_a_seen",
            event_schema_version=1,
            event_type=EventType.SESSION_OBSERVED.value,
            provider="agy",
            environment_id=env_id,
            native_session_id="a-newer-seen-only",
            source_timestamp="2099-01-01T09:00:00Z",
            observed_timestamp="2099-01-01T09:00:01Z",
            source_adapter_version="0.1.0",
            payload={
                "last_seen_at": "2099-01-01T09:00:00Z",
            },
        ),
    )

    res = svc.find_sessions(workflow_identifier=wf_id)
    cont = res["continuity"]
    assert cont["latest_seen"]["native_session_id"] == "a-newer-seen-only"
    assert cont["latest_turn"]["native_session_id"] == "c-older-completed"
    assert cont["latest_completed_turn"]["native_session_id"] == "c-older-completed"
    assert cont["latest_created"]["native_session_id"] == "c-older-completed"
