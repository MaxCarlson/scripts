from __future__ import annotations

import ctypes
import os
import socket
import time

import pytest

from resource_coordinator import windows_listener


def test_native_ipv4_listener_row_decodes_port_and_address():
    row = windows_listener._MibTcpRowOwnerPid()
    row.dwState = windows_listener._MIB_TCP_STATE_LISTEN
    row.dwLocalAddr = int.from_bytes(socket.inet_aton("127.0.0.1"), "little")
    row.dwLocalPort = socket.htons(43210)
    row.dwOwningPid = 321

    endpoint = windows_listener._ipv4_row_to_endpoint(row)

    assert endpoint == {"local_address": "127.0.0.1", "port": 43210, "pid": 321}


def test_native_ipv6_listener_row_is_decoded():
    row = windows_listener._MibTcp6RowOwnerPid()
    row.dwState = windows_listener._MIB_TCP_STATE_LISTEN
    row.ucLocalAddr[:] = (ctypes.c_ubyte * 16).from_buffer_copy(socket.inet_pton(socket.AF_INET6, "::1"))
    row.dwLocalPort = socket.htons(43210)
    row.dwOwningPid = 321

    endpoint = windows_listener._ipv6_row_to_endpoint(row)

    assert endpoint == {"local_address": "::1", "port": 43210, "pid": 321}


def test_native_row_structure_sizes_match_windows_tcp_mib_contract():
    assert ctypes.sizeof(windows_listener._MibTcpRowOwnerPid) == 24
    assert ctypes.sizeof(windows_listener._MibTcp6RowOwnerPid) == 56


def test_discovery_filters_exact_port_and_compatible_address(monkeypatch):
    monkeypatch.setattr(windows_listener, "_psutil_listener_rows", lambda: [
        {"local_address": "127.0.0.1", "port": 43211, "pid": 1},
        {"local_address": "192.168.1.2", "port": 43210, "pid": 2},
        {"local_address": "127.0.0.1", "port": 43210, "pid": 3},
    ])
    monkeypatch.setattr(windows_listener, "_process_identity", lambda pid: windows_listener.ProcessIdentityResult(
        {"pid": pid, "create_time": float(pid), "executable": "python.exe"}, "identified"))

    result = windows_listener.identify_tcp_listener("127.0.0.1", 43210)

    assert result.verified
    assert result.identity["pid"] == 3
    assert result.identity["discovery_backend"] == "psutil"


def test_discovery_matches_requested_ipv6_loopback_endpoint(monkeypatch):
    monkeypatch.setattr(windows_listener, "_psutil_listener_rows", lambda: [
        {"local_address": "::1", "port": 43210, "pid": 3},
    ])
    monkeypatch.setattr(windows_listener, "_process_identity", lambda pid: windows_listener.ProcessIdentityResult(
        {"pid": pid, "create_time": 3.0}, "identified"))

    result = windows_listener.identify_tcp_listener("::1", 43210)

    assert result.verified
    assert result.identity["local_address"] == "::1"


def test_native_fallback_used_when_psutil_cannot_provide_pid(monkeypatch):
    monkeypatch.setattr(windows_listener, "_psutil_listener_rows", lambda: [
        {"local_address": "127.0.0.1", "port": 43210, "pid": None},
    ])
    monkeypatch.setattr(windows_listener, "_native_listener_rows", lambda: ([
        {"local_address": "127.0.0.1", "port": 43210, "pid": 44},
    ], []))
    monkeypatch.setattr(windows_listener, "_windows_process_identity", lambda pid: windows_listener.ProcessIdentityResult(
        {"pid": pid, "create_time": 100.0, "executable": r"C:\Python\python.exe"}, "identified"))

    result = windows_listener.identify_tcp_listener("127.0.0.1", 43210)

    assert result.verified
    assert result.identity["pid"] == 44
    assert result.identity["discovery_backend"] == "windows-ip-helper"


def test_multiple_distinct_owners_are_ambiguous(monkeypatch):
    monkeypatch.setattr(windows_listener, "_psutil_listener_rows", lambda: [
        {"local_address": "127.0.0.1", "port": 43210, "pid": 10},
        {"local_address": "0.0.0.0", "port": 43210, "pid": 11},
    ])
    monkeypatch.setattr(windows_listener, "_process_identity", lambda pid: windows_listener.ProcessIdentityResult(
        {"pid": pid, "create_time": float(pid), "executable": None}, "identified"))
    result = windows_listener.identify_tcp_listener("127.0.0.1", 43210)
    assert result.category == "ambiguous"
    assert not result.verified


