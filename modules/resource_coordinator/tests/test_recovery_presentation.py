from io import StringIO

from resource_coordinator.presentation import render_recovery_result


def test_recovery_result_shows_operational_state_and_next_cli_step_at_80_columns():
    output = StringIO()
    render_recovery_result({
        "action": "reconcile",
        "status": "planned",
        "service_state": "ready",
        "listener": {"pid": 73468, "create_time": 1793964871.4},
        "listener_discovery": "identified",
        "task": {"name": "ResourceCoordinator-KRig-UserLogon"},
        "task_attribution": {"verified": True},
        "miner_state": "running",
        "miner_pid": 92792,
        "miner_owned": True,
        "receipt_present": True,
        "receipt_phase": "RECOVERY_REQUIRED",
        "failed_at": "OLD_STOPPED",
        "active_inferences": 0,
        "pending_inferences": 0,
        "gaming_state": "inactive",
        "changes": ["archive completed failed-upgrade receipt"],
    }, stream=output, color="never", width=80)

    rendered = output.getvalue()
    assert "Coordinator" in rendered and "ready" in rendered
    assert "PID 73468" in rendered
    assert "Task attribution" in rendered and "Verified" in rendered
    assert "RECOVERY_REQUIRED" in rendered
    assert "OLD_STOPPED" in rendered
    assert "resource-coordinator system recovery reconcile -a" in rendered
    assert "{'pid':" not in rendered
    assert "create_time" not in rendered


def test_recovery_result_explains_blocker_and_does_not_claim_changes():
    output = StringIO()
    render_recovery_result({
        "action": "restore", "status": "blocked", "service_state": "offline",
        "listener_discovery": "not-found", "receipt_present": True,
        "receipt_phase": "RECOVERY_REQUIRED", "failed_at": "OLD_STOPPED",
        "blockers": ["prior coordinator PID and creation time are not proven exited"],
    }, stream=output, color="never", width=100)

    rendered = output.getvalue()
    assert "prior coordinator PID and creation time are not proven exited" in rendered
    assert "No changes made." in rendered
    assert "resource-coordinator system recovery diagnose" in rendered
