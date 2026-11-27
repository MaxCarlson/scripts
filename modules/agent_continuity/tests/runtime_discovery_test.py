from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

import agent_continuity.runtime_discovery as runtime_discovery
from agent_continuity.runtime_discovery import (
    AgySessionStore,
    AttachmentState,
    CodexSessionStore,
    EvidenceAvailability,
    EvidenceConfidence,
    ManagedAssociationState,
    ManagedLaunchAssociation,
    ManagedPaneReference,
    ManagedReceiptSnapshot,
    ManagementState,
    MatchStatus,
    ProcessIdentity,
    ProcessInventory,
    ProcessLiveness,
    ProcessRecord,
    ProviderActivity,
    PsutilProcessEnumerator,
    RuntimeDiscovery,
    SessionKey,
    TerminalLauncherManagedReceiptSource,
    managed_pane_reference_from_terminal_launcher_record,
    match_agy_invocation,
    match_claude_invocation,
    match_codex_invocation,
)

SESSION = "01a20ac0-9181-7993-bedc-6393a27e383d"
OTHER_SESSION = "01a20ac0-9181-7993-bedc-6393a27e384d"
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


def identity(pid: int, created: int | None = None) -> ProcessIdentity:
    return ProcessIdentity(pid=pid, creation_time_ns=created if created is not None else pid * 1000)


def record(
    pid: int,
    name: str,
    argv: tuple[str, ...] | None,
    *,
    parent: int | None = None,
    created: int | None = None,
) -> ProcessRecord:
    return ProcessRecord(
        identity=identity(pid, created), parent_pid=parent, image_name=name, argv=argv
    )


class FakeProcessEnumerator:
    def __init__(self, inventory: ProcessInventory):
        self.inventory = inventory
        self.calls = 0

    def enumerate_processes(self) -> ProcessInventory:
        self.calls += 1
        return self.inventory


class FakeSessionStore:
    def __init__(self, activity: ProviderActivity):
        self.activity = activity
        self.calls = 0

    def observe(self, _key: SessionKey) -> ProviderActivity:
        self.calls += 1
        return self.activity


class FakeManagedReceipts:
    def __init__(self, snapshot: ManagedReceiptSnapshot):
        self.snapshot = snapshot

    def observe(self, _key: SessionKey) -> ManagedReceiptSnapshot:
        return self.snapshot


def inventory(*records: ProcessRecord, availability=EvidenceAvailability.COMPLETE) -> ProcessInventory:
    return ProcessInventory(records=tuple(records), availability=availability, captured_at=NOW)


def activity(*, found: bool | None, at: datetime | None = None) -> ProviderActivity:
    return ProviderActivity(
        availability=EvidenceAvailability.COMPLETE,
        found=found,
        last_activity_at=at,
        source="test_provider_store",
        captured_at=NOW,
    )


def receipts(*refs: ManagedPaneReference, availability=EvidenceAvailability.COMPLETE) -> ManagedReceiptSnapshot:
    return ManagedReceiptSnapshot(references=tuple(refs), availability=availability, captured_at=NOW)


def test_invocation_matchers_require_exact_provider_session_tokens():
    assert match_codex_invocation(("codex.exe", "resume", SESSION), SESSION)
    assert not match_codex_invocation(("codex.exe", "resume", OTHER_SESSION), SESSION)
    assert not match_codex_invocation(("codex.exe", "resume", SESSION + "x"), SESSION)
    assert not match_codex_invocation(("codex.exe", "resume", "--last"), SESSION)
    assert match_agy_invocation(("agy.exe", "--conversation", SESSION), SESSION)
    assert not match_agy_invocation(("agy.exe", "--conversation", OTHER_SESSION), SESSION)
    assert not match_agy_invocation(("agy.exe", "--conversation=" + SESSION + "x"), SESSION)