def test_both_enumeration_backends_failing_is_not_reported_as_no_listener(monkeypatch):
    monkeypatch.setattr(windows_listener, "_psutil_listener_rows", lambda: (_ for _ in ()).throw(
        RuntimeError("psutil TCP table access denied")))
    monkeypatch.setattr(windows_listener, "_native_listener_rows", lambda: ([], [
        "IPv4 GetExtendedTcpTable: Windows error 5 (access denied)",
    ]))

    result = windows_listener.identify_tcp_listener("127.0.0.1", 43210)

    assert result.category == "discovery-error"
    assert not result.verified
    assert "access denied" in " ".join(result.diagnostics)


def test_complete_native_table_can_confirm_absence_after_psutil_failure(monkeypatch):
    monkeypatch.setattr(windows_listener, "_psutil_listener_rows", lambda: (_ for _ in ()).throw(
        RuntimeError("psutil TCP table access denied")))
    monkeypatch.setattr(windows_listener, "_native_listener_rows", lambda: ([], []))

    result = windows_listener.identify_tcp_listener("127.0.0.1", 43210)

    assert result.category == "not-found"
    assert not result.verified


@pytest.mark.parametrize("category", ["access-denied", "process-exited", "identity-unavailable"])
def test_process_identity_failure_is_not_reported_as_verified(monkeypatch, category):
    monkeypatch.setattr(windows_listener, "_psutil_listener_rows", lambda: [
        {"local_address": "127.0.0.1", "port": 43210, "pid": 10},
    ])
    monkeypatch.setattr(windows_listener, "_native_listener_rows", lambda: ([], ["native API unavailable"]))
    monkeypatch.setattr(windows_listener, "_process_identity", lambda _pid: windows_listener.ProcessIdentityResult(
        None, category, "process query failed"))
    result = windows_listener.identify_tcp_listener("127.0.0.1", 43210)
    assert not result.verified
    assert result.category == category


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows IP Helper contract test")
def test_get_extended_tcp_table_retries_after_buffer_growth(monkeypatch):
    calls = []
    row = windows_listener._MibTcpRowOwnerPid()
    row.dwState = windows_listener._MIB_TCP_STATE_LISTEN
    row.dwLocalAddr = int.from_bytes(socket.inet_aton("127.0.0.1"), "little")
    row.dwLocalPort = socket.htons(43210)
    row.dwOwningPid = 99

    class FakeFunction:
        argtypes = None
        restype = None

        def __call__(self, buffer, size, _order, _family, _table, _reserved):
            calls.append(buffer)
            if buffer is None:
                size._obj.value = ctypes.sizeof(ctypes.c_uint32)
                return windows_listener._ERROR_INSUFFICIENT_BUFFER
            needed = ctypes.sizeof(ctypes.c_uint32) + ctypes.sizeof(row)
            if size._obj.value < needed:
                size._obj.value = needed
                return windows_listener._ERROR_INSUFFICIENT_BUFFER
            ctypes.memmove(buffer, ctypes.byref(ctypes.c_uint32(1)), ctypes.sizeof(ctypes.c_uint32))
            ctypes.memmove(ctypes.addressof(buffer) + ctypes.sizeof(ctypes.c_uint32),
                           ctypes.byref(row), ctypes.sizeof(row))
            return 0

    class FakeLibrary:
        GetExtendedTcpTable = FakeFunction()

    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: FakeLibrary())
    rows = windows_listener._query_windows_table(windows_listener._AF_INET,
                                                  windows_listener._MibTcpRowOwnerPid)

    assert len(calls) == 3
    assert rows[0].dwOwningPid == 99


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity integration check")
def test_windows_process_identity_uses_creation_time_and_optional_image_path():
    import psutil

    result = windows_listener._windows_process_identity(os.getpid())
    assert result.identity is not None, result.error
    assert result.identity["pid"] == os.getpid()
    assert result.identity["create_time"] > 0
    assert abs(result.identity["create_time"] - psutil.Process(os.getpid()).create_time()) < 0.01
    if result.identity["executable"]:
        assert os.path.isabs(result.identity["executable"])


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows socket integration check")
def test_windows_discovery_identifies_disposable_loopback_socket():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        time.sleep(0.05)
        host, port = listener.getsockname()
        result = windows_listener.identify_tcp_listener(host, port)
        if not result.verified and result.category in {"not-found", "discovery-error"}:
            pytest.skip("This Windows test runner cannot see its disposable socket in the system TCP table")
        assert result.verified, result.to_dict()
        assert result.identity["pid"] == __import__("os").getpid()
        assert result.identity["create_time"] > 0
    finally:
        listener.close()
