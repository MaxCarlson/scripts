"""End-to-end offline qualification for LLMD-26/40/41/42/43/44/45 adapters and CLI handlers."""

from __future__ import annotations

import argparse
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
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
from agent_continuity.environment import detect_runtime_kind
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
    is_managed_terminal_available,
)
from agent_continuity.workspace_checkpoint import (
    CheckpointStore,
    WorkspaceSlotInput,
    WorkspaceTopologyRequest,
)
from agent_continuity.workspace_cli import (
    handle_checkpoints,
    handle_queue,
    handle_restore,
    handle_save,
    register_workspace_subcommands,
)
from agent_continuity.workspace_lifecycle import (
    RestoreLaunchRequest,
    TopologyRestorer,
)


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
        runtime_kind=detect_runtime_kind(),
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
        runtime_kind=detect_runtime_kind(),
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
            recs = [r for r in fresh_tl_store.enumerate_processes() if r.state.value == "reserved"]
            for tab_idx, tab in enumerate(plan.tabs):
                for pane_idx, pane in enumerate(tab.panes):
                    if pane.argv[0] == "codex":
                        target = next(
                            (r for r in recs if r.requested_tab_index == tab_idx and r.requested_pane_index == pane_idx),
                            None,
                        )
                        if target is not None:
                            claim_tok = fresh_tl_store.claim_pane(
                                target.launch_id, target.pane_id, relay_pid=relay_pid, relay_process_created=ft
                            )
                            assert claim_tok is not None
                            fresh_tl_store.record_started(
                                target.launch_id,
                                target.pane_id,
                                claim_token=claim_tok,
                                pid=2001,
                                process_created=ft,
                                relay_pid=relay_pid,
                                relay_process_created=ft,
                            )
            return LaunchResult(status=LaunchStatus.SUBMITTED, backend="fake-wt")

    launcher = TerminalLauncherRestoreAdapter(
        backend=_FakeBackend(),
        managed_store=fresh_tl_store,
        home_dir=home_dir,
        command_builder=type(
            "_CmdBuilder",
            (),
            {
                "build_pane_command": staticmethod(
                    lambda req: (req.provider, "--session", req.native_session_id)
                )
            },
        )(),
    )
    buf = io.StringIO()
    restore_rc = handle_restore(
        parser.parse_args(["restore", "-c", chk_id, "-a", "-o", "op_e2e", "-j"]),
        dispatcher=fresh_dispatcher,
        launcher=launcher,
        managed_store=fresh_tl_store,
        observers=obs_after,
        stream=buf,
    )
    # Partial/unconfirmed outcome returns nonzero exit code 2
    assert restore_rc == 2
    restore_json = json.loads(buf.getvalue())
    outcomes = {item["slot_id"]: item for item in restore_json["report"]["outcomes"]}
    assert outcomes[ids["codex_slot"]]["status"] == "restored"
    assert outcomes[ids["codex_slot"]]["spawn_confirmed"] is True
    assert outcomes[ids["agy_slot"]]["status"] == "accepted_unconfirmed"
    assert outcomes[ids["agy_slot"]]["launch_accepted"] is True
    assert outcomes[ids["agy_slot"]]["spawn_confirmed"] is False
    assert outcomes[ids["claude_slot"]]["status"] == "skipped"

    # Queue inspection shows AGY as AMBIGUOUS and reserved Claude as PENDING; operator can resolve AGY with -a
    buf = io.StringIO()
    assert handle_queue(parser.parse_args(["queue", "list", "-u", "-j"]), dispatcher=fresh_dispatcher, stream=buf) == 0
    unresolved = json.loads(buf.getvalue())["entries"]
    assert len(unresolved) == 2
    agy_entry = next(e for e in unresolved if e["status"] == "ambiguous")
    agy_entry_id = agy_entry["queue_entry_id"]

    # Without -a, queue resolve is preview-only
    buf = io.StringIO()
    assert handle_queue(
        parser.parse_args(["queue", "resolve", "-e", agy_entry_id, "-O", "completed", "-j"]),
        dispatcher=fresh_dispatcher,
        stream=buf,
    ) == 0
    assert json.loads(buf.getvalue())["mode"] == "preview"

    buf = io.StringIO()
    assert handle_queue(
        parser.parse_args(["queue", "resolve", "-e", agy_entry_id, "-O", "completed", "-r", "verified_manually", "-a", "-j"]),
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


def test_real_managed_relay_grouped_restoration_and_failure_modes(tmp_path: Path) -> None:
    """Exercise real WindowsTerminalBackend.launch_managed + real _managed_relay with harmless Python children."""
    import subprocess
    import sys

    from terminal_launcher.backends.windows_terminal import WindowsTerminalBackend

    home_dir = tmp_path / "llmd_home"
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    dispatcher, ids = _seed_dispatcher_with_mixed_sessions(home_dir, work_dir, work_dir)

    ft = 134000000000000000
    obs_run = RuntimeDiscovery(
        environment_id=ids["env_id"],
        runtime_kind=detect_runtime_kind(),
        process_enumerator=_StaticEnumerator(
            (
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(5001, ft),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", ids["codex_sid"]),
                ),
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(5002, ft),
                    parent_pid=500,
                    image_name="agy.exe",
                    argv=("agy", "--conversation", ids["agy_sid"]),
                ),
            )
        ),
    )
    slot_a = WorkspaceSlotInput(
        slot_id=ids["codex_slot"],
        gui_id="gui_alpha",
        gui_alias="GUI-Alpha",
        provider="codex",
        native_session_id=ids["codex_sid"],
        environment_id=ids["env_id"],
        runtime_kind=detect_runtime_kind(),
        worktree=DispatcherWorkspaceAdapter(dispatcher).slot_provider(ids["codex_slot"]).worktree,  # type: ignore[union-attr]
        requested_topology=WorkspaceTopologyRequest(
            target_window="win-grouped",
            requested_tab_index=0,
            requested_pane_index=0,
            requested_layout="two-column",
        ),
    )
    slot_b = WorkspaceSlotInput(
        slot_id=ids["agy_slot"],
        gui_id="gui_alpha",
        gui_alias="GUI-Alpha",
        provider="agy",
        native_session_id=ids["agy_sid"],
        environment_id=ids["env_id"],
        runtime_kind=detect_runtime_kind(),
        worktree=DispatcherWorkspaceAdapter(dispatcher).slot_provider(ids["agy_slot"]).worktree,  # type: ignore[union-attr]
        requested_topology=WorkspaceTopologyRequest(
            target_window="win-grouped",
            requested_tab_index=0,
            requested_pane_index=1,
            requested_layout="two-column",
        ),
    )
    chk = CheckpointStore(tmp_path / "state").create_checkpoint([slot_a, slot_b], observers=obs_run)

    tl_store = ManagedProcessStore(tmp_path / "managed_real.sqlite3")
    spawned_relays: list[subprocess.Popen[str]] = []

    def _harmless_relay_runner(cmd: list[str], **_kwargs):
        # Extract the real _pane_runner.py relay invocations embedded in wt.exe args
        # and launch them directly as harmless local subprocesses running `python -c "import time; time.sleep(0.2)"`
        modules_root = str(Path(__file__).resolve().parents[2])
        idx = 0
        while idx < len(cmd):
            if cmd[idx].endswith("_pane_runner.py") and idx + 1 < len(cmd):
                relay_cmd = [cmd[idx - 1], cmd[idx], cmd[idx + 1]]
                proc = subprocess.Popen(
                    relay_cmd,
                    text=True,
                    env={**os.environ, "PYTHONPATH": modules_root},
                )
                spawned_relays.append(proc)
                idx += 2
            else:
                idx += 1
        assert len(spawned_relays) == 2
        return subprocess.CompletedProcess(cmd, 0, "", "")

    backend = WindowsTerminalBackend(runner=_harmless_relay_runner)

    class _HarmlessCmdBuilder:
        def build_pane_command(self, request: RestoreLaunchRequest) -> tuple[str, ...]:
            return (sys.executable, "-c", "import time; time.sleep(0.2)")

    launcher = TerminalLauncherRestoreAdapter(
        backend=backend,
        managed_store=tl_store,
        command_builder=_HarmlessCmdBuilder(),
        startup_timeout=5.0,
    )
    obs_after = RuntimeDiscovery(environment_id=ids["env_id"], runtime_kind=detect_runtime_kind(), process_enumerator=_StaticEnumerator(()))
    restorer = TopologyRestorer()
    plan = restorer.preview_restore(chk, current_slots=[slot_a, slot_b], observers=obs_after)
    report = restorer.execute_restore(
        plan,
        authorized=True,
        operator_id="op_real_relay",
        launcher=launcher,
        checkpoint=chk,
        receipt_store=tl_store,
        slot_guard=DispatcherSlotExecutionGuard(home_dir),
        current_slots=[slot_a, slot_b],
        observers=obs_after,
    )
    for proc in spawned_relays:
        proc.wait(timeout=5.0)

    assert report.partial_failure is False
    by_slot = {o.slot_id: o for o in report.outcomes}
    assert by_slot[ids["codex_slot"]].status == "restored"
    assert by_slot[ids["codex_slot"]].spawn_confirmed is True
    assert by_slot[ids["codex_slot"]].observed_receipt is not None
    assert by_slot[ids["agy_slot"]].status == "restored"
    assert by_slot[ids["agy_slot"]].spawn_confirmed is True
    # Both panes share the same grouped launch_id
    assert by_slot[ids["codex_slot"]].observed_receipt.launch_id == by_slot[ids["agy_slot"]].observed_receipt.launch_id  # type: ignore[union-attr]