def test_provider_matchers_reject_executable_names_in_option_values_and_conflicts():
    assert not match_codex_invocation(("pwsh.exe", "-Command", "codex.exe", "resume", SESSION), SESSION)
    assert not match_codex_invocation(("codex.exe", "resume", "-C", SESSION, OTHER_SESSION), SESSION)
    assert not match_codex_invocation(("codex.exe", "resume", SESSION, "--last"), SESSION)
    assert not match_agy_invocation(("agy.exe", "--conversation", SESSION, "--conversation", OTHER_SESSION), SESSION)
    assert not match_agy_invocation(("agy.exe", "--unknown-option", "--conversation", SESSION), SESSION)
    assert not match_claude_invocation(("claude.exe", "--resume", SESSION, "--session-id", OTHER_SESSION), SESSION)
    assert not match_claude_invocation(("claude.exe", "--unknown-option", "--resume", SESSION), SESSION)


def test_claude_matcher_rejects_conflicting_and_noninteractive_modes():
    invocations = (
        ("claude.exe", "--resume", SESSION, "--continue"),
        ("claude.exe", "--continue", "--resume", SESSION),
        ("claude.exe", "--resume", SESSION, "--help"),
        ("claude.exe", "--resume", SESSION, "--version"),
        ("claude.exe", "--resume", SESSION, "--print", "prompt"),
        ("claude.exe", "-p", "prompt", "--resume", SESSION),
    )

    assert all(not match_claude_invocation(argv, SESSION) for argv in invocations)


def test_agy_matcher_rejects_help_and_version_modes():
    assert not match_agy_invocation(("agy.exe", "--help", "--conversation", SESSION), SESSION)
    assert not match_agy_invocation(("agy.exe", "--version", "--conversation", SESSION), SESSION)


def test_claude_session_id_selector_matches_exact_reserved_identity():
    assert match_claude_invocation(("claude.exe", "--session-id", SESSION), SESSION)
    assert not match_claude_invocation(("claude.exe", "--session-id", OTHER_SESSION), SESSION)


def test_claude_reserved_id_is_not_reported_as_missing_durable_session():
    processes = FakeProcessEnumerator(
        inventory(record(202, "claude.exe", ("claude.exe", "--session-id", SESSION)))
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"claude": FakeSessionStore(activity(found=False, at=NOW))},
        environment_id="env-native",
        clock=lambda: NOW,
    )

    observed = discovery.observe(SessionKey("claude", SESSION, "env-native"))

    assert observed.session_identity_state.value == "reserved"
    assert not observed.evidence_conflict


def test_managed_identity_comparison_keeps_rounded_psutil_time_ambiguous():
    exact = runtime_discovery.process_identity_from_windows_filetime(203, 133_000_000_000_000_000)
    approximate = runtime_discovery.process_identity_from_psutil(
        exact.pid, exact.creation_time_ns / 1_000_000_000
    )
    ref = ManagedPaneReference(
        provider="codex", native_session_id=SESSION, environment_id="env-native",
        process_identity=exact, launch_id="launch", pane_id="pane", terminal_session_id="terminal",
    )
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(
            ProcessInventory((ProcessRecord(approximate, 0, "pwsh.exe"),), EvidenceAvailability.COMPLETE, NOW)
        ),
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        managed_receipt_source=FakeManagedReceipts(receipts(ref)),
        environment_id="env-native",
        clock=lambda: NOW,
    )

    observed = discovery.observe(SessionKey("codex", SESSION, "env-native"))

    assert observed.process_liveness is ProcessLiveness.UNKNOWN
    assert not observed.identity_conflict


