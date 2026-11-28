from __future__ import annotations

import hashlib
import json
import sys
from io import StringIO
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import build_parser, dispatch
from agent_continuity.errors import ContinuityError
from agent_continuity.runtime_discovery import ManagementState, MatchStatus, ProcessLiveness
from agent_continuity.workflows import (
    LocalAgentBridgeWorkflowAdapter,
    ResourceStatus,
    discover_workflow_resources,
    prepare_additive_workflow_init,
    reconcile_activity_and_associations,
    resolve_authoritative_runtime_identity,
    validate_addressed_handoff,
)


def test_workflow_resource_snapshot_deduplicates_common_and_preserves_exact_text() -> None:
    common = "  Common policy starts here.\n\nKeep trailing whitespace. \n"
    handoff = "Handoff-only instructions.\n"
    common_digest = hashlib.sha256(common.encode("utf-8")).hexdigest()
    handoff_digest = hashlib.sha256(handoff.encode("utf-8")).hexdigest()
    def resource(resource_id: str, content: str, digest: str) -> ResourceStatus:
        return ResourceStatus(
            resource_id=resource_id, revision=digest[:12], digest=digest, provider="codex",
            runtime="windows", status="available", installed=True, callable=True,
            runtime_verified=False, content=content,
        )

    prepared = prepare_additive_workflow_init(
        provider="codex", runtime="windows", is_new_session=True, selection="handoff",
        resources=(resource("workflow.common", common, common_digest),
                   resource("workflow.common", common, common_digest),
                   resource("workflow.handoff", handoff, handoff_digest)),
    )

    assert prepared["delivery_prompt"].count("[workflow.common@") == 1
    assert f"[workflow.common@{common_digest[:12]}]\n{common}" in prepared["delivery_prompt"]
    assert f"[workflow.handoff@{handoff_digest[:12]}]\n{handoff}" in prepared["delivery_prompt"]
    assert [item["resource_id"] for item in prepared["provenance"]] == [
        "workflow.common", "workflow.handoff",
    ]
    assert prepared["resource_snapshot"]["schema_version"] == 1
    assert [item["id"] for item in prepared["resource_snapshot"]["resources"]] == [
        "workflow.common", "workflow.handoff",
    ]


def test_conflicting_duplicate_resource_digests_are_excluded_but_other_resources_survive() -> None:
    def resource(resource_id: str, content: str) -> ResourceStatus:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return ResourceStatus(
            resource_id=resource_id, revision=digest[:12], digest=digest, provider="codex",
            runtime="windows", status="available", installed=True, callable=True,
            runtime_verified=False, content=content,
        )

    prepared = prepare_additive_workflow_init(
        provider="codex", runtime="windows", is_new_session=True, selection="hybrid",
        resources=(resource("workflow.common", "first common"),
                   resource("workflow.common", "conflicting common"),
                   resource("workflow.handoff", "handoff survives")),
    )

    assert prepared["status"] == "degraded"
    assert "first common" not in prepared["delivery_prompt"]
    assert "conflicting common" not in prepared["delivery_prompt"]
    assert "handoff survives" in prepared["delivery_prompt"]
    assert prepared["limitations"] == [{
        "resource_id": "workflow.common",
        "status": "conflicting",
        "detail": "duplicate resource identity has different content digests",
    }]


