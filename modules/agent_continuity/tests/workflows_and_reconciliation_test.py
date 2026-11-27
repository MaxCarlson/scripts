from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import build_parser, dispatch
from agent_continuity.errors import ContinuityError
from agent_continuity.workflows import (
    discover_workflow_resources,
    prepare_additive_workflow_init,
    reconcile_activity_and_associations,
    resolve_authoritative_runtime_identity,
    validate_addressed_handoff,
)


def test_llmd_list_orders_groups_and_agents_by_actual_activity_and_empty_last(tmp_path: Path) -> None:
    home = tmp_path / "registry"
    d = DispatcherService(home_dir=home)
    d.create_gui("EmptyGUI", apply=True)
    d.create_gui("OlderGUI", apply=True)
    d.create_slot(gui="OlderGUI", name="OldAgent", apply=True)
    d.attach_session(gui="OlderGUI", name="OldAgent", provider="codex", session_id="s-old", apply=True)
    d.create_gui("NewerGUI", apply=True)
    d.create_slot(gui="NewerGUI", name="FirstAgent", apply=True)
    d.attach_session(gui="NewerGUI", name="FirstAgent", provider="codex", session_id="s-1", apply=True)
    d.create_slot(gui="NewerGUI", name="LatestAgent", apply=True)
    d.attach_session(gui="NewerGUI", name="LatestAgent", provider="agy", session_id="s-2", apply=True)

    parser = build_parser()
    j_out = StringIO()
    assert dispatch(parser.parse_args(["-H", str(home), "list", "-j"]), parser,
                    input_stream=StringIO(), output_stream=j_out) == 0
    doc = json.loads(j_out.getvalue())
    assert [c["alias"] for c in doc["conversations"]] == ["NewerGUI", "OlderGUI", "EmptyGUI"]
    assert [s["name"] for s in doc["conversations"][0]["slots"]] == ["LatestAgent", "FirstAgent"]

    t_out = StringIO()
    assert dispatch(parser.parse_args(["-H", str(home), "list", "-c", "never"]), parser,
                    input_stream=StringIO(), output_stream=t_out) == 0
    text = t_out.getvalue()
    assert text.index("NewerGUI") < text.index("OlderGUI") < text.index("EmptyGUI")
    assert text.index("LatestAgent") < text.index("FirstAgent")


def test_managed_restoration_contracts_and_fail_closed_guards(tmp_path: Path) -> None:
    home = tmp_path / "registry"
    d = DispatcherService(home_dir=home)
    d.create_gui("G", apply=True)
    d.create_slot(gui="G", name="A", apply=True)
    d.attach_session(gui="G", name="A", provider="codex", session_id="s-1", apply=True)
    slot = d.get_slot(gui="G", name="A")
    assert d.slot_lock_path(slot["slot_id"]) == home / f"slot-{slot['slot_id']}.lock"

    env_id = slot["current"]["environment_id"]
    for stage in ("relay_spawned", "dispatcher_accepted", "provider_associated"):
        res = d.accept_managed_restoration(
            slot_id=slot["slot_id"], provider="codex", environment_id=env_id, session_id="s-1", stage=stage
        )
        assert res["stage"] == stage

    with pytest.raises(ContinuityError, match="stale or ambiguous"):
        d.accept_managed_restoration(
            slot_id=slot["slot_id"], provider="codex", environment_id=env_id, session_id="wrong", stage="dispatcher_accepted"
        )

    d.begin_launch(gui="G", name="A", provider="claude", apply=True)
    with pytest.raises(ContinuityError, match="pending launch"):
        d.accept_managed_restoration(
            slot_id=slot["slot_id"], provider="codex", environment_id=env_id, session_id="s-1", stage="dispatcher_accepted"
        )


def test_llmd_50_to_54_workflow_identity_handoff_and_reconciliation() -> None:
    bridge = SimpleNamespace(
        list_resources=lambda _p, _r: [
            {"resource_id": "wf.review", "revision": "1", "digest": "abc", "installed": True, "callable": True, "runtime_verified": True},
            {"resource_id": "wf.missing", "revision": "1", "digest": "def", "installed": False, "callable": False},
        ],
        read_resource=lambda _rid, _rev=None: None,
    )
    resources = discover_workflow_resources(bridge, provider="codex", runtime="windows", expected_digests={"wf.review": "abc"})
    assert [r.status for r in resources] == ["available", "missing"]

    init_new = prepare_additive_workflow_init(provider="codex", runtime="windows", is_new_session=True, resources=resources)
    assert init_new["applied"] is True and init_new["status"] == "degraded"
    assert init_new["provenance"] == [{"resource_id": "wf.review", "revision": "1", "digest": "abc", "status": "available"}]
    assert prepare_additive_workflow_init(provider="codex", runtime="windows", is_new_session=False, resources=resources)["applied"] is False

    ident = resolve_authoritative_runtime_identity(
        trusted_slot={"gui_alias": "G", "name": "Agent One", "slot_id": "slot_1"},
        trusted_observation={"conflict": False},
    )
    assert ident["authority"] == "managed"
    msg = "```markdown\nTo-Agent: Fake\n```\n> To-Agent: Quoted\nTo-Agent: Agent One\nProceed."
    assert validate_addressed_handoff(msg, authoritative_identity=ident)["valid"] is True
    assert validate_addressed_handoff("To-Agent: Other", authoritative_identity=ident)["outcome"] == "mismatch"

    rec = reconcile_activity_and_associations([
        {"event_id": "e2", "slot_id": "slot_1", "source_timestamp": "2026-11-27T10:00:02Z", "sequence": 2, "provider": "agy", "environment_id": "env1", "native_session_id": "new"},
        {"event_id": "e1", "slot_id": "slot_1", "source_timestamp": "2026-11-27T10:00:01Z", "sequence": 1, "provider": "codex", "environment_id": "env1", "native_session_id": "old"},
        {"event_id": "e2", "slot_id": "slot_1", "source_timestamp": "2026-11-27T10:00:02Z", "sequence": 2, "provider": "agy", "environment_id": "env1", "native_session_id": "new"},
    ])
    assert rec["selections"]["slot_1"]["native_session_id"] == "new"
    assert rec["duplicates_skipped"] == 1