def test_historical_receipts_never_establish_current_process_liveness_or_identity():
    key = SessionKey("codex", SESSION, "env-native")
    first = ManagedPaneReference(
        provider="codex", native_session_id=SESSION, environment_id="env-native",
        process_identity=identity(220, 220000), launch_id="launch-old-1", pane_id="pane-1",
        terminal_session_id="terminal-1", association_state=ManagedAssociationState.HISTORICAL,
    )
    second = ManagedPaneReference(
        provider="codex", native_session_id=SESSION, environment_id="env-native",
        process_identity=identity(221, 221000), launch_id="launch-old-2", pane_id="pane-2",
        terminal_session_id="terminal-2", association_state=ManagedAssociationState.HISTORICAL,
    )
    receipt_snapshot = ManagedReceiptSnapshot(
        references=(), availability=EvidenceAvailability.COMPLETE, captured_at=NOW,
        historical_references=(first, second),
    )
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(
            inventory(ProcessRecord(first.process_identity, None, "pwsh.exe"))
        ),
        provider_stores={},
        managed_receipt_source=FakeManagedReceipts(receipt_snapshot),
        environment_id="env-native",
        clock=lambda: NOW,
    )

    observed = discovery.observe(key)

    assert observed.process_liveness is ProcessLiveness.NOT_OBSERVED
    assert observed.process_session_match is MatchStatus.NOT_OBSERVED
    assert observed.management is ManagementState.HISTORICAL
    assert observed.managed_pane is None
    assert observed.historical_managed_panes == (first, second)


def test_observation_serializes_process_identity_precision_for_recovery():
    approximate = ProcessIdentity(204, 2_000_000_000_000_000_000, precision_ns=200)
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(
            inventory(ProcessRecord(approximate, 0, "codex.exe", ("codex.exe", "resume", SESSION)))
        ),
        provider_stores={},
        clock=lambda: NOW,
    )

    payload = discovery.observe(SessionKey("codex", SESSION)).to_dict()

    assert payload["processes"][0]["creation_time_precision_ns"] == 200


def test_ancestry_uses_identity_precision_when_parent_timestamp_rounds_later():
    terminal = ProcessRecord(ProcessIdentity(210, 10_000, 100), None, "WindowsTerminal.exe")
    shell = ProcessRecord(ProcessIdentity(211, 9_950, 100), 210, "pwsh.exe")
    provider = ProcessRecord(
        ProcessIdentity(212, 11_000, 100), 211, "codex.exe", ("codex.exe", "resume", SESSION)
    )
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(inventory(terminal, shell, provider)),
        provider_stores={},
        clock=lambda: NOW,
    )

    observed = discovery.observe(SessionKey("codex", SESSION))

    assert observed.interactive_attachment is AttachmentState.ATTACHED
    assert not observed.ancestry[0].ambiguous


def test_batch_observation_reuses_one_environment_bound_snapshot():
    environment_id = "env-native"
    keys = tuple(SessionKey("codex", f"session-{index}", environment_id) for index in range(20))
    processes = FakeProcessEnumerator(inventory(record(201, "pwsh.exe", ("pwsh.exe",))))
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        environment_id=environment_id,
        clock=lambda: NOW,
    )

    snapshot = discovery.capture_snapshot()
    observations = discovery.observe_many(keys, snapshot=snapshot)

    assert processes.calls == 1
    assert len(observations) == len(keys)
    assert all(item.process_liveness is ProcessLiveness.NOT_OBSERVED for item in observations)
    assert all(item.key.environment_id == environment_id for item in observations)


def test_observer_rejects_environment_mismatch_without_querying_sources():
    processes = FakeProcessEnumerator(inventory())
    store = FakeSessionStore(activity(found=True, at=NOW))
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"codex": store},
        environment_id="env-local",
        clock=lambda: NOW,
    )

    observed = discovery.observe(SessionKey("codex", SESSION, "env-other"))

    assert observed.availability is EvidenceAvailability.UNAVAILABLE
    assert processes.calls == 0
    assert store.calls == 0


def test_expired_batch_snapshot_is_not_used_for_negative_process_evidence():
    now = [NOW]
    processes = FakeProcessEnumerator(inventory())
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={},
        environment_id="env-native",
        clock=lambda: now[0],
    )
    snapshot = discovery.capture_snapshot()
    now[0] += timedelta(seconds=3)

    observed = discovery.observe_many(
        (SessionKey("codex", SESSION, "env-native"),), snapshot=snapshot
    )[0]

    assert observed.process_liveness is ProcessLiveness.UNKNOWN
    assert observed.availability is EvidenceAvailability.UNAVAILABLE
    assert processes.calls == 1