def test_local_agent_bridge_adapter_consumes_schema_v1_bundle_without_claiming_runtime_load(
    monkeypatch,
) -> None:
    content = "\n exact resolver text \n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    payload = {
        "schema_version": 1,
        "selection": "hybrid",
        "resources": [{"id": "workflow.common", "path": "instructions/common.md",
                       "sha256": digest, "content": content}],
    }
    package = ModuleType("local_agent_bridge")
    package.__path__ = []
    resolver = ModuleType("local_agent_bridge.workflow_resources")
    resolver.resolve_workflow_resources = lambda selection: {**payload, "selection": selection}
    monkeypatch.setitem(sys.modules, "local_agent_bridge", package)
    monkeypatch.setitem(sys.modules, "local_agent_bridge.workflow_resources", resolver)

    items = LocalAgentBridgeWorkflowAdapter().list_resources("codex", "windows", selection="hybrid")

    assert len(items) == 1
    assert items[0]["schema_version"] == 1
    assert items[0]["content"] == content
    assert items[0]["digest"] == digest
    assert items[0]["supported"] is True
    assert items[0]["runtime_verified"] is False


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
        list_resources=lambda _p, _r, *, selection="standard": [
            {"resource_id": "wf.review", "revision": "1", "digest": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae", "content": "foo", "installed": True, "callable": True, "runtime_verified": True},
            {"resource_id": "wf.missing", "revision": "1", "digest": "def", "installed": False, "callable": False},
        ],
        read_resource=lambda _rid, _rev=None, *, selection="standard": None,
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
    bridge = SimpleNamespace(
        list_resources=lambda _p, _r, *, selection="standard": [
            {"resource_id": "wf.init", "revision": "2", "digest": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae", "content": "foo", "installed": True, "callable": True, "runtime_verified": True}
        ],
        read_resource=lambda _rid, _rev=None, *, selection="standard": None,
    )
    d.workflow_bridge = bridge
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

    home = tmp_path / "registry"
    d = DispatcherService(home_dir=home)
    d.create_gui("SrcGUI", apply=True)
    d.create_gui("DstGUI", apply=True)
    d.create_slot(gui="SrcGUI", name="Worker One", apply=True)
    d.set_workflow_type(gui="SrcGUI", agent="Worker One", workflow_type="handoff", apply=True)
    selections: list[str] = []
    resource_content = " canonical workflow instructions \n"
    resource_digest = hashlib.sha256(resource_content.encode("utf-8")).hexdigest()
    bridge = SimpleNamespace(
        list_resources=lambda _p, _r, *, selection="standard": selections.append(selection) or [
            {
                "resource_id": "workflow.handoff",
                "revision": resource_digest[:12],
                "digest": resource_digest,
                "content": resource_content,
                "installed": True,
                "callable": True,
                "runtime_verified": False,
                "supported": True,
            }
        ],
        read_resource=lambda _rid, _rev=None, *, selection="standard": None,
    )
    d.workflow_bridge = bridge
    monkeypatch.setattr("agent_continuity.workflows.LocalAgentBridgeWorkflowAdapter", lambda: bridge)

    # 1) End-to-end new codex launch: delivers prepared workflow instructions in bootstrap_argv.
    monkeypatch.setattr(
        "agent_continuity.dispatcher_cli._native_argv",
        lambda _dispatcher, provider, *_args, **_kwargs: [provider],
    )
    captured_argvs: list[list[str]] = []

    def fake_bootstrap(argv, **_kw):
        captured_argvs.append(list(argv))
        if argv[0] == "agy":
            stdout = '{"conversation_id":"agy-new-2","status":"SUCCESS"}\n'
        else:
            stdout = '{"type":"thread.started","thread_id":"codex-new-1"}\n{"type":"turn.completed"}\n'
        return subprocess.CompletedProcess(
            argv, 0, stdout=stdout, stderr=""
        )

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_with_progress", fake_bootstrap)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", lambda argv, **_kw: captured_argvs.append(list(argv)) or subprocess.CompletedProcess(argv, 0))
    parser = build_parser()
    custom_file = tmp_path / "instructions.txt"
    custom_file.write_bytes(b"\nCustom instructions with exact edge whitespace. \n")
    custom_content = custom_file.read_bytes().decode("utf-8")
    assert dispatch(parser.parse_args([
        "-H", str(home), "start", "SrcGUI", "Worker One", "-p", "codex", "-N", "-a",
        "-W", "hybrid", "--instruction-file", str(custom_file),
    ]), parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert len(captured_argvs) == 2
    assert selections == ["hybrid"]
    assert resource_content in captured_argvs[0][-1]
    assert custom_content in captured_argvs[0][-1]
    assert "workflow." not in " ".join(captured_argvs[1])
    states = [
        json.loads(r["payload_json"]).get("delivery_state")
        for r in d._rows("SELECT payload_json FROM activity_events WHERE event_type = 'dispatcher.process_observed'")
        if json.loads(r["payload_json"]).get("delivery_state")
    ]
    assert states == ["prepared", "delivered"]
    delivered = [
        json.loads(r["payload_json"])
        for r in d._rows("SELECT payload_json FROM activity_events WHERE event_type = 'dispatcher.process_observed'")
        if json.loads(r["payload_json"]).get("delivery_state") == "delivered"
    ][0]
    assert delivered["native_session_id"] == "codex-new-1"
    assert delivered["resource_snapshot"] == {
        "schema_version": 1,
        "selection": "hybrid",
        "resources": [
            {"id": "workflow.handoff", "revision": resource_digest[:12], "sha256": resource_digest},
            {"id": f"custom:{custom_file.name}",
             "revision": hashlib.sha256(custom_content.encode("utf-8")).hexdigest()[:12],
             "sha256": hashlib.sha256(custom_content.encode("utf-8")).hexdigest()},
        ],
    }
    source_slot = d.get_slot(gui="SrcGUI", name="Worker One")
    portable_snapshot = d.get_portable_launch_context(
        slot_id=source_slot["slot_id"], provider="codex",
        environment_id=source_slot["current"]["environment_id"], session_id="codex-new-1",
    )
    assert portable_snapshot["workflow_resource_snapshot"] == delivered["resource_snapshot"]
    assert portable_snapshot["workflow_custom_instruction_path"] == str(custom_file)
    d.materializer.rebuild_from_spools()
    rebuilt_snapshot = d.get_portable_launch_context(
        slot_id=source_slot["slot_id"], provider="codex",
        environment_id=source_slot["current"]["environment_id"], session_id="codex-new-1",
    )
    assert rebuilt_snapshot["workflow_resource_snapshot"] == delivered["resource_snapshot"]
    assert rebuilt_snapshot["workflow_custom_instruction_path"] == str(custom_file)

    # A new cross-provider slot inherits the exact workflow selection and verifies the saved resource digest.
    second_launch = d.prepare_start(gui="SrcGUI", name="Worker Two", provider="agy", cwd=str(tmp_path), apply=True)
    from agent_continuity.dispatcher_cli import _run_pane

    try:
        run_result = _run_pane(
            d, slot_id=second_launch["details"]["slot_id"], launch_id=second_launch["details"]["launch_id"],
            input_stream=StringIO(), output_stream=StringIO(), show_summary=False,
            transition_source={"slot_id": source_slot["slot_id"],
                              "expected_source": ("codex", rebuilt_snapshot["runtime_identity"]["environment_id"],
                                                  "codex-new-1")},
        )
    except ContinuityError as exc:
        pytest.fail(f"cross-provider workflow restore failed: {exc}; detail={exc.detail}")
    assert run_result == 0
    assert selections == ["hybrid", "hybrid"]
    assert resource_content in " ".join(captured_argvs[-2])
    assert custom_content in " ".join(captured_argvs[-2])
    agy_slot = d.get_slot(gui="SrcGUI", name="Worker Two")
    agy_snapshot = d.get_portable_launch_context(
        slot_id=agy_slot["slot_id"], provider="agy", environment_id=agy_slot["current"]["environment_id"],
        session_id="agy-new-2",
    )
    assert agy_snapshot["workflow_resource_snapshot"] == delivered["resource_snapshot"]

    # Claude has no qualified additive workflow bootstrap; refuse without spawning it.
    d.create_gui("ClaudeGUI", apply=True)
    claude_launch = d.prepare_start(gui="ClaudeGUI", name="Reviewer", provider="claude", cwd=str(tmp_path), apply=True)
    guarded_invocations = len(captured_argvs)
    with pytest.raises(ContinuityError, match="cannot be delivered to claude"):
        _run_pane(
            d, slot_id=claude_launch["details"]["slot_id"], launch_id=claude_launch["details"]["launch_id"],
            input_stream=StringIO(), output_stream=StringIO(), show_summary=False,
            transition_source={
                "slot_id": agy_slot["slot_id"],
                "expected_source": ("agy", agy_slot["current"]["environment_id"], "agy-new-2"),
            },
        )
    assert len(captured_argvs) == guarded_invocations

    # Changed explicit instruction bytes block replacement before bootstrap or provider execution.
    custom_file.write_text("changed after the exact session snapshot\n", encoding="utf-8")
    third_launch = d.prepare_start(gui="SrcGUI", name="Worker Three", provider="codex", cwd=str(tmp_path), apply=True)
    guarded_invocations = len(captured_argvs)
    with pytest.raises(ContinuityError, match="Saved workflow resources changed"):
        _run_pane(
            d, slot_id=third_launch["details"]["slot_id"], launch_id=third_launch["details"]["launch_id"],
            input_stream=StringIO(), output_stream=StringIO(), show_summary=False,
            transition_source={
                "slot_id": agy_slot["slot_id"],
                "expected_source": ("agy", agy_slot["current"]["environment_id"], "agy-new-2"),
                "source_state": "inactive", "destination_state": "active", "provenance": "post_exit_new_agent",
            },
        )
    assert len(captured_argvs) == guarded_invocations

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
    assert d.get_slot(gui="SrcGUI", name="Worker One")["agent_number"] == 4
    d.create_slot(gui="DstGUI", name="Worker One", apply=True)
    with pytest.raises(ContinuityError, match="already has an agent"):
        dispatch(parser.parse_args(["-H", str(home), "transfer", "-g", "SrcGUI", "-n", "Worker One", "-t", "DstGUI", "-a"]), parser, input_stream=StringIO(), output_stream=StringIO())

    # 3) Read-only handoff-validate CLI fails closed when runtime observation is absent, succeeds when observed, and creates no locks.
    locks_dir = home / "locks"
    before_locks = set(locks_dir.iterdir()) if locks_dir.exists() else set()
    out = StringIO()
    rc = dispatch(parser.parse_args(["-H", str(home), "handoff-validate", "-g", "SrcGUI", "-n", "Worker One", "--text", "Agent: #4 — Worker One", "-j"]), parser, input_stream=StringIO(), output_stream=out)
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
    rc = dispatch(parser.parse_args(["-H", str(home), "handoff-validate", "-g", "SrcGUI", "-n", "Worker One", "--text", "Agent: #4 — Worker One", "-j"]), parser, input_stream=StringIO(), output_stream=out)
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
