import pytest
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

def test_mem_info():
    mgr = SystemManager()
    results = mgr.mem_info()
    assert len(results) >= 1
    assert results[0]['type'] == "RAM"
    assert "total" in results[0]

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
