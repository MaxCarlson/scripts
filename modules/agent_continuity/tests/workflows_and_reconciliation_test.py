from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import build_parser, dispatch
from agent_continuity.errors import ContinuityError
from agent_continuity.runtime_discovery import ManagementState, MatchStatus, ProcessLiveness
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
            {"resource_id": "wf.review", "revision": "1", "digest": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae", "content": "foo", "installed": True, "callable": True, "runtime_verified": True},
            {"resource_id": "wf.missing", "revision": "1", "digest": "def", "installed": False, "callable": False},
        ],
        read_resource=lambda _rid, _rev=None: None,
    )
    resources = discover_workflow_resources(bridge, provider="codex", runtime="windows", expected_digests={"wf.review": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae"})
    assert [r.status for r in resources] == ["available", "missing"]

    init_new = prepare_additive_workflow_init(provider="codex", runtime="windows", is_new_session=True, resources=resources)
    assert init_new["applied"] is True and init_new["status"] == "degraded"
    assert init_new["provenance"] == [
        {
            "resource_id": "wf.review",
            "revision": "1",
            "digest": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
            "status": "available",
            "selection": "standard",
            "integrity_verified": True,
            "installed": True,
            "callable": True,
        }
    ]
    assert prepare_additive_workflow_init(provider="codex", runtime="windows", is_new_session=False, resources=resources)["applied"] is False
    assert prepare_additive_workflow_init(provider="claude", runtime="windows", is_new_session=True, resources=resources)["status"] == "unsupported"

    # Slot metadata alone is insufficient for managed-runtime classification.
    unverified_ident = resolve_authoritative_runtime_identity(
        trusted_slot={"gui_alias": "G", "name": "Agent One - Review", "slot_id": "slot_1", "agent_number": 3},
        trusted_observation=None,
    )
    assert unverified_ident["authority"] == "unavailable"

    ident = resolve_authoritative_runtime_identity(
        trusted_slot={"gui_alias": "G", "name": "Agent One - Review", "slot_id": "slot_1", "agent_number": 3},
        trusted_observation={"conflict": False, "slot_id": "slot_1", "agent_number": 3},
    )
    assert ident["authority"] == "managed"
    msg = "```markdown\nTo-Agent: Fake\n```\n> Agent: #9 — Quoted\nAgent: #3 — Agent One - Review\nProceed."
    assert validate_addressed_handoff(msg, authoritative_identity=ident)["valid"] is True
    assert validate_addressed_handoff("Agent: #4 — Agent One - Review", authoritative_identity=ident)["outcome"] == "mismatch"
    assert validate_addressed_handoff("To-Agent: Other", authoritative_identity=ident)["outcome"] == "mismatch"
    # Fail closed when numbered recipient identity cannot be verified against a known agent_number.
    no_num_ident = {**ident, "agent_number": None}
    assert validate_addressed_handoff("Agent: #3 — Agent One - Review", authoritative_identity=no_num_ident)["outcome"] == "unverified_number"

    rec = reconcile_activity_and_associations([
        {"event_id": "e2", "slot_id": "slot_1", "source_timestamp": "2026-11-27T10:00:02Z", "sequence": 2, "provider": "agy", "environment_id": "env1", "native_session_id": "new"},
        {"event_id": "e1", "slot_id": "slot_1", "source_timestamp": "2026-11-27T10:00:01Z", "sequence": 1, "provider": "codex", "environment_id": "env1", "native_session_id": "old"},
        {"event_id": "e2", "slot_id": "slot_1", "source_timestamp": "2026-11-27T10:00:02Z", "sequence": 2, "provider": "agy", "environment_id": "env1", "native_session_id": "new"},
    ])
    assert rec["selections"]["slot_1"]["native_session_id"] == "new"
    assert rec["duplicates_skipped"] == 1


def test_atomic_slot_transfer_preserves_identity_history_and_monotonic_numbers(tmp_path: Path) -> None:
    home = tmp_path / "registry"
    d = DispatcherService(home_dir=home)
    d.create_gui("SourceGUI", apply=True)
    d.create_gui("DestGUI", apply=True)
    d.create_slot(gui="SourceGUI", name="Worker", apply=True)
    d.attach_session(gui="SourceGUI", name="Worker", provider="codex", session_id="sess-1", apply=True)
    d.set_workflow_type(gui="SourceGUI", agent="Worker", workflow_type="handoff", apply=True)
    before = d.get_slot(gui="SourceGUI", name="Worker")
    src_num = before["agent_number"]

    transferred = d.transfer_slot(gui="SourceGUI", name="Worker", destination_gui="DestGUI", apply=True)
    assert transferred["details"]["destination_agent_number"] == 1
    moved = d.get_slot(gui="DestGUI", name="Worker")
    assert moved["slot_id"] == before["slot_id"]
    assert moved["current"]["native_session_id"] == "sess-1"
    assert moved["workflow_type"] == "handoff"

    # Transfer back allocates a new monotonic number in SourceGUI without reusing src_num.
    d.transfer_slot(gui="DestGUI", name="Worker", destination_gui="SourceGUI", apply=True)
    returned = d.get_slot(gui="SourceGUI", name="Worker")
    assert returned["agent_number"] > src_num

    d.materializer.rebuild_from_spools()
    assert d.get_slot(gui="SourceGUI", name="Worker")["agent_number"] == returned["agent_number"]


def test_dispatcher_workflow_init_and_pane_run_expected_identity_guard(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "registry"
    d = DispatcherService(home_dir=home)
    d.workflow_bridge = SimpleNamespace(
        list_resources=lambda _p, _r: [
            {"resource_id": "wf.init", "revision": "2", "digest": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae", "content": "foo", "installed": True, "callable": True, "runtime_verified": True}
        ],
        read_resource=lambda _rid, _rev=None: None,
    )
    d.create_gui("G", apply=True)
    d.create_slot(gui="G", name="A", apply=True)
    d.set_workflow_type(gui="G", agent="A", workflow_type="standard", apply=True)
    launch = d.prepare_start(gui="G", name="A", provider="codex", apply=True)
    prep = d.prepare_new_session_workflow(
        slot_id=launch["details"]["slot_id"],
        launch_id=launch["details"]["launch_id"],
        provider="codex",
        environment_id=launch["details"]["environment_id"],
        bridge=d.workflow_bridge,
    )
    assert prep["applied"] is True
    d.confirm_workflow_init_delivered(
        slot_id=launch["details"]["slot_id"],
        launch_id=launch["details"]["launch_id"],
        provider="codex",
        environment_id=launch["details"]["environment_id"],
        session_id="exact-1",
        provenance=prep["provenance"],
    )
    outcomes = [
        json.loads(r["payload_json"]).get("delivery_state")
        for r in d._rows("SELECT payload_json FROM activity_events WHERE event_type = 'dispatcher.process_observed'")
    ]
    assert outcomes == ["prepared", "delivered"]

    d.attach_session(
        gui="G", name="A", provider="codex", session_id="exact-1",
        environment_selector=launch["details"]["environment_id"], launch_id=launch["details"]["launch_id"], apply=True,
    )
    parser = build_parser()
    slot = d.get_slot(gui="G", name="A")
    with pytest.raises(ContinuityError, match="selection changed"):
        dispatch(
            parser.parse_args([
                "-H", str(home), "pane-run", "-s", slot["slot_id"],
                "--expected-provider", "codex",
                "--expected-environment", slot["current"]["environment_id"],
                "--expected-session-id", "stale-id",
            ]),
            parser, input_stream=StringIO(), output_stream=StringIO(),
        )


def test_end_to_end_workflow_delivery_transfer_handoff_and_reconcile_cli(tmp_path: Path, monkeypatch) -> None:
    import subprocess
    from pathlib import Path as _Path

    toolkit_bridge = _Path(r"C:\Users\mcarls\src\llm-agent-toolkit\modules\local_agent_bridge")
    if toolkit_bridge.is_dir():
        monkeypatch.syspath_prepend(str(toolkit_bridge))

    home = tmp_path / "registry"
    d = DispatcherService(home_dir=home)
    d.create_gui("SrcGUI", apply=True)
    d.create_gui("DstGUI", apply=True)
    d.create_slot(gui="SrcGUI", name="Worker One", apply=True)
    d.set_workflow_type(gui="SrcGUI", agent="Worker One", workflow_type="handoff", apply=True)
    if not toolkit_bridge.is_dir():
        d.workflow_bridge = SimpleNamespace(
            list_resources=lambda _p, _r, selection="standard": [
                {
                    "resource_id": "workflow.handoff",
                    "revision": "rev1",
                    "digest": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
                    "content": "foo",
                    "installed": True,
                    "callable": True,
                    "runtime_verified": True,
                    "supported": True,
                }
            ]
        )

    # 1) End-to-end new codex launch: delivers prepared workflow instructions in bootstrap_argv.
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *_a, **_kw: ["codex"])
    captured_argvs: list[list[str]] = []

    def fake_bootstrap(argv, **_kw):
        captured_argvs.append(list(argv))
        return subprocess.CompletedProcess(
            argv, 0, stdout='{"type":"thread.started","thread_id":"codex-new-1"}\n{"type":"turn.completed"}\n', stderr=""
        )

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_with_progress", fake_bootstrap)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", lambda argv, **_kw: captured_argvs.append(list(argv)) or subprocess.CompletedProcess(argv, 0))
    parser = build_parser()
    assert dispatch(parser.parse_args(["-H", str(home), "start", "SrcGUI", "Worker One", "-p", "codex", "-N", "-a"]), parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert len(captured_argvs) == 2
    assert "workflow." in captured_argvs[0][-1]
    assert "workflow." not in " ".join(captured_argvs[1])
    states = [
        json.loads(r["payload_json"]).get("delivery_state")
        for r in d._rows("SELECT payload_json FROM activity_events WHERE event_type = 'dispatcher.process_observed'")
        if json.loads(r["payload_json"]).get("delivery_state")
    ]
    assert states == ["prepared", "delivered"]

    # 2) CLI transfer preview, apply, collision, and transfer-back without number reuse.
    out = StringIO()
    assert dispatch(parser.parse_args(["-H", str(home), "transfer", "-g", "SrcGUI", "-n", "Worker One", "-t", "DstGUI", "-d", "-j"]), parser, input_stream=StringIO(), output_stream=out) == 0
    assert json.loads(out.getvalue())["applied"] is False
    assert d.get_slot(gui="SrcGUI", name="Worker One")["agent_number"] == 1

    out = StringIO()
    assert dispatch(parser.parse_args(["-H", str(home), "transfer", "-g", "SrcGUI", "-n", "Worker One", "-t", "DstGUI", "-a", "-j"]), parser, input_stream=StringIO(), output_stream=out) == 0
    assert json.loads(out.getvalue())["applied"] is True
    assert d.get_slot(gui="DstGUI", name="Worker One")["agent_number"] == 1

    assert dispatch(parser.parse_args(["-H", str(home), "transfer", "-g", "DstGUI", "-n", "Worker One", "-t", "SrcGUI", "-a"]), parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert d.get_slot(gui="SrcGUI", name="Worker One")["agent_number"] == 2
    d.create_slot(gui="DstGUI", name="Worker One", apply=True)
    with pytest.raises(ContinuityError, match="already has an agent"):
        dispatch(parser.parse_args(["-H", str(home), "transfer", "-g", "SrcGUI", "-n", "Worker One", "-t", "DstGUI", "-a"]), parser, input_stream=StringIO(), output_stream=StringIO())

    # 3) Read-only handoff-validate CLI fails closed when runtime observation is absent, succeeds when observed, and creates no locks.
    locks_dir = home / "locks"
    before_locks = set(locks_dir.iterdir()) if locks_dir.exists() else set()
    out = StringIO()
    rc = dispatch(parser.parse_args(["-H", str(home), "handoff-validate", "-g", "SrcGUI", "-n", "Worker One", "--text", "Agent: #2 — Worker One", "-j"]), parser, input_stream=StringIO(), output_stream=out)
    assert rc == 2
    assert json.loads(out.getvalue())["identity"]["authority"] == "unavailable"
    monkeypatch.setattr(
        DispatcherService,
        "observe_runtime_session",
        lambda *_a, **_kw: SimpleNamespace(
            management=ManagementState.MANAGED,
            process_liveness=ProcessLiveness.RUNNING,
            process_session_match=MatchStatus.EXACT,
            pids=(4242,),
        ),
    )
    out = StringIO()
    rc = dispatch(parser.parse_args(["-H", str(home), "handoff-validate", "-g", "SrcGUI", "-n", "Worker One", "--text", "Agent: #2 — Worker One", "-j"]), parser, input_stream=StringIO(), output_stream=out)
    assert rc == 0
    assert json.loads(out.getvalue())["identity"]["authority"] == "managed"
    after_locks = set(locks_dir.iterdir()) if locks_dir.exists() else set()
    assert after_locks == before_locks

    # 4) Reconcile CLI replays persisted events without overwriting current selection with late observation.
    slot = d.get_slot(gui="SrcGUI", name="Worker One")
    rec = d.reconcile_late_activity(
        slot_id=slot["slot_id"],
        observed_events=[{"event_id": "late-1", "slot_id": slot["slot_id"], "source_timestamp": "2020-01-01T00:00:00Z", "sequence": 1, "provider": "agy", "environment_id": slot["current"]["environment_id"], "native_session_id": "stale-old"}],
    )
    assert rec["selected_session_preserved"] is True and rec["replaced"] is False
    out = StringIO()
    assert dispatch(parser.parse_args(["-H", str(home), "reconcile", "--slot-id", slot["slot_id"], "-j"]), parser, input_stream=StringIO(), output_stream=out) == 0
    assert json.loads(out.getvalue())["selected_session_preserved"] is True