def test_claude_resume_matcher_is_available_for_runtime_discovery():
    matcher = getattr(runtime_discovery, "match_claude_invocation", None)

    assert callable(matcher)
    assert matcher(("claude.exe", "--resume", SESSION), SESSION)
    assert not matcher(("claude.exe", "--resume", OTHER_SESSION), SESSION)
    assert not matcher(("claude.exe", "--resume", SESSION + "x"), SESSION)


def test_claude_process_is_exactly_observed_without_provider_store():
    processes = FakeProcessEnumerator(
        inventory(record(80, "claude.exe", ("claude.exe", "--resume", SESSION)))
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={},
        environment_id="env-win",
        clock=lambda: NOW,
    )

    observed = discovery.observe(SessionKey("claude", SESSION, "env-win"))

    assert observed.process_session_match is MatchStatus.EXACT
    assert observed.process_liveness is ProcessLiveness.RUNNING


def test_custom_provider_process_matcher_extends_runtime_observation():
    def matcher(argv, native_session_id):
        return tuple(argv or ()) == ("custom-agent.exe", "--session", native_session_id)

    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(
            inventory(record(81, "custom-agent.exe", ("custom-agent.exe", "--session", SESSION)))
        ),
        provider_stores={},
        process_matchers={"custom": matcher},
        environment_id="env-win",
        clock=lambda: NOW,
    )

    observed = discovery.observe(SessionKey("custom", SESSION, "env-win"))

    assert observed.process_session_match is MatchStatus.EXACT
    assert observed.process_liveness is ProcessLiveness.RUNNING


def test_exact_codex_process_match_is_live_even_when_provider_activity_is_stale():
    old = NOW - timedelta(days=10)
    processes = FakeProcessEnumerator(
        inventory(
            record(10, "WindowsTerminal.exe", ("WindowsTerminal.exe",)),
            record(20, "pwsh.exe", ("pwsh.exe",), parent=10),
            record(30, "codex.exe", ("codex.exe", "resume", SESSION), parent=20),
        )
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=old))},
        managed_receipt_source=FakeManagedReceipts(receipts()),
        environment_id="env-win",
        clock=lambda: NOW,
    )

    observed = discovery.observe(SessionKey("codex", SESSION, "env-win"), registry_association=True)

    assert observed.process_session_match is MatchStatus.EXACT
    assert observed.process_liveness is ProcessLiveness.RUNNING
    assert observed.interactive_attachment is AttachmentState.ATTACHED
    assert observed.management is ManagementState.UNMANAGED
    assert observed.provider_activity_at == old
    assert observed.registry_association is True
    assert observed.confidence is EvidenceConfidence.EXACT
    assert "argv" not in observed.to_dict()
    assert SESSION not in repr(observed.evidence)


def test_recent_unrelated_session_never_substitutes_for_requested_exact_id():
    processes = FakeProcessEnumerator(
        inventory(record(31, "codex.exe", ("codex.exe", "resume", OTHER_SESSION)))
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )

    observed = discovery.observe(SessionKey("codex", SESSION))

    assert observed.process_session_match is MatchStatus.NOT_OBSERVED
    assert observed.process_liveness is ProcessLiveness.NOT_OBSERVED
    assert observed.provider_session_found is True


def test_positive_exact_match_survives_partial_inventory_without_claiming_completeness():
    processes = FakeProcessEnumerator(
        inventory(
            record(32, "codex.exe", ("codex.exe", "resume", SESSION)),
            availability=EvidenceAvailability.PARTIAL,
        )
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION))
    assert observed.process_liveness is ProcessLiveness.RUNNING
    assert observed.process_session_match is MatchStatus.EXACT
    assert observed.availability is EvidenceAvailability.PARTIAL


