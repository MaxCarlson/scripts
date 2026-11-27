"""Focused synthetic-session tests for LLMD-42..LLMD-45 workspace checkpoint & lifecycle."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from terminal_launcher.managed import (
    LaunchSubmissionState,
    ManagedPaneReservation,
    ManagedProcessStore,
)
from terminal_launcher.managed import (
    ProcessLiveness as TLProcessLiveness,
)

from agent_continuity.errors import ContinuityError
from agent_continuity.restoration_queue import QueueEntryStatus, RestorationQueue
from agent_continuity.runtime_discovery import (
    EvidenceAvailability,
    ManagedAssociationState,
    ManagedLaunchAssociation,
    ProcessInventory,
    ProcessRecord,
    RuntimeDiscovery,
    TerminalLauncherManagedReceiptSource,
    process_identity_from_windows_filetime,
)
from agent_continuity.workspace_checkpoint import (
    CheckpointStore,
    WorkspaceSlotInput,
    WorkspaceSlotMetadata,
    WorkspaceTopologyRequest,
    WorkspaceWorktreeEvidence,
    preview_checkpoint,
    revalidate_checkpoint,
)
from agent_continuity.workspace_lifecycle import (
    OwnedShutdownCoordinator,
    RestoreLaunchOutcome,
    RestoreLaunchRequest,
    TopologyRestorer,
    WorkspaceCheckpointCoordinator,
)


class _CountingEnumerator:
    def __init__(self, records: tuple[ProcessRecord, ...]) -> None:
        self.records = records
        self.calls = 0

    def enumerate_processes(self) -> ProcessInventory:
        self.calls += 1
        return ProcessInventory(
            records=self.records,
            availability=EvidenceAvailability.COMPLETE,
            captured_at=datetime.now(UTC),
        )


def _filetime_from_ns(ns: int) -> int:
    return (ns + 11644473600 * 1_000_000_000) // 100


def _make_slot(
    *,
    slot_id: str = "slot_1",
    gui_id: str = "gui_1",
    provider: str = "codex",
    session_id: str = "01a21ca1-528f-7e33-8024-bc784553a2fd",
    env_id: str = "env_win_test",
    cwd: str = "C:/work/repo",
    git_commit: str = "abc123",
    settings: dict | None = None,
    topology: WorkspaceTopologyRequest | None = None,
    metadata: WorkspaceSlotMetadata | None = None,
) -> WorkspaceSlotInput:
    return WorkspaceSlotInput(
        slot_id=slot_id,
        gui_id=gui_id,
        provider=provider,
        native_session_id=session_id,
        environment_id=env_id,
        runtime_kind="local",
        lifecycle_state="active",
        gui_alias="MainGUI",
        slot_name=f"agent-{slot_id}",
        launch_settings=settings or {"model": "gpt-5", "sandbox": "workspace-write"},
        worktree=WorkspaceWorktreeEvidence(
            requested_cwd=cwd,
            effective_cwd=cwd,
            git_repository="C:/work/repo",
            git_worktree=cwd,
            git_branch="main",
            git_commit=git_commit,
        ),
        requested_topology=topology
        or WorkspaceTopologyRequest(
            launch_id="tlaunch_1",
            pane_id="pane_1",
            terminal_session_id="term_1",
            target_window="MainWin",
            requested_layout="two-column",
            requested_tab_index=0,
            requested_pane_index=0,
        ),
        metadata=metadata
        or WorkspaceSlotMetadata(
            workflow_type="handoff",
            profile_id="prof_1",
            profile_revision=2,
            agent_number=3,
        ),
    )


def test_checkpoint_uses_single_batched_snapshot_and_separates_unobserved_and_reserved(tmp_path: Path) -> None:
    codex_sid = "01a21ca1-528f-7e33-8024-bc784553a2fd"
    claude_sid = "2152d5b2-09a9-4628-9ee6-5f7b334aa27f"
    unobserved_sid = "01a20000-0000-7000-8000-000000000099"

    filetime = 134000000000000000
    codex_id = process_identity_from_windows_filetime(1010, filetime)
    claude_id = process_identity_from_windows_filetime(2020, filetime + 1000)

    enumerator = _CountingEnumerator(
        (
            ProcessRecord(
                identity=codex_id,
                parent_pid=500,
                image_name="codex.exe",
                argv=("codex.exe", "resume", codex_sid),
            ),
            ProcessRecord(
                identity=claude_id,
                parent_pid=500,
                image_name="claude.exe",
                argv=("claude.exe", "--session-id", claude_sid),
            ),
        )
    )
    observer = RuntimeDiscovery(environment_id="env_win_test", process_enumerator=enumerator)
    slots = [
        _make_slot(slot_id="slot_codex", provider="codex", session_id=codex_sid),
        _make_slot(slot_id="slot_claude", provider="claude", session_id=claude_sid),
        _make_slot(slot_id="slot_unobserved", provider="codex", session_id=unobserved_sid),
    ]

    preview = preview_checkpoint(slots, label="before-reboot", observers=observer)
    assert enumerator.calls == 1
    assert [entry.slot_id for entry in preview.sessions] == ["slot_codex", "slot_claude"]
    assert [skip.slot_id for skip in preview.skipped_slots] == ["slot_unobserved"]
    assert preview.skipped_slots[0].lifecycle_state == "active"
    assert preview.skipped_slots[0].process_liveness == "not_observed"

    codex_entry, claude_entry = preview.sessions
    assert codex_entry.session_identity_state == "exact"
    assert codex_entry.observed_topology.window_ownership_inferred is False
    assert codex_entry.observed_topology.pane_geometry_inferred is False
    assert codex_entry.metadata.workflow_type == "handoff"
    assert codex_entry.metadata.profile_id == "prof_1"
    assert codex_entry.metadata.profile_revision == 2
    assert codex_entry.metadata.agent_number == 3

    assert claude_entry.session_identity_state == "reserved"
    assert claude_entry.resumability_state == "reserved_unconfirmed"

    store = CheckpointStore(tmp_path)
    saved = store.create_checkpoint(slots, label="before-reboot", observers=observer)
    assert enumerator.calls == 2
    loaded = store.get_checkpoint(saved.checkpoint_id)
    assert loaded == saved


def test_checkpoint_rejects_secrets_handles_corrupt_and_concurrent_saves(tmp_path: Path) -> None:
    bad_slot = _make_slot(settings={"api_key": "secret-123"})
    with pytest.raises(ContinuityError):
        preview_checkpoint([bad_slot])

    store = CheckpointStore(tmp_path)
    store.checkpoints_dir.mkdir(parents=True, exist_ok=True)
    (store.checkpoints_dir / ".tmp.999.abcd.json").write_text("{partial", encoding="utf-8")
    (store.checkpoints_dir / "chk_corrupt.json").write_text("{not-json", encoding="utf-8")

    def _save_one(idx: int) -> str:
        sid = f"01a21ca1-528f-7e33-8024-bc784553a2{idx:02d}"
        id_ = process_identity_from_windows_filetime(3000 + idx, 134000000000000000)
        enum = _CountingEnumerator(
            (ProcessRecord(identity=id_, parent_pid=500, image_name="codex.exe", argv=("codex", "resume", sid)),)
        )
        obs = RuntimeDiscovery(environment_id="env_win_test", process_enumerator=enum)
        chk = store.create_checkpoint(
            [_make_slot(slot_id=f"slot_{idx}", session_id=sid)],
            observers=obs,
        )
        return chk.checkpoint_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        created_ids = list(pool.map(_save_one, range(4)))

    valid, corrupt = store.list_checkpoints(quarantine_corrupt=True)
    assert {c.checkpoint_id for c in valid} == set(created_ids)
    assert len(corrupt) == 1
    assert not (store.checkpoints_dir / "chk_corrupt.json").exists()
    assert len(list(store.quarantine_dir.glob("chk_corrupt.*.json"))) == 1


def test_revalidation_preserves_cross_gui_transfer_and_marks_stale_evidence(tmp_path: Path) -> None:
    sid = "01a21ca1-528f-7e33-8024-bc784553a2fd"
    worktree = tmp_path / "repo"
    worktree.mkdir()
    obs = RuntimeDiscovery(
        environment_id="env_win_test",
        process_enumerator=_CountingEnumerator(
            (
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(1111, 134000000000000000),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", sid),
                ),
            )
        ),
    )
    store = CheckpointStore(tmp_path / "state")
    chk = store.create_checkpoint(
        [_make_slot(slot_id="slot_x", gui_id="gui_old", session_id=sid, cwd=str(worktree), git_commit="c1")],
        observers=obs,
    )

    transferred = _make_slot(slot_id="slot_x", gui_id="gui_new", session_id=sid, cwd=str(worktree), git_commit="c2")
    report = revalidate_checkpoint(chk, current_slots=[transferred])
    assert report.entries[0].cross_gui_transferred is True
    assert report.entries[0].current_gui_id == "gui_new"
    assert report.entries[0].can_restore is True
    assert "stale_workspace_revision_changed" in report.entries[0].reasons

    worktree.rmdir()
    missing_report = revalidate_checkpoint(chk, current_slots=[transferred])
    assert missing_report.entries[0].can_restore is False
    assert "stale_worktree_missing" in missing_report.entries[0].reasons


def test_restoration_queue_dedup_concurrent_claim_and_rebuild_preserves_unresolved(tmp_path: Path) -> None:
    sid1 = "01a21ca1-528f-7e33-8024-bc784553a201"
    sid2 = "01a21ca1-528f-7e33-8024-bc784553a202"
    obs = RuntimeDiscovery(
        environment_id="env_win_test",
        process_enumerator=_CountingEnumerator(
            (
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(1001, 134000000000000000),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", sid1),
                ),
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(1002, 134000000000000000),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", sid2),
                ),
            )
        ),
    )
    chk = CheckpointStore(tmp_path).create_checkpoint(
        [_make_slot(slot_id="slot_1", session_id=sid1), _make_slot(slot_id="slot_2", session_id=sid2)],
        observers=obs,
    )
    queue = RestorationQueue(tmp_path)
    first = queue.enqueue_checkpoint(chk)
    second = queue.enqueue_checkpoint(chk)
    assert len(first.enqueued) == 2
    assert len(second.enqueued) == 0
    assert len(second.deduplicated) == 2

    target_id = first.enqueued[0].queue_entry_id
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda i: queue.claim(target_id, operator_id=f"op_{i}"), range(4)))
    winners = [c for c in claims if c.acquired]
    assert len(winners) == 1
    token = winners[0].claim_token
    assert token is not None

    queue.record_failure(target_id, claim_token=token, reason="partial_timeout", partial=True)
    reclaimed = queue.claim(target_id, operator_id="op_retry")
    assert reclaimed.acquired is True
    assert reclaimed.claim_token is not None

    second_id = first.enqueued[1].queue_entry_id
    c2 = queue.claim(second_id, operator_id="op_done")
    assert c2.claim_token is not None
    queue.complete(second_id, claim_token=c2.claim_token, launch_id="tlaunch_9")

    queue.db_path.unlink()
    replayed = queue.rebuild_index()
    assert replayed >= 5

    unresolved = queue.list_entries(unresolved_only=True)
    assert [item.queue_entry_id for item in unresolved] == [target_id]
    assert unresolved[0].status is QueueEntryStatus.CLAIMED


def test_owned_shutdown_refuses_unverified_and_handles_partial_exit(tmp_path: Path) -> None:
    ft_ok = 134000000000000000
    ft_timeout = 134000000000010000
    sid_ok = "01a21ca1-528f-7e33-8024-bc784553a210"
    sid_timeout = "01a21ca1-528f-7e33-8024-bc784553a211"
    sid_unmanaged = "01a21ca1-528f-7e33-8024-bc784553a212"

    relay_pid = os.getpid()
    liveness_state = {relay_pid: TLProcessLiveness.ALIVE, 4001: TLProcessLiveness.ALIVE, 4002: TLProcessLiveness.ALIVE}
    identity_state = {relay_pid: (relay_pid, ft_ok), 4001: (4001, ft_ok), 4002: (4002, ft_timeout)}

    tl_store = ManagedProcessStore(
        tmp_path / "managed.sqlite3",
        process_identity_lookup=lambda pid: identity_state.get(pid),
        process_liveness_lookup=lambda pid: liveness_state.get(pid, TLProcessLiveness.UNKNOWN),
    )
    tl_store.reserve_launch(
        "tlaunch_ok",
        "winhash",
        [ManagedPaneReservation("pane_ok", 0, 0, "two-column"), ManagedPaneReservation("pane_to", 0, 1, "two-column")],
    )
    tl_store.mark_submission_started("tlaunch_ok")
    tl_store.mark_submission_outcome("tlaunch_ok", LaunchSubmissionState.ACCEPTED)
    tok1 = tl_store.claim_pane("tlaunch_ok", "pane_ok", relay_pid=relay_pid, relay_process_created=ft_ok)
    tok2 = tl_store.claim_pane("tlaunch_ok", "pane_to", relay_pid=relay_pid, relay_process_created=ft_ok)
    assert tok1 is not None and tok2 is not None
    tl_store.record_started(
        "tlaunch_ok",
        "pane_ok",
        claim_token=tok1,
        pid=4001,
        process_created=ft_ok,
        relay_pid=relay_pid,
        relay_process_created=ft_ok,
    )
    tl_store.record_started(
        "tlaunch_ok",
        "pane_to",
        claim_token=tok2,
        pid=4002,
        process_created=ft_timeout,
        relay_pid=relay_pid,
        relay_process_created=ft_ok,
    )

    receipt_source = TerminalLauncherManagedReceiptSource(
        tl_store,
        lambda key: (
            (
                ManagedLaunchAssociation(
                    launch_id="tlaunch_ok",
                    terminal_session_id="term_1",
                    pane_id="pane_ok" if key.native_session_id == sid_ok else "pane_to",
                    session_key=key,
                    association_state=ManagedAssociationState.CURRENT,
                ),
            )
            if key.native_session_id in {sid_ok, sid_timeout}
            else ()
        ),
    )

    observer = RuntimeDiscovery(
        environment_id="env_win_test",
        process_enumerator=_CountingEnumerator(
            (
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(4001, ft_ok),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", sid_ok),
                ),
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(4002, ft_timeout),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", sid_timeout),
                ),
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(4003, ft_ok),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", sid_unmanaged),
                ),
            )
        ),
        managed_receipt_source=receipt_source,
    )

    slots = [
        _make_slot(slot_id="s_ok", session_id=sid_ok),
        _make_slot(slot_id="s_to", session_id=sid_timeout),
        _make_slot(slot_id="s_unmanaged", session_id=sid_unmanaged),
    ]
    shutdown = OwnedShutdownCoordinator(tl_store)
    plan = shutdown.preview_shutdown(slots, observers=observer)
    assert [t.slot_id for t in plan.eligible_targets] == ["s_ok", "s_to"]
    assert [t.slot_id for t in plan.refused_targets] == ["s_unmanaged"]

    with pytest.raises(ContinuityError):
        shutdown.execute_shutdown(plan, authorized=False)

    # Simulate pane_ok exiting cleanly after request_interrupt is called while pane_to stays alive
    orig_request_interrupt = tl_store.request_interrupt

    def _request_interrupt_and_exit_ok(pane_id: str):
        res = orig_request_interrupt(pane_id)
        if pane_id == "pane_ok" and res.accepted:
            liveness_state[4001] = TLProcessLiveness.EXITED
            tl_store.deliver_interruption(
                "pane_ok",
                relay_pid=relay_pid,
                relay_process_created=ft_ok,
                signal_process_group=lambda _pid: True,
            )
            tl_store.record_exit(
                "tlaunch_ok",
                "pane_ok",
                claim_token=tok1,
                exit_code=0,
            )
        return res

    tl_store.request_interrupt = _request_interrupt_and_exit_ok  # type: ignore[method-assign]

    report = shutdown.execute_shutdown(
        plan,
        authorized=True,
        current_slots=slots,
        timeout_seconds=0.05,
        poll_interval_seconds=0.01,
    )
    assert report.partial is True
    by_slot = {o.slot_id: o for o in report.outcomes}
    assert by_slot["s_ok"].observed_state == "exited"
    assert by_slot["s_ok"].exit_code == 0
    assert by_slot["s_to"].requested is True
    assert by_slot["s_to"].observed_state == "timed_out"
    assert by_slot["s_unmanaged"].requested is False
    assert by_slot["s_unmanaged"].observed_state == "refused"


def test_topology_restorer_and_coordinator_save_restore_partial_recovery(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    sid1 = "01a21ca1-528f-7e33-8024-bc784553a221"
    sid2 = "01a21ca1-528f-7e33-8024-bc784553a222"
    ft = 134000000000000000

    obs_running = RuntimeDiscovery(
        environment_id="env_win_test",
        process_enumerator=_CountingEnumerator(
            (
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(5001, ft),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", sid1),
                ),
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(5002, ft),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", sid2),
                ),
            )
        ),
    )

    relay_pid = os.getpid()
    tl_store = ManagedProcessStore(
        tmp_path / "managed_restore.sqlite3",
        process_identity_lookup=lambda pid: (pid, ft),
        process_liveness_lookup=lambda _pid: TLProcessLiveness.ALIVE,
    )
    tl_store.reserve_launch(
        "tlaunch_restored",
        "winhash",
        [ManagedPaneReservation("pane_restored_1", 0, 0, "two-column")],
    )
    tl_store.mark_submission_started("tlaunch_restored")
    tl_store.mark_submission_outcome("tlaunch_restored", LaunchSubmissionState.ACCEPTED)
    tok = tl_store.claim_pane("tlaunch_restored", "pane_restored_1", relay_pid=relay_pid, relay_process_created=ft)
    assert tok is not None
    tl_store.record_started(
        "tlaunch_restored",
        "pane_restored_1",
        claim_token=tok,
        pid=6001,
        process_created=ft,
        relay_pid=relay_pid,
        relay_process_created=ft,
    )

    coordinator = WorkspaceCheckpointCoordinator(tmp_path / "llmd_state", managed_store=tl_store)
    slots = [
        _make_slot(slot_id="s1", session_id=sid1, cwd=str(repo_dir)),
        _make_slot(slot_id="s2", session_id=sid2, cwd=str(repo_dir)),
    ]

    save_preview = coordinator.preview_save(slots, label="reboot", observers=obs_running)
    assert len(save_preview.checkpoint_preview.sessions) == 2

    save_res = coordinator.save(slots, label="reboot", observers=obs_running)
    chk_id = save_res.checkpoint.checkpoint_id

    # After reboot: neither process is running
    obs_after_reboot = RuntimeDiscovery(
        environment_id="env_win_test",
        process_enumerator=_CountingEnumerator(()),
    )

    class _PartialLauncher:
        def launch_session(self, request: RestoreLaunchRequest) -> RestoreLaunchOutcome:
            if request.slot_id == "s1":
                return RestoreLaunchOutcome(
                    accepted=True,
                    launch_id="tlaunch_restored",
                    pane_id="pane_restored_1",
                    terminal_session_id="term_r1",
                )
            return RestoreLaunchOutcome(accepted=False, failure_reason="provider_start_failed")

    restore_preview = coordinator.preview_restore(chk_id, current_slots=slots, observers=obs_after_reboot)
    assert len(restore_preview.ready_items) == 2

    report = coordinator.restore(
        chk_id,
        authorized=True,
        operator_id="op_main",
        launcher=_PartialLauncher(),
        current_slots=slots,
        observers=obs_after_reboot,
    )
    assert report.partial_failure is True
    assert report.recovery_record_path is not None
    recovery_data = json.loads(Path(report.recovery_record_path).read_text(encoding="utf-8"))
    assert recovery_data["partial_failure"] is True

    by_slot = {item.slot_id: item for item in report.outcomes}
    assert by_slot["s1"].status == "restored"
    assert by_slot["s1"].observed_receipt is not None
    assert by_slot["s1"].observed_receipt.pane_id == "pane_restored_1"
    assert by_slot["s2"].status == "failed"

    unresolved = coordinator.queue.list_entries(unresolved_only=True)
    assert [item.slot_id for item in unresolved] == ["s2"]
    assert unresolved[0].partial is True
    assert unresolved[0].recovery_note == "provider_start_failed"

    # Duplicate restore attempt skips already-completed s1 and retries only s2
    preview_retry = coordinator.preview_restore(chk_id, current_slots=slots, observers=obs_after_reboot)
    retry_actions = {item.slot_id: item.action for item in preview_retry.items}
    assert retry_actions["s1"] == "skip_completed"
    assert retry_actions["s2"] == "restore"


def test_shutdown_refuses_pid_reuse_and_transfer_race_and_restore_blocks_reserved_claude(tmp_path: Path) -> None:
    ft_old = 134000000000000000
    ft_reused = 134000000099990000
    claude_sid = "2152d5b2-09a9-4628-9ee6-5f7b334aa27f"
    codex_sid = "01a21ca1-528f-7e33-8024-bc784553a299"

    relay_pid = os.getpid()
    identity_map = {relay_pid: (relay_pid, ft_old), 7001: (7001, ft_old)}
    tl_store = ManagedProcessStore(
        tmp_path / "managed_race.sqlite3",
        process_identity_lookup=lambda pid: identity_map.get(pid),
        process_liveness_lookup=lambda _pid: TLProcessLiveness.ALIVE,
    )
    tl_store.reserve_launch(
        "tlaunch_race",
        "winhash",
        [ManagedPaneReservation("pane_race", 0, 0, "single")],
    )
    tl_store.mark_submission_started("tlaunch_race")
    tl_store.mark_submission_outcome("tlaunch_race", LaunchSubmissionState.ACCEPTED)
    tok = tl_store.claim_pane("tlaunch_race", "pane_race", relay_pid=relay_pid, relay_process_created=ft_old)
    assert tok is not None
    tl_store.record_started(
        "tlaunch_race",
        "pane_race",
        claim_token=tok,
        pid=7001,
        process_created=ft_old,
        relay_pid=relay_pid,
        relay_process_created=ft_old,
    )

    race_receipt_source = TerminalLauncherManagedReceiptSource(
        tl_store,
        lambda key: (
            (
                ManagedLaunchAssociation(
                    launch_id="tlaunch_race",
                    terminal_session_id="term_race",
                    pane_id="pane_race",
                    session_key=key,
                    association_state=ManagedAssociationState.CURRENT,
                ),
            )
            if key.native_session_id == codex_sid
            else ()
        ),
    )

    observer = RuntimeDiscovery(
        environment_id="env_win_test",
        process_enumerator=_CountingEnumerator(
            (
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(7001, ft_old),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", codex_sid),
                ),
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(7002, ft_old),
                    parent_pid=500,
                    image_name="claude.exe",
                    argv=("claude", "--session-id", claude_sid),
                ),
            )
        ),
        managed_receipt_source=race_receipt_source,
    )

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    codex_slot = _make_slot(slot_id="s_race", gui_id="gui_1", provider="codex", session_id=codex_sid, cwd=str(repo_dir))
    claude_slot = _make_slot(
        slot_id="s_claude", gui_id="gui_1", provider="claude", session_id=claude_sid, cwd=str(repo_dir)
    )

    shutdown = OwnedShutdownCoordinator(tl_store)
    plan = shutdown.preview_shutdown([codex_slot], observers=observer)
    assert len(plan.eligible_targets) == 1

    # Race 1: slot transferred to another GUI before shutdown executes
    transferred_slot = _make_slot(
        slot_id="s_race", gui_id="gui_2", provider="codex", session_id=codex_sid, cwd=str(repo_dir)
    )
    race_report = shutdown.execute_shutdown(plan, authorized=True, current_slots=[transferred_slot])
    assert race_report.outcomes[0].requested is False
    assert race_report.outcomes[0].request_reason == "race_session_or_gui_changed"

    # Race 2: PID reused before shutdown executes
    identity_map[7001] = (7001, ft_reused)
    reuse_report = shutdown.execute_shutdown(plan, authorized=True, current_slots=[codex_slot])
    assert reuse_report.outcomes[0].requested is False
    assert reuse_report.outcomes[0].request_reason == "race_process_identity_changed"

    # Reserved Claude identity blocked on restore unless explicitly allowed
    chk = CheckpointStore(tmp_path / "chk").create_checkpoint([claude_slot], observers=observer)
    restorer = TopologyRestorer()
    obs_empty = RuntimeDiscovery(environment_id="env_win_test", process_enumerator=_CountingEnumerator(()))
    blocked_plan = restorer.preview_restore(chk, current_slots=[claude_slot], observers=obs_empty)
    assert blocked_plan.items[0].action == "blocked_reserved_unconfirmed"
    allowed_plan = restorer.preview_restore(
        chk, current_slots=[claude_slot], observers=obs_empty, allow_reserved_claude=True
    )
    assert allowed_plan.items[0].action == "restore"
