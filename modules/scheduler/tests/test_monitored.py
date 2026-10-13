import json
import sys
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scheduler.cli import build_parser
from scheduler.monitored import (
    ConditionTracker,
    MonitoredProcess,
    MonitorCondition,
    MonitoredProcessManager,
    discover_fields,
)
from scheduler.storage import StorageManager


def test_condition_requires_a_complete_fresh_average_window():
    tracker = ConditionTracker()
    condition = MonitorCondition(
        path="gpu.other", operator="lt", value=10,
        aggregation="average", window_seconds=10,
    )
    tracker.add({"gpu": {"other": 2}}, now=100)
    assert tracker.matches([condition], now=105) is False
    tracker.add({"gpu": {"other": 4}}, now=110)
    assert tracker.matches([condition], now=110) is True


def test_condition_hold_and_missing_field_fail_closed():
    tracker = ConditionTracker()
    condition = MonitorCondition(path="usage", operator="lt", value=10, hold_seconds=5)
    tracker.add({"usage": 0}, now=1)
    assert tracker.matches([condition], now=1) is False
    tracker.add({"usage": 0}, now=7)
    assert tracker.matches([condition], now=7) is True
    tracker.add({}, now=8)
    assert tracker.matches([condition], now=8) is False


def test_discover_fields_reports_nested_json_leaf_types():
    assert discover_fields({"gpu": {"usage": 12.5}, "running": True}) == {
        "gpu.usage": "float", "running": "bool"
    }


def test_monitored_process_storage_preserves_old_data_and_runtime_state(tmp_path):
    path = tmp_path / "scheduler_data.json"
    path.write_text(json.dumps({"version": 1, "config": {}, "schedules": {}, "tasks": {}}))
    storage = StorageManager(path)
    rule = MonitoredProcess(
        name="miner", executable="miner.exe", monitor_code="Write-Output '{}'",
        start_conditions=[MonitorCondition("ready", "eq", True)],
        stop_conditions=[MonitorCondition("busy", "eq", True)],
    )
    storage.save_monitored_process(rule)
    assert storage.get_monitored_process("miner").rule_id == rule.rule_id
    state = {rule.rule_id: {"pid": 3, "create_time": 1.0, "executable": "miner.exe"}}
    storage.save_monitor_runtime_state(state)
    assert storage.get_monitor_runtime_state() == state
    stored = json.loads(path.read_text())
    assert stored["schedules"] == {}
    assert stored["tasks"] == {}
    with pytest.raises(ValueError, match="Stop the scheduler-owned process"):
        storage.delete_monitored_process("miner")
    storage.save_monitor_runtime_state({})
    assert storage.delete_monitored_process("miner") is True
    assert storage.get_monitor_runtime_state() == {}


def test_monitor_cli_parser_accepts_json_import_and_status():
    parser = build_parser()
    args = parser.parse_args(["monitor", "create", "--input-file", "rule.json"])
    assert args.monitor_cmd == "create"
    args = parser.parse_args(["monitor", "status", "--name", "miner"])
    assert args.monitor_cmd == "status"
    assert args.name == "miner"
    args = parser.parse_args(["logs", "monitor", "--name", "miner", "--count", "25"])
    assert args.logs_cmd == "monitor"
    assert args.count == 25


def test_monitor_script_arguments_preserve_powershell_parameter_binding(tmp_path):
    script = tmp_path / "monitor script.ps1"
    executor = Mock()
    executor.execute.return_value = SimpleNamespace(success=True, stdout="{}")
    manager = MonitoredProcessManager(StorageManager(tmp_path / "data.json"), executor, Mock())
    rule = MonitoredProcess(
        name="miner", executable="miner.exe", monitor_file=str(script),
        monitor_arguments=["-ExcludeProcessName", "krig-miner"],
        start_conditions=[MonitorCondition("ready", "eq", True)],
        stop_conditions=[MonitorCondition("stop", "eq", True)],
    )
    try:
        assert manager.test(rule) == {}
        command = executor.execute.call_args.args[0].code
        assert command == f"& '{script}' -ExcludeProcessName 'krig-miner'"
    finally:
        manager.close()


def test_manual_process_stop_only_terminates_recorded_process(tmp_path, monkeypatch):
    storage = StorageManager(tmp_path / "scheduler_data.json")
    manager = MonitoredProcessManager(storage, executor=None, logger=Mock())
    rule = MonitoredProcess(
        name="child", executable=sys.executable, arguments=["-c", "import time; time.sleep(60)"],
        monitor_code="{}", start_conditions=[MonitorCondition("ready", "eq", True)],
        stop_conditions=[MonitorCondition("stop", "eq", True)],
    )
    monkeypatch.setattr(manager, "_externally_running", lambda _rule: False)
    try:
        message = manager.start(rule)
        assert message.startswith("started (PID ")
        assert manager.status(rule)["process_state"] == "owned"
        assert manager.stop(rule) == "stopped"
        assert manager.status(rule)["process_state"] == "stopped"
    finally:
        manager.close()


def test_disabling_rule_discards_an_in_flight_probe_result(tmp_path, monkeypatch):
    class ImmediatePool:
        def submit(self, _fn, _rule):
            result = Future()
            result.set_result({"ready": True})
            return result

        def shutdown(self, **_kwargs):
            return None

    storage = StorageManager(tmp_path / "scheduler_data.json")
    rule = MonitoredProcess(
        name="delayed", executable="miner.exe", monitor_code="{}",
        start_conditions=[MonitorCondition("ready", "eq", True)],
        stop_conditions=[MonitorCondition("stop", "eq", True)],
    )
    storage.save_monitored_process(rule)
    manager = MonitoredProcessManager(storage, executor=None, logger=Mock())
    manager._pool.shutdown(wait=False, cancel_futures=True)
    manager._pool = ImmediatePool()
    starts = []
    monkeypatch.setattr(manager, "start", lambda candidate: starts.append(candidate.name))
    try:
        manager.tick()
        rule.enabled = False
        storage.save_monitored_process(rule)
        manager.tick()
        assert starts == []
    finally:
        manager.close()
