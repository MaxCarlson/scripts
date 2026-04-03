import pytest
from system_manager.manager import SystemManager

def test_process_top():
    mgr = SystemManager()
    results = mgr.process_top(count=5, sort_by="cpu")
    assert len(results) > 0
    assert "pid" in results[0]
    assert "name" in results[0]
    assert "cpu" in results[0]

def test_proc_tree():
    mgr = SystemManager()
    results = mgr.proc_tree()
    assert len(results) > 0
    assert "pid" in results[0]
    assert "name" in results[0]

def test_proc_find():
    mgr = SystemManager()
    # Find python process (which is running this test)
    results = mgr.proc_find(pattern="python")
    assert len(results) > 0
    assert any("python" in r['name'].lower() for r in results)

def test_proc_full_list():
    mgr = SystemManager()
    results = mgr.proc_full_list()
    assert len(results) > 0
    assert "pid" in results[0]
    assert "path" in results[0]
