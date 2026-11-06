from resource_coordinator.installation import verify_legacy_evidence
import pytest


def evidence():
    return {
        "engine_pids": [10], "launcher": "C:/rc/start.ps1", "config": "C:/rc/config.yaml",
        "listener": {"pid": 30, "create_time": 3.0, "executable": "C:/Python/python.exe"},
        "chain": [
            {"pid": 30, "ppid": 20, "create_time": 3.0, "executable": "C:/Python/python.exe",
             "cmdline": ["python", "-m", "resource_coordinator.cli", "serve", "-c", "C:/rc/config.yaml", "--stop-process-on-shutdown", "krig_miner"]},
            {"pid": 20, "ppid": 10, "create_time": 2.0, "executable": "C:/venv/python.exe",
             "cmdline": ["python", "-m", "resource_coordinator.cli", "serve", "-c", "C:/rc/config.yaml", "--stop-process-on-shutdown", "krig_miner"]},
            {"pid": 10, "ppid": 1, "create_time": 1.0, "executable": "C:/pwsh.exe",
             "cmdline": ["pwsh", "-File", "C:/rc/start.ps1"]},
        ],
    }


def test_legacy_venv_to_global_python_is_attributed():
    result = verify_legacy_evidence(evidence(), "krig_miner")
    assert result["verified"] is True
    assert result["shutdown_verified"] is True


def test_legacy_attribution_rejects_unsafe_evidence():
    import copy
    base = evidence()
    cases = []
    item = copy.deepcopy(base)
    item["engine_pids"] = [10, 11]
    cases.append(item)
    item = copy.deepcopy(base)
    item["chain"][0]["create_time"] = 4.0
    cases.append(item)
    item = copy.deepcopy(base)
    item["chain"][0]["ppid"] = 99
    cases.append(item)
    item = copy.deepcopy(base)
    item["chain"][0]["cmdline"][2] = "unrelated"
    cases.append(item)
    item = copy.deepcopy(base)
    item["chain"][0]["cmdline"][5] = "C:/other.yaml"
    cases.append(item)
    item = copy.deepcopy(base)
    item["chain"][0]["cmdline"] = item["chain"][0]["cmdline"][:-2]
    cases.append(item)
    item = copy.deepcopy(base)
    item["chain"][2]["cmdline"][-1] = "C:/wrong.ps1"
    cases.append(item)
    item = copy.deepcopy(base)
    item["chain"][1]["create_time"] = 4.0
    cases.append(item)
    item = copy.deepcopy(base)
    item["chain"][0]["executable"] = "C:/other.exe"
    cases.append(item)
    for item in cases:
        assert verify_legacy_evidence(item, "krig_miner")["verified"] is False


@pytest.mark.parametrize("failure", [None, "ambiguous", "inaccessible", "wrong_task", "changed_process"])
def test_collector_fails_closed(tmp_path, monkeypatch, failure):
    import json
    import time
    import psutil
    import resource_coordinator.installation as mod

    launcher = tmp_path / "start.ps1"
    launcher.write_text("# launcher")
    now = time.time() + 5
    values = evidence()
    values["launcher"] = str(launcher)
    values["chain"][-1]["cmdline"][-1] = str(launcher)
    for index, item in enumerate(values["chain"]):
        item["create_time"] = now - index
    values["listener"]["create_time"] = now
    class Proc:
        def __init__(self, pid):
            self.item = next(x for x in values["chain"] if x["pid"] == pid)
            self.pid = pid
        def ppid(self): return self.item["ppid"]
        def create_time(self):
            return self.item["create_time"] + (1 if failure == "changed_process" else 0)
        def exe(self): return self.item["executable"]
        def cmdline(self): return self.item["cmdline"]

    def run(*args, **kwargs):
        if failure == "inaccessible":
            raise psutil.AccessDenied()
        return type("Result", (), {"stdout": json.dumps([10, 11] if failure == "ambiguous" else [10])})()
    monkeypatch.setattr(mod.subprocess, "run", run)
    monkeypatch.setattr(mod.psutil, "Process", Proc)
    monkeypatch.setattr(mod, "_task_identity_valid", lambda task: failure != "wrong_task")
    task = mod.StartupTask(mod.TASK_NAMES["logon"], "logon", True, "Running", "user", "Highest",
                           f'C:/pwsh.exe -File "{launcher}"', True)
    paths = type("Paths", (), {"config": values["config"]})()
    result = mod._legacy_attribution(task, values["listener"], paths, "krig_miner")
    assert result["verified"] is (failure is None)
    if failure == "inaccessible":
        assert "privileges" in result["reason"]
