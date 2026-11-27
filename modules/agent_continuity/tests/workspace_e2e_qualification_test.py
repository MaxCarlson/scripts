"""End-to-end offline qualification for LLMD-26/40/41/42/43/44/45 adapters and CLI handlers."""

from __future__ import annotations

import argparse
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from terminal_launcher.backend import LaunchResult, LaunchStatus, TerminalLaunchPlan
from terminal_launcher.managed import (
    LaunchSubmissionState,
    ManagedPaneReservation,
    ManagedProcessStore,
)
from terminal_launcher.managed import (
    ProcessLiveness as TLProcessLiveness,
)

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.runtime_discovery import (
    EvidenceAvailability,
    ProcessInventory,
    ProcessRecord,
    RuntimeDiscovery,
    process_identity_from_windows_filetime,
)
from agent_continuity.workspace_adapters import (
    DispatcherSlotExecutionGuard,
    DispatcherWorkspaceAdapter,
    TerminalLauncherRestoreAdapter,
)
from agent_continuity.workspace_checkpoint import (
    CheckpointStore,
    WorkspaceSlotInput,
)
from agent_continuity.workspace_cli import (
    handle_checkpoints,
    handle_queue,
    handle_restore,
    handle_save,
    register_workspace_subcommands,
)
from agent_continuity.workspace_lifecycle import TopologyRestorer


class _StaticEnumerator:
    def __init__(self, records: tuple[ProcessRecord, ...], *, availability: EvidenceAvailability = EvidenceAvailability.COMPLETE) -> None:
        self.records = records
        self.availability = availability

    def enumerate_processes(self) -> ProcessInventory:
        return ProcessInventory(
            records=self.records,
            availability=self.availability,
            captured_at=datetime.now(UTC),
            inaccessible_count=12 if self.availability is EvidenceAvailability.PARTIAL else 0,
        )


def _seed_dispatcher_with_mixed_sessions(home_dir: Path, work_a: Path, work_b: Path) -> tuple[DispatcherService, dict[str, str]]:
    svc = DispatcherService(home_dir=home_dir)
    svc.create_gui("GUI-Alpha", apply=True)
    svc.create_gui("GUI-Beta", apply=True)

    codex_sid = "01a21ca1-528f-7e33-8024-bc7845530001"
    agy_sid = "agy-conv-0002"
    claude_sid = "2152d5b2-09a9-4628-9ee6-5f7b334a0003"

    reg_codex = svc.register(
        "GUI-Alpha",
        "alpha-codex",
        provider="codex",
        session_id=codex_sid,
        apply=True,
    )
    reg_agy = svc.register(
        "GUI-Alpha",
        "alpha-agy",
        provider="agy",
        session_id=agy_sid,
        apply=True,
    )
    reg_claude = svc.register(
        "GUI-Beta",
        "beta-claude",
        provider="claude",
        session_id=claude_sid,
        apply=True,
    )
    codex_slot_id = reg_codex["details"]["slot_id"]
    agy_slot_id = reg_agy["details"]["slot_id"]
    claude_slot_id = reg_claude["details"]["slot_id"]
    codex_slot = svc.get_slot_by_id(codex_slot_id)
    return svc, {
        "codex_slot": codex_slot_id,
        "agy_slot": agy_slot_id,
        "claude_slot": claude_slot_id,
        "codex_sid": codex_sid,
        "agy_sid": agy_sid,
        "claude_sid": claude_sid,
        "env_id": codex_slot["current"]["environment_id"],
    }


