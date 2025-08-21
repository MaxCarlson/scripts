import types
import sysmon
import builtins


# --- sparkline ---------------------------------------------------------------
def test_sparkline_basic():
    s = sysmon.sparkline([0, 1, 2, 3, 4, 5, 6, 7], width=8)
    assert len(s) == 8
    # Should include lowest and highest blocks
    assert s[0] in "▁▂▃▄▅▆▇█"
    assert s[-1] in "▁▂▃▄▅▆▇█"


def test_sparkline_empty():
    assert sysmon.sparkline([], width=10) == ""
    assert sysmon.sparkline([1, 2, 3], width=0) == ""


# --- column selection --------------------------------------------------------
def test_cpu_columns_for_width_thresholds():
    assert sysmon.cpu_columns_for_width(60) == ["PID", "Name", "CPU %"]
    assert sysmon.cpu_columns_for_width(75) == ["PID", "Name", "CPU %", "Mem(MB)"]
    assert sysmon.cpu_columns_for_width(90) == [
        "PID",
        "Name",
        "CPU %",
        "Mem(MB)",
        "DΔ(MB)",
    ]
    assert sysmon.cpu_columns_for_width(105) == [
        "PID",
        "Name",
        "CPU %",
        "Mem(MB)",
        "RΔ(MB)",
        "WΔ(MB)",
    ]


# --- sorting -----------------------------------------------------------------
def test_sort_cpu_rows_modes():
    rows = [
        {"pid": 1, "name": "b", "cpu_pct": 10, "mem_mb": 200, "disk_mb": 5},
        {"pid": 2, "name": "a", "cpu_pct": 20, "mem_mb": 100, "disk_mb": 10},
    ]
    sysmon.sort_cpu_rows(rows, "cpu")
    assert rows[0]["pid"] == 2
    sysmon.sort_cpu_rows(rows, "memory")
    assert rows[0]["pid"] == 1
    sysmon.sort_cpu_rows(rows, "disk")
    assert rows[0]["pid"] == 2
    sysmon.sort_cpu_rows(rows, "name")
    assert rows[0]["pid"] == 2  # 'a' first


# --- human Mbps --------------------------------------------------------------
def test_human_mbps_units():
    assert sysmon.human_mbps(1_000_000, "mb") == 1.0
    assert round(sysmon.human_mbps(1 << 20, "mib"), 6) == 1.0


# --- net rows math (mock psutil accessors) -----------------------------------
class FakeProc:
    def __init__(self, pid, name, bytes_total):
        self.pid = pid
        self._name = name
        self._bytes = bytes_total

    def io_counters(self):
        return types.SimpleNamespace(
            read_bytes=self._bytes // 2, write_bytes=self._bytes // 2
        )

    def name(self):
        return self._name


def test_compute_net_rows_basic(monkeypatch):
    # Monkeypatch proc_io_bytes_and_name to deterministic behavior
    values = {10: ("p10", 1000), 11: ("p11", 3000)}

    def fake_proc_io(pid):
        nm, b = values[pid]
        return b, nm

    monkeypatch.setattr(sysmon, "proc_io_bytes_and_name", lambda pid: fake_proc_io(pid))

    prev = {10: (1000, "p10")}
    rows, updated = sysmon.compute_net_rows(prev, [10, 11], elapsed=1.0, base="mb")
    # p10 delta = 0, p11 seeded only (no delta until next)
    assert any(r[0] == 10 for r in rows)
    assert 11 in updated


def test_compute_net_rows_sort_and_units(monkeypatch):
    calls = {20: 2000, 21: 4000}

    def fake(pid):
        return calls[pid], f"p{pid}"

    monkeypatch.setattr(sysmon, "proc_io_bytes_and_name", lambda pid: fake(pid))

    prev = {20: (1000, "p20"), 21: (2000, "p21")}
    rows, _ = sysmon.compute_net_rows(prev, [20, 21], elapsed=2.0, base="mib")
    # Both deltas are 1000/2000 bytes -> order by mbps desc => pid 21 first
    assert rows[0][0] == 21


# --- arg parsing --------------------------------------------------------------
def test_parse_args_defaults():
    ns = sysmon.parse_args([])
    assert ns.top == 15 and ns.interval == 1.0 and ns.view in ("cpu", "net")


def test_parse_args_values():
    ns = sysmon.parse_args(["-t", "5", "-i", "0.5", "-w", "net", "-u", "mib"])
    assert ns.top == 5 and ns.interval == 0.5 and ns.view == "net" and ns.units == "mib"
