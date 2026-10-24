from types import SimpleNamespace
import system_manager.manager as manager_module
from system_manager.manager import SystemManager

def test_uptime():
    mgr = SystemManager()
    result = mgr.uptime()
    assert "uptime" in result
    assert "boot_time" in result

def test_cpu_info():
    mgr = SystemManager()
    result = mgr.cpu_info()
    assert result['physical_cores'] > 0
    assert "current_load" in result


def test_cpu_info_uses_shared_cpu_count_and_blocking_sample(monkeypatch):
    count_calls = []
    cpu_calls = []
    monkeypatch.setattr(manager_module, "cpu_count", lambda *, logical: count_calls.append(logical) or (16 if logical else 8))
    monkeypatch.setattr(manager_module, "cpu_percent", lambda **kwargs: cpu_calls.append(kwargs) or 12.5)

    result = SystemManager.cpu_info()

    assert result["physical_cores"] == 8
    assert result["logical_cores"] == 16
    assert result["current_load"] == "12.5%"
    assert count_calls == [False, True]
    assert cpu_calls == [{"interval": 0.5}]

def test_mem_info():
    mgr = SystemManager()
    results = mgr.mem_info()
    assert len(results) >= 1
    assert results[0]['type'] == "RAM"
    assert "total" in results[0]


def test_mem_info_uses_shared_ram_values_and_preserves_swap(monkeypatch):
    monkeypatch.setattr(
        manager_module,
        "memory_stats",
        lambda: {"total": 1000, "used": 400, "available": 600, "percent": 40.0},
    )
    monkeypatch.setattr(
        manager_module.psutil,
        "swap_memory",
        lambda: SimpleNamespace(total=200, used=50, free=150, percent=25.0),
    )

    results = SystemManager.mem_info()

    assert results[0] == {"type": "RAM", "total": 1000, "used": 400, "free": 600, "percent": "40.0%"}
    assert results[1]["type"] == "Swap"


def test_sys_monitor_uses_shared_cpu_ram_and_network_samples(monkeypatch):
    cpu_calls = []
    network_calls = []
    monkeypatch.setattr(manager_module, "cpu_percent", lambda **kwargs: cpu_calls.append(kwargs) or 12.5)
    monkeypatch.setattr(
        manager_module,
        "memory_stats",
        lambda: {"total": 1000, "used": 400, "available": 600, "percent": 40.0},
    )
    monkeypatch.setattr(
        manager_module,
        "net_io_counters",
        lambda **kwargs: network_calls.append(kwargs) or SimpleNamespace(bytes_sent=100, bytes_recv=200),
    )
    monkeypatch.setattr(manager_module.psutil, "disk_usage", lambda path: SimpleNamespace(percent=30.0))

    result = SystemManager.sys_monitor()

    assert result["cpu_load"] == "12.5%"
    assert result["memory_usage"] == "40.0%"
    assert result["disk_usage"] == "30.0%"
    assert isinstance(result["net_sent"], str)
    assert isinstance(result["net_recv"], str)
    assert cpu_calls == [{"interval": 0.5}]
    assert network_calls == [{}]

def test_disk_list():
    mgr = SystemManager()
    results = mgr.disk_list()
    assert len(results) > 0
    assert "device" in results[0]
    assert "mount" in results[0]

def test_os_detail():
    mgr = SystemManager()
    # This prints to console but we can check if it runs without error
    mgr.os_detail()

def test_sys_console_size():
    mgr = SystemManager()
    result = mgr.sys_console_size()
    assert result['width'] > 0
    assert result['height'] > 0