def test_e2e_save_restart_restore_with_real_dispatcher_and_terminal_launcher(tmp_path: Path) -> None:
    home_dir = tmp_path / "llmd_home"
    work_a = tmp_path / "repo_a"
    work_b = tmp_path / "repo_b"
    work_a.mkdir()
    work_b.mkdir()

    dispatcher, ids = _seed_dispatcher_with_mixed_sessions(home_dir, work_a, work_b)
    ft = 134000000000000000
    relay_pid = os.getpid()

    tl_store = ManagedProcessStore(
        tmp_path / "managed.sqlite3",
        process_identity_lookup=lambda pid: (pid, ft) if pid in {relay_pid, 1001} else None,
        process_liveness_lookup=lambda pid: TLProcessLiveness.ALIVE if pid in {relay_pid, 1001} else TLProcessLiveness.EXITED,
    )
    tl_store.reserve_launch("tl_init_1", "win_a", [ManagedPaneReservation("pane_init_1", 0, 0, "two-column")])
    tl_store.mark_submission_started("tl_init_1")
    tl_store.mark_submission_outcome("tl_init_1", LaunchSubmissionState.ACCEPTED)
    tok = tl_store.claim_pane("tl_init_1", "pane_init_1", relay_pid=relay_pid, relay_process_created=ft)
    assert tok is not None
    tl_store.record_started(
        "tl_init_1",
        "pane_init_1",
        claim_token=tok,
        pid=1001,
        process_created=ft,
        relay_pid=relay_pid,
        relay_process_created=ft,
    )
    dispatcher.record_terminal_launch(
        {
            "launch_id": "tl_init_1",
            "pane_id": "pane_init_1",
            "terminal_session_id": "0199c03e-319b-44f8-8fd5-a35eaaf0fee7",
            "launch_started_at": "2026-11-27T17:00:00.000000Z",
            "status": "launching",
            "slot_id": ids["codex_slot"],
            "gui_id": "gui_alpha",
            "provider": "codex",
            "native_session_id": ids["codex_sid"],
            "environment_id": ids["env_id"],
            "requested_cwd": str(work_a),
            "effective_cwd": str(work_a),
            "settings": {"model": "gpt-5", "sandbox": "workspace-write"},
        }
    )

    adapter = DispatcherWorkspaceAdapter(dispatcher)
    receipt_src = adapter.build_receipt_source(tl_store)
    obs_before = RuntimeDiscovery(
        environment_id=ids["env_id"],
        runtime_kind="local",
        process_enumerator=_StaticEnumerator(
            (
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(1001, ft),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", ids["codex_sid"]),
                ),
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(1002, ft),
                    parent_pid=500,
                    image_name="agy.exe",
                    argv=("agy", "--conversation", ids["agy_sid"]),
                ),
                # Claude uses --session-id (reserved, not confirmed resumable)
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(1003, ft),
                    parent_pid=500,
                    image_name="claude.exe",
                    argv=("claude", "--session-id", ids["claude_sid"]),
                ),
            )
        ),
        managed_receipt_source=receipt_src,
    )

    # Verify parser registration works cleanly
    parser = argparse.ArgumentParser(prog="llmd")
    sub = parser.add_subparsers(dest="command")
    register_workspace_subcommands(sub)

    # 1. Save preview (-d -j)
    buf = io.StringIO()
    args_save_preview = parser.parse_args(["save", "-l", "pre-reboot", "-d", "-j"])
    assert handle_save(args_save_preview, dispatcher=dispatcher, managed_store=tl_store, observers=obs_before, stream=buf) == 0
    save_prev_json = json.loads(buf.getvalue())
    assert save_prev_json["mode"] == "preview"
    assert len(save_prev_json["checkpoint"]["sessions"]) == 3

    # 2. Save apply (-a -j)
    buf = io.StringIO()
    args_save_apply = parser.parse_args(["save", "-l", "pre-reboot", "-a", "-j"])
    assert handle_save(args_save_apply, dispatcher=dispatcher, managed_store=tl_store, observers=obs_before, stream=buf) == 0
    save_json = json.loads(buf.getvalue())
    assert save_json["mode"] == "applied"
    chk_id = save_json["checkpoint"]["checkpoint_id"]

    # 3. Simulate reboot: fresh DispatcherService, fresh ManagedProcessStore, all prior processes exited
    tl_store.record_exit("tl_init_1", "pane_init_1", claim_token=tok, exit_code=0)
    fresh_dispatcher = DispatcherService(home_dir=home_dir)
    fresh_tl_store = ManagedProcessStore(
        tmp_path / "managed.sqlite3",
        process_identity_lookup=lambda pid: (pid, ft) if pid == relay_pid else None,
        process_liveness_lookup=lambda pid: TLProcessLiveness.ALIVE if pid == relay_pid else TLProcessLiveness.EXITED,
    )
    obs_after = RuntimeDiscovery(
        environment_id=ids["env_id"],
        runtime_kind="local",
        process_enumerator=_StaticEnumerator(()),
        managed_receipt_source=DispatcherWorkspaceAdapter(fresh_dispatcher).build_receipt_source(fresh_tl_store),
    )

    # Checkpoints list & show
    buf = io.StringIO()
    assert handle_checkpoints(parser.parse_args(["checkpoints", "list", "-j"]), dispatcher=fresh_dispatcher, stream=buf) == 0
    assert json.loads(buf.getvalue())["checkpoints"][0]["checkpoint_id"] == chk_id

    # Manual restore preview (-m -j) emits manual commands for Codex/AGY and blocks reserved Claude
    buf = io.StringIO()
    assert handle_restore(
        parser.parse_args(["restore", "-c", chk_id, "-m", "-j"]),
        dispatcher=fresh_dispatcher,
        managed_store=fresh_tl_store,
        observers=obs_after,
        stream=buf,
    ) == 0
    manual_json = json.loads(buf.getvalue())
    assert ids["codex_slot"] in manual_json["manual_commands"]
    assert ids["agy_slot"] in manual_json["manual_commands"]
    assert ids["claude_slot"] not in manual_json["manual_commands"]

    # Real TerminalLauncherRestoreAdapter with fake TerminalBackend:
    # Codex gets spawn_acknowledged=True; AGY gets accepted=True but spawn_confirmed=False!
    class _FakeBackend:
        def preview(self, plan: TerminalLaunchPlan):
            raise NotImplementedError

        def launch(self, plan: TerminalLaunchPlan) -> LaunchResult:
            argv = plan.tabs[0].panes[0].argv
            if argv[0] == "codex":
                # Simulate relay acknowledging spawn in fresh_tl_store
                recs = fresh_tl_store.enumerate_processes()
                latest = recs[-1]
                claim_tok = fresh_tl_store.claim_pane(
                    latest.launch_id, latest.pane_id, relay_pid=relay_pid, relay_process_created=ft
                )
                assert claim_tok is not None
                fresh_tl_store.record_started(
                    latest.launch_id,
                    latest.pane_id,
                    claim_token=claim_tok,
                    pid=2001,
                    process_created=ft,
                    relay_pid=relay_pid,
                    relay_process_created=ft,
                )
            return LaunchResult(status=LaunchStatus.SUBMITTED, backend="fake-wt")

    launcher = TerminalLauncherRestoreAdapter(backend=_FakeBackend(), managed_store=fresh_tl_store)
    buf = io.StringIO()
    assert handle_restore(
        parser.parse_args(["restore", "-c", chk_id, "-a", "-o", "op_e2e", "-j"]),
        dispatcher=fresh_dispatcher,
        launcher=launcher,
        managed_store=fresh_tl_store,
        observers=obs_after,
        stream=buf,
    ) == 0
    restore_json = json.loads(buf.getvalue())
    outcomes = {item["slot_id"]: item for item in restore_json["report"]["outcomes"]}
    assert outcomes[ids["codex_slot"]]["status"] == "restored"
    assert outcomes[ids["codex_slot"]]["spawn_confirmed"] is True
    assert outcomes[ids["agy_slot"]]["status"] == "accepted_unconfirmed"
    assert outcomes[ids["agy_slot"]]["launch_accepted"] is True
    assert outcomes[ids["agy_slot"]]["spawn_confirmed"] is False
    assert outcomes[ids["claude_slot"]]["status"] == "skipped"

    # Queue inspection shows AGY as AMBIGUOUS and reserved Claude as PENDING; operator can resolve AGY
    buf = io.StringIO()
    assert handle_queue(parser.parse_args(["queue", "list", "-u", "-j"]), dispatcher=fresh_dispatcher, stream=buf) == 0
    unresolved = json.loads(buf.getvalue())["entries"]
    assert len(unresolved) == 2
    agy_entry = next(e for e in unresolved if e["status"] == "ambiguous")
    agy_entry_id = agy_entry["queue_entry_id"]

    buf = io.StringIO()
    assert handle_queue(
        parser.parse_args(["queue", "resolve", "-e", agy_entry_id, "-O", "completed", "-r", "verified_manually", "-j"]),
        dispatcher=fresh_dispatcher,
        stream=buf,
    ) == 0
    assert json.loads(buf.getvalue())["entry"]["status"] == "completed"