def test_exact_live_process_contradicting_provider_store_is_retained_as_conflict():
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(
            inventory(record(33, "codex.exe", ("codex.exe", "resume", SESSION)))
        ),
        provider_stores={"codex": FakeSessionStore(activity(found=False))},
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION))
    assert observed.process_liveness is ProcessLiveness.RUNNING
    assert observed.provider_session_found is False
    assert observed.evidence_conflict
    assert not observed.identity_conflict
    assert any(item.code == "process_match_missing_from_provider_store" for item in observed.evidence)


def test_pid_reuse_marks_old_managed_identity_exited_and_current_exact_process_live():
    processes = FakeProcessEnumerator(
        inventory(record(40, "codex.exe", ("codex.exe", "resume", SESSION), created=9000))
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )

    observed = discovery.observe(
        SessionKey("codex", SESSION), known_process=identity(40, 8000)
    )

    assert observed.process_liveness is ProcessLiveness.RUNNING
    assert observed.known_process_liveness is ProcessLiveness.EXITED
    assert observed.identity_conflict


def test_known_pid_missing_from_complete_inventory_is_exited():
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(inventory()),
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION), known_process=identity(50, 50000))
    assert observed.process_liveness is ProcessLiveness.EXITED
    assert observed.known_process_liveness is ProcessLiveness.EXITED


def test_known_live_process_identity_remains_exact_without_readable_arguments():
    known = identity(52, 52000)
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(
            inventory(record(52, "codex.exe", None, created=52000))
        ),
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION), known_process=known)
    assert observed.process_liveness is ProcessLiveness.RUNNING
    assert observed.process_session_match is MatchStatus.EXACT


def test_incomplete_process_enumeration_never_reports_inactive_or_exited():
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(
            inventory(availability=EvidenceAvailability.PARTIAL)
        ),
        provider_stores={"codex": FakeSessionStore(activity(found=None))},
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION), known_process=identity(51, 51000))
    assert observed.process_liveness is ProcessLiveness.UNKNOWN
    assert observed.known_process_liveness is ProcessLiveness.UNKNOWN
    assert observed.availability is EvidenceAvailability.PARTIAL


def test_ambiguous_ancestry_keeps_attachment_unknown():
    processes = FakeProcessEnumerator(
        inventory(
            record(60, "WindowsTerminal.exe", ("WindowsTerminal.exe",), created=6000),
            record(60, "taskhostw.exe", ("taskhostw.exe",), created=6100),
            record(61, "codex.exe", ("codex.exe", "resume", SESSION), parent=60),
        )
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION))
    assert observed.process_liveness is ProcessLiveness.RUNNING
    assert observed.interactive_attachment is AttachmentState.UNKNOWN
    assert any(item.code == "ambiguous_ancestry" for item in observed.evidence)


def test_missing_parent_evidence_does_not_claim_attachment_or_detachment():
    processes = FakeProcessEnumerator(
        inventory(record(62, "codex.exe", ("codex.exe", "resume", SESSION), parent=999))
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION))
    assert observed.process_liveness is ProcessLiveness.RUNNING
    assert observed.interactive_attachment is AttachmentState.UNKNOWN
    assert any(item.code == "ancestry_incomplete" for item in observed.evidence)


def test_complete_background_task_ancestry_is_reported_detached():
    processes = FakeProcessEnumerator(
        inventory(
            record(70, "taskhostw.exe", ("taskhostw.exe",), parent=0),
            record(71, "codex.exe", ("codex.exe", "resume", SESSION), parent=70),
        )
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION))
    assert observed.interactive_attachment is AttachmentState.DETACHED
    assert observed.attachment_confidence is EvidenceConfidence.MEDIUM