def test_adapter_safety_floor_011_gui_scope_and_queue_recovery_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    home_dir = tmp_path / "llmd_home"
    work_a = tmp_path / "repo_a"
    work_b = tmp_path / "repo_b"
    work_a.mkdir()
    work_b.mkdir()
    dispatcher, ids = _seed_dispatcher_with_mixed_sessions(home_dir, work_a, work_b)

    # 1. Exact identity correlation & no pane_id inference from launch_id
    dispatcher.record_terminal_launch(
        {
            "launch_id": "tl_no_pane",
            "terminal_session_id": "0199c03e-319b-44f8-8fd5-a35eaaf0fee7",
            "launch_started_at": "2026-11-27T17:00:00.000000Z",
            "status": "launching",
            "slot_id": ids["codex_slot"],
            "gui_id": "gui_alpha",
            "provider": "codex",
            "native_session_id": ids["codex_sid"],
            "environment_id": ids["env_id"],
            "settings": {"model": "gpt-5"},
        }
    )
    adapter = DispatcherWorkspaceAdapter(dispatcher)
    # Without explicit pane_id, associations_for_session must return empty (never infer from launch_id)
    from agent_continuity.runtime_discovery import SessionKey

    assert adapter.associations_for_session(
        SessionKey(provider="codex", native_session_id=ids["codex_sid"], environment_id=ids["env_id"], runtime_kind="local")
    ) == ()
    # Unknown environment_id returns "unknown" (never guesses from prefix)
    assert adapter._resolve_runtime_kind("env_wsl_fake_prefix") == "unknown"

    # 2. GUI-scoped restore excludes other GUIs from execution
    ft = 134000000000000000
    obs_run = RuntimeDiscovery(
        environment_id=ids["env_id"],
        runtime_kind=detect_runtime_kind(),
        process_enumerator=_StaticEnumerator(
            (
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(6001, ft),
                    parent_pid=500,
                    image_name="codex.exe",
                    argv=("codex", "resume", ids["codex_sid"]),
                ),
                ProcessRecord(
                    identity=process_identity_from_windows_filetime(6002, ft),
                    parent_pid=500,
                    image_name="claude.exe",
                    argv=("claude", "--resume", ids["claude_sid"]),
                ),
            )
        ),
    )
    slots = adapter.list_candidate_slots()
    chk = CheckpointStore(home_dir / "workspace_state").create_checkpoint(slots, observers=obs_run)

    class _CountingLauncher:
        def __init__(self) -> None:
            self.launched: list[str] = []

        def launch_session(self, request: RestoreLaunchRequest):
            from agent_continuity.workspace_lifecycle import RestoreLaunchOutcome

            self.launched.append(request.slot_id)
            return RestoreLaunchOutcome(accepted=True, launch_id="tl_g", pane_id="p_g", spawn_confirmed=True)

    obs_after = RuntimeDiscovery(environment_id=ids["env_id"], runtime_kind=detect_runtime_kind(), process_enumerator=_StaticEnumerator(()))
    parser = argparse.ArgumentParser(prog="llmd")
    register_workspace_subcommands(parser.add_subparsers(dest="command"))
    launcher = _CountingLauncher()
    buf = io.StringIO()
    assert handle_restore(
        parser.parse_args(["restore", "-c", chk.checkpoint_id, "-g", "GUI-Alpha", "-a", "-j"]),
        dispatcher=dispatcher,
        launcher=launcher,
        observers=obs_after,
        stream=buf,
    ) == 0
    assert launcher.launched == [ids["codex_slot"]]

    # 3. Queue recover refuses without --verified-abandoned
    from agent_continuity.errors import ContinuityError
    from agent_continuity.restoration_queue import RestorationQueue

    q = RestorationQueue(home_dir / "workspace_state")
    q.enqueue_checkpoint(chk)
    e_id = q.list_entries()[0].queue_entry_id
    q.claim(e_id, operator_id="op_live")
    with pytest.raises(ContinuityError, match="abandonment"):
        handle_queue(
            parser.parse_args(["queue", "recover", "-e", e_id, "-a", "-j"]),
            dispatcher=dispatcher,
            stream=io.StringIO(),
        )

    # 4. Terminal Launcher 0.1.1 floor (no terminal_launcher.managed) still supports inspection & manual workflows
    monkeypatch.setitem(sys.modules, "terminal_launcher.managed", None)
    assert is_managed_terminal_available() is False
    buf = io.StringIO()
    assert handle_checkpoints(
        parser.parse_args(["checkpoints", "list", "-j"]), dispatcher=dispatcher, stream=buf
    ) == 0
    assert json.loads(buf.getvalue())["managed_terminal_available"] is False
    buf = io.StringIO()
    assert handle_restore(
        parser.parse_args(["restore", "-c", chk.checkpoint_id, "-m", "-j"]),
        dispatcher=dispatcher,
        observers=obs_after,
        stream=buf,
    ) == 0
    assert json.loads(buf.getvalue())["managed_terminal_available"] is False
