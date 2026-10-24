from types import SimpleNamespace

import psutil

from resource_metrics import system


def test_system_wrappers_and_rate(monkeypatch):
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None, percpu=False: [10.0, 20.0] if percpu else 15.0)
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 8 if logical else 4)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(used=3, available=7, total=10, percent=30.0))
    assert system.cpu_percent() == 15.0
    assert system.cpu_percent(per_cpu=True) == [10.0, 20.0]
    assert system.cpu_count(logical=False) == 4
    assert system.memory_stats() == {"used": 3, "available": 7, "total": 10, "percent": 30.0}
    assert system.rate(12, 20, 2) == 4.0
    assert system.rate(20, 12, 2) == 0.0
    assert system.rate(0, 1, 0) is None


def test_unavailable_memory_is_none(monkeypatch):
    monkeypatch.setattr(psutil, "virtual_memory", lambda: (_ for _ in ()).throw(OSError("unavailable")))
    assert system.memory_stats() is None