def test_managed_pane_reference_uses_exact_pid_creation_identity():
    ref = ManagedPaneReference(
        provider="codex",
        native_session_id=SESSION,
        environment_id="env-win",
        process_identity=identity(80, 80000),
        launch_id="launch-safe-id",
        pane_id="pane-safe-id",
        terminal_session_id="terminal-safe-id",
    )
    processes = FakeProcessEnumerator(
        inventory(record(80, "codex.exe", None, parent=79, created=80000))
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        managed_receipt_source=FakeManagedReceipts(receipts(ref)),
        environment_id="env-win",
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION, "env-win"))
    assert observed.process_liveness is ProcessLiveness.RUNNING
    assert observed.process_session_match is MatchStatus.EXACT
    assert observed.management is ManagementState.MANAGED
    assert observed.interactive_attachment is AttachmentState.ATTACHED
    assert observed.managed_pane == ref


def test_terminal_launcher_receipt_adapter_is_optional_and_normalizes_filetime():
    from types import SimpleNamespace

    filetime = 133_000_000_000_000_000
    native_record = SimpleNamespace(
        spawn_acknowledged=True,
        pid=81,
        process_created=filetime,
        launch_id="launch-id",
        pane_id="pane-id",
    )
    ref = managed_pane_reference_from_terminal_launcher_record(
        SessionKey("codex", SESSION, "env-win"),
        native_record,
        terminal_session_id="terminal-id",
    )
    assert ref is not None
    assert ref.process_identity.pid == 81
    assert ref.process_identity.creation_time_ns == (filetime - 116_444_736_000_000_000) * 100
    assert managed_pane_reference_from_terminal_launcher_record(
        SessionKey("codex", SESSION),
        SimpleNamespace(**{**vars(native_record), "spawn_acknowledged": False}),
        terminal_session_id="terminal-id",
    ) is None


def test_optional_terminal_launcher_source_joins_exact_session_without_import_dependency():
    from types import SimpleNamespace

    filetime = 133_000_000_000_000_000
    terminal_record = SimpleNamespace(
        spawn_acknowledged=True,
        pid=82,
        process_created=filetime,
        launch_id="launch-exact",
        pane_id="pane-exact",
    )

    class FakeStore:
        calls: list[str] = []

        def enumerate_processes(self, *, launch_id=None):
            self.calls.append(launch_id)
            return (terminal_record,) if launch_id == "launch-exact" else ()

    store = FakeStore()
    source = TerminalLauncherManagedReceiptSource(
        store,
        lambda key: (
            (ManagedLaunchAssociation(
                "launch-exact", "terminal-exact", "pane-exact", key,
                ManagedAssociationState.CURRENT,
            ),)
            if key.native_session_id == SESSION else ()
        ),
        clock=lambda: NOW,
    )
    key = SessionKey("codex", SESSION, "env-win")
    snapshot = source.observe(key)
    assert snapshot.availability is EvidenceAvailability.COMPLETE
    assert len(snapshot.references) == 1
    assert store.calls == ["launch-exact"]

    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(
            inventory(
                record(
                    82,
                    "codex.exe",
                    None,
                    created=snapshot.references[0].process_identity.creation_time_ns,
                )
            )
        ),
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        managed_receipt_source=source,
        environment_id="env-win",
        clock=lambda: NOW,
    )
    observed = discovery.observe(key)
    assert observed.management is ManagementState.MANAGED
    assert observed.interactive_attachment is AttachmentState.ATTACHED