def test_uncorrelated_historical_receipt_cannot_prove_exit_under_partial_enum(tmp_path: Path) -> None:
    sid = "01a21ca1-528f-7e33-8024-bc7845530099"
    ft_old = 134000000000000000
    ft_current = 134000000055550000
    relay_pid = os.getpid()

    # Checkpoint captured PID 3002 @ ft_current
    obs_chk = RuntimeDiscovery(
        environment_id="env_win_test",
        process_enumerator=_StaticEnumerator(
            (
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(3002, ft_current),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", sid),
                ),
            )
        ),
    )
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    slot = WorkspaceSlotInput(
        slot_id="slot_corr",
        gui_id="gui_1",
        provider="codex",
        native_session_id=sid,
        environment_id="env_win_test",
        runtime_kind="local",
    )
    chk = CheckpointStore(tmp_path).create_checkpoint([slot], observers=obs_chk)

    # Older historical receipt for PID 3001 @ ft_old (different process!) exited
    tl_store = ManagedProcessStore(
        tmp_path / "managed_uncorr.sqlite3",
        process_identity_lookup=lambda pid: (pid, ft_old) if pid == relay_pid else None,
        process_liveness_lookup=lambda pid: TLProcessLiveness.ALIVE if pid == relay_pid else TLProcessLiveness.EXITED,
    )
    tl_store.reserve_launch("tl_old", "win", [ManagedPaneReservation("pane_old", 0, 0, "single")])
    tl_store.mark_submission_started("tl_old")
    tl_store.mark_submission_outcome("tl_old", LaunchSubmissionState.ACCEPTED)
    tok = tl_store.claim_pane("tl_old", "pane_old", relay_pid=relay_pid, relay_process_created=ft_old)
    assert tok is not None
    tl_store.record_started(
        "tl_old", "pane_old", claim_token=tok, pid=3001, process_created=ft_old, relay_pid=relay_pid, relay_process_created=ft_old
    )
    tl_store.record_exit("tl_old", "pane_old", claim_token=tok, exit_code=0)

    from agent_continuity.runtime_discovery import (
        ManagedAssociationState,
        ManagedLaunchAssociation,
        TerminalLauncherManagedReceiptSource,
    )

    receipt_src = TerminalLauncherManagedReceiptSource(
        tl_store,
        lambda key: (
            ManagedLaunchAssociation(
                launch_id="tl_old",
                terminal_session_id="term_old",
                pane_id="pane_old",
                session_key=key,
                association_state=ManagedAssociationState.HISTORICAL,
            ),
        ),
    )
    obs_partial = RuntimeDiscovery(
        environment_id="env_win_test",
        process_enumerator=_StaticEnumerator((), availability=EvidenceAvailability.PARTIAL),
        managed_receipt_source=receipt_src,
    )

    restorer = TopologyRestorer()
    plan = restorer.preview_restore(chk, current_slots=[slot], observers=obs_partial, has_slot_exclusion=True)
    assert plan.items[0].action == "blocked_unknown_runtime"
    assert "uncorrelated_historical_receipt" in plan.items[0].reasons


def test_dispatcher_slot_execution_guard_cross_instance_exclusion(tmp_path: Path) -> None:
    guard_a = DispatcherSlotExecutionGuard(tmp_path)
    guard_b = DispatcherSlotExecutionGuard(tmp_path)
    lease_a = guard_a.acquire_slot("slot_x", operator_id="op_a", checkpoint_id="chk_1", queue_entry_id="rq_1")
    assert lease_a.acquired is True
    lease_b = guard_b.acquire_slot("slot_x", operator_id="op_b", checkpoint_id="chk_2", queue_entry_id="rq_2")
    assert lease_b.acquired is False
    assert lease_b.reason == "slot_lock_held"
    guard_a.release_slot(lease_a)
    lease_b2 = guard_b.acquire_slot("slot_x", operator_id="op_b", checkpoint_id="chk_2", queue_entry_id="rq_2")
    assert lease_b2.acquired is True
    guard_b.release_slot(lease_b2)