def test_terminal_launcher_source_links_exact_pane_and_separates_history_within_launch():
    from types import SimpleNamespace

    filetime = 133_000_000_000_000_000
    records = (
        SimpleNamespace(
            spawn_acknowledged=True, pid=830, process_created=filetime,
            launch_id="shared-launch", pane_id="pane-codex", state="running", liveness="alive",
        ),
        SimpleNamespace(
            spawn_acknowledged=True, pid=831, process_created=filetime + 1000,
            launch_id="shared-launch", pane_id="pane-claude", state="exited", liveness="exited",
        ),
    )

    class FakeStore:
        def enumerate_processes(self, *, launch_id=None):
            return records if launch_id == "shared-launch" else ()

    codex_key = SessionKey("codex", SESSION, "env-win")
    claude_key = SessionKey("claude", OTHER_SESSION, "env-win")
    associations = {
        codex_key: (
            SimpleNamespace(
                session_key=codex_key, launch_id="shared-launch", pane_id="pane-codex",
                terminal_session_id="terminal-1", association_state="current",
            ),
        ),
        claude_key: (
            SimpleNamespace(
                session_key=claude_key, launch_id="shared-launch", pane_id="pane-claude",
                terminal_session_id="terminal-1", association_state="historical",
            ),
        ),
    }
    source = TerminalLauncherManagedReceiptSource(
        FakeStore(), lambda key: associations[key], clock=lambda: NOW
    )

    current = source.observe(codex_key)
    historical = source.observe(claude_key)

    assert [reference.pane_id for reference in current.references] == ["pane-codex"]
    assert current.historical_references == ()
    assert historical.references == ()
    assert [reference.pane_id for reference in historical.historical_references] == ["pane-claude"]


@pytest.mark.parametrize(
    "filetime",
    (
        134344736000000011,
        134344736000000016,
        134344736000000020,
        134344736000000049,
        134344736000000080,
    ),
)
def test_psutil_time_precision_does_not_turn_filetime_rounding_into_pid_reuse(filetime):
    converter = getattr(runtime_discovery, "process_identity_from_psutil", None)
    comparer = getattr(runtime_discovery, "compare_process_identities", None)

    assert callable(converter)
    assert callable(comparer)
    exact = runtime_discovery.process_identity_from_windows_filetime(900, filetime)
    approximate = converter(900, exact.creation_time_ns / 1_000_000_000)

    assert comparer(exact, approximate).value == "ambiguous"
    reused = ProcessIdentity(900, exact.creation_time_ns + 10_000)
    assert comparer(exact, reused).value == "different"


def test_managed_receipt_pid_reuse_conflicts_with_current_exact_session_process():
    ref = ManagedPaneReference(
        provider="codex",
        native_session_id=SESSION,
        environment_id=None,
        process_identity=identity(90, 90000),
        launch_id="launch",
        pane_id="pane",
        terminal_session_id="terminal",
    )
    processes = FakeProcessEnumerator(
        inventory(record(90, "codex.exe", ("codex.exe", "resume", SESSION), created=90001))
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        managed_receipt_source=FakeManagedReceipts(receipts(ref)),
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION))
    assert observed.process_liveness is ProcessLiveness.RUNNING
    assert observed.management is ManagementState.CONFLICT
    assert observed.identity_conflict
    assert observed.evidence_conflict
    assert observed.interactive_attachment is AttachmentState.UNKNOWN


def test_multiple_managed_pane_references_are_ambiguous():
    refs = tuple(
        ManagedPaneReference(
            provider="codex",
            native_session_id=SESSION,
            environment_id="env",
            process_identity=identity(pid),
            launch_id=f"launch-{pid}",
            pane_id=f"pane-{pid}",
            terminal_session_id=f"terminal-{pid}",
        )
        for pid in (91, 92)
    )
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(inventory()),
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        managed_receipt_source=FakeManagedReceipts(receipts(*refs)),
        environment_id="env",
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION, "env"))
    assert observed.process_liveness is ProcessLiveness.AMBIGUOUS
    assert observed.process_session_match is MatchStatus.AMBIGUOUS
    assert observed.management is ManagementState.CONFLICT
    assert observed.evidence_conflict
    assert not observed.identity_conflict
    assert observed.managed_pane is None


def test_registry_only_session_stays_unknown_without_native_or_process_evidence():
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(inventory()),
        provider_stores={},
        runtime_kind="wsl",
        environment_id="env-wsl",
        clock=lambda: NOW,
    )
    observed = discovery.observe(
        SessionKey("agy", SESSION, "env-wsl", runtime_kind="wsl"), registry_association=True
    )
    assert observed.registry_association is True
    assert observed.provider_session_found is None
    assert observed.process_liveness is ProcessLiveness.NOT_OBSERVED
    assert observed.management is ManagementState.UNKNOWN
    assert observed.interactive_attachment is AttachmentState.UNKNOWN


def test_absent_optional_receipt_source_does_not_require_terminal_launcher_020():
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(inventory()),
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION))
    assert observed.management is ManagementState.UNKNOWN
    assert observed.managed_pane is None


def test_agy_exact_process_and_provider_database_row_are_correlated(tmp_path):
    db = tmp_path / "conversation_summaries.db"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "create table conversation_summaries (conversation_id text, last_modified_time text, last_user_input_time text)"
        )
        connection.executemany(
            "insert into conversation_summaries values (?, ?, ?)",
            [(OTHER_SESSION, "2026-11-27T11:59:00Z", None), (SESSION, "2026-11-01T00:00:00Z", "2026-10-31T23:00:00Z")],
        )
    store = AgySessionStore(db)
    result = store.observe(SessionKey("agy", SESSION))
    assert result.found is True
    assert result.last_activity_at == datetime(2026, 11, 1, 0, 0, tzinfo=UTC)


def test_codex_exact_database_lookup_does_not_select_newest_row(tmp_path):
    db = tmp_path / "state_5.sqlite"
    with sqlite3.connect(db) as connection:
        connection.execute("create table threads (id text, updated_at real)")
        connection.executemany(
            "insert into threads values (?, ?)", [(OTHER_SESSION, 1795779000), (SESSION, 1794000000)]
        )
    store = CodexSessionStore(db)
    result = store.observe(SessionKey("codex", SESSION))
    assert result.found is True
    assert result.last_activity_at == datetime.fromtimestamp(1794000000, UTC)


def test_unavailable_provider_store_is_not_a_negative_session_result(tmp_path):
    store = CodexSessionStore(tmp_path / "missing.sqlite")
    result = store.observe(SessionKey("codex", SESSION))
    assert result.found is None
    assert result.availability is EvidenceAvailability.UNAVAILABLE


def test_concurrent_observations_do_not_share_or_mutate_records():
    processes = FakeProcessEnumerator(
        inventory(record(100, "agy.exe", ("agy.exe", "--conversation", SESSION)))
    )
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"agy": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )
    with ThreadPoolExecutor(max_workers=8) as pool:
        observations = list(pool.map(lambda _: discovery.observe(SessionKey("agy", SESSION)), range(16)))
    assert all(item.process_liveness is ProcessLiveness.RUNNING for item in observations)
    assert len({item.captured_at for item in observations}) == 1


def test_process_inventory_and_observation_never_repr_raw_arguments():
    raw = ("codex.exe", "resume", SESSION, "secret-like-prompt")
    snapshot = inventory(record(110, "codex.exe", raw))
    discovery = RuntimeDiscovery(
        process_enumerator=FakeProcessEnumerator(snapshot),
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION))
    assert "secret-like-prompt" not in repr(snapshot)
    assert "secret-like-prompt" not in repr(observed)
    assert "secret-like-prompt" not in str(observed.to_dict())


def test_psutil_source_returns_a_safe_availability_record():
    snapshot = PsutilProcessEnumerator().enumerate_processes()
    assert snapshot.availability in {
        EvidenceAvailability.COMPLETE,
        EvidenceAvailability.PARTIAL,
        EvidenceAvailability.UNAVAILABLE,
    }
    assert "argv=<redacted>" in repr(snapshot)


def test_wsl_or_remote_target_is_not_probed_from_the_local_runtime():
    processes = FakeProcessEnumerator(inventory())
    discovery = RuntimeDiscovery(
        process_enumerator=processes,
        provider_stores={"codex": FakeSessionStore(activity(found=True, at=NOW))},
        clock=lambda: NOW,
    )
    observed = discovery.observe(SessionKey("codex", SESSION, runtime_kind="wsl"))
    assert observed.process_liveness is ProcessLiveness.UNKNOWN
    assert observed.availability is EvidenceAvailability.UNAVAILABLE
    assert processes.calls == 0
