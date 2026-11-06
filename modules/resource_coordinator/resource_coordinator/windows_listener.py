"""Verifiable TCP listener discovery with a native Windows IP Helper fallback."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import ipaddress
import os
import socket
import struct
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import psutil

_AF_INET = 2
_AF_INET6 = 23
_TCP_TABLE_OWNER_PID_LISTENER = 3
_MIB_TCP_STATE_LISTEN = 2
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_NO_DATA = 232
_RETRIES = 4


class _MibTcpRowOwnerPid(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "dwState", "dwLocalAddr", "dwLocalPort", "dwRemoteAddr", "dwRemotePort", "dwOwningPid",
    )]


class _MibTcpTableOwnerPid(ctypes.Structure):
    _fields_ = [("dwNumEntries", ctypes.c_uint32), ("table", _MibTcpRowOwnerPid * 1)]


class _MibTcp6RowOwnerPid(ctypes.Structure):
    _fields_ = [
        ("ucLocalAddr", ctypes.c_uint8 * 16), ("dwLocalScopeId", ctypes.c_uint32),
        ("dwLocalPort", ctypes.c_uint32), ("ucRemoteAddr", ctypes.c_uint8 * 16),
        ("dwRemoteScopeId", ctypes.c_uint32), ("dwRemotePort", ctypes.c_uint32),
        ("dwState", ctypes.c_uint32), ("dwOwningPid", ctypes.c_uint32),
    ]


class _MibTcp6TableOwnerPid(ctypes.Structure):
    _fields_ = [("dwNumEntries", ctypes.c_uint32), ("table", _MibTcp6RowOwnerPid * 1)]


@dataclass(frozen=True)
class ProcessIdentityResult:
    identity: Optional[Dict[str, Any]]
    category: str
    error: Optional[str] = None


@dataclass(frozen=True)
class ListenerIdentityResult:
    category: str
    identity: Optional[Dict[str, Any]]
    diagnostics: Tuple[str, ...] = ()
    candidates: Tuple[Dict[str, Any], ...] = ()

    @property
    def verified(self) -> bool:
        return self.category == "identified" and self.identity is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "verified": self.verified,
            "identity": self.identity,
            "diagnostics": list(self.diagnostics),
            "candidates": list(self.candidates),
        }


def _port_from_network_dword(value: int) -> int:
    """Windows stores the network-order WORD in the low bytes of a DWORD."""
    return socket.ntohs(int(value) & 0xFFFF)


def _ipv4_row_to_endpoint(row: _MibTcpRowOwnerPid) -> Dict[str, Any]:
    return {
        "local_address": socket.inet_ntoa(struct.pack("<I", int(row.dwLocalAddr))),
        "port": _port_from_network_dword(row.dwLocalPort),
        "pid": int(row.dwOwningPid),
    }


def _ipv6_row_to_endpoint(row: _MibTcp6RowOwnerPid) -> Dict[str, Any]:
    return {
        "local_address": socket.inet_ntop(socket.AF_INET6, bytes(row.ucLocalAddr)),
        "port": _port_from_network_dword(row.dwLocalPort),
        "pid": int(row.dwOwningPid),
    }


def _parse_table(buffer: Any, row_type: Any) -> List[Any]:
    count = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint32)).contents.value
    offset = ctypes.sizeof(ctypes.c_uint32)
    row_size = ctypes.sizeof(row_type)
    return [row_type.from_buffer_copy(ctypes.string_at(ctypes.addressof(buffer) + offset + i * row_size, row_size))
            for i in range(count)]


def _query_windows_table(address_family: int, row_type: Any) -> List[Any]:
    if os.name != "nt":
        raise OSError("native IP Helper API is available only on Windows")
    iphlpapi = ctypes.WinDLL("iphlpapi.dll")
    get_table = iphlpapi.GetExtendedTcpTable
    get_table.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int,
                          ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    get_table.restype = ctypes.c_uint32
    required = ctypes.c_uint32(0)
    result = get_table(None, ctypes.byref(required), 0, address_family,
                       _TCP_TABLE_OWNER_PID_LISTENER, 0)
    if result not in (_ERROR_INSUFFICIENT_BUFFER, _ERROR_NO_DATA):
        raise OSError(result, f"GetExtendedTcpTable size query failed with Windows error {result}")
    if result == _ERROR_NO_DATA:
        return []
    for _attempt in range(_RETRIES):
        buffer = ctypes.create_string_buffer(required.value)
        result = get_table(buffer, ctypes.byref(required), 0, address_family,
                           _TCP_TABLE_OWNER_PID_LISTENER, 0)
        if result == 0:
            return _parse_table(buffer, row_type)
        if result == _ERROR_NO_DATA:
            return []
        if result != _ERROR_INSUFFICIENT_BUFFER:
            raise OSError(result, f"GetExtendedTcpTable failed with Windows error {result}")
    raise OSError(_ERROR_INSUFFICIENT_BUFFER, "GetExtendedTcpTable buffer kept growing after bounded retries")


def _native_listener_rows() -> Tuple[List[Dict[str, Any]], List[str]]:
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    for family, row_type, convert, label in (
        (_AF_INET, _MibTcpRowOwnerPid, _ipv4_row_to_endpoint, "IPv4"),
        (_AF_INET6, _MibTcp6RowOwnerPid, _ipv6_row_to_endpoint, "IPv6"),
    ):
        try:
            for row in _query_windows_table(family, row_type):
                if row.dwState == _MIB_TCP_STATE_LISTEN:
                    rows.append(convert(row))
        except OSError as exc:
            errors.append(f"{label} GetExtendedTcpTable: {exc}")
        except Exception as exc:  # ctypes/API errors are surfaced as diagnostic evidence, never success.
            errors.append(f"{label} GetExtendedTcpTable: {type(exc).__name__}: {exc}")
    return rows, errors


def _psutil_listener_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for connection in psutil.net_connections(kind="inet"):
        if connection.status != psutil.CONN_LISTEN or not connection.laddr:
            continue
        rows.append({"local_address": connection.laddr.ip, "port": connection.laddr.port, "pid": connection.pid})
    return rows


def _windows_process_identity(pid: int) -> ProcessIdentityResult:
    if os.name != "nt":
        return ProcessIdentityResult(None, "identity-unavailable", "native process query is only available on Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_void_p, ctypes.c_void_p]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                                     ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    process = kernel32.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        error = ctypes.get_last_error()
        category = "access-denied" if error == 5 else "process-exited" if error in (6, 87) else "identity-unavailable"
        return ProcessIdentityResult(None, category, f"OpenProcess failed with Windows error {error}")
    try:
        creation, exit_time, kernel_time, user_time = (ctypes.wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(process, ctypes.byref(creation), ctypes.byref(exit_time),
                                        ctypes.byref(kernel_time), ctypes.byref(user_time)):
            error = ctypes.get_last_error()
            category = "access-denied" if error == 5 else "process-exited" if error in (6, 87) else "identity-unavailable"
            return ProcessIdentityResult(None, category, f"GetProcessTimes failed with Windows error {error}")
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        create_time = (ticks - 116444736000000000) / 10_000_000
        size = ctypes.c_uint32(32768)
        image = ctypes.create_unicode_buffer(size.value)
        executable: Optional[str] = None
        image_error: Optional[str] = None
        if kernel32.QueryFullProcessImageNameW(process, 0, image, ctypes.byref(size)):
            executable = image.value
        else:
            error = ctypes.get_last_error()
            image_error = f"QueryFullProcessImageNameW failed with Windows error {error}"
        return ProcessIdentityResult({"pid": pid, "create_time": create_time, "executable": executable},
                                     "identified", image_error)
    finally:
        kernel32.CloseHandle(process)


def _process_identity(pid: int) -> ProcessIdentityResult:
    try:
        process = psutil.Process(pid)
        identity = {"pid": pid, "create_time": process.create_time()}
        executable_error: Optional[str] = None
        try:
            identity["executable"] = process.exe()
        except psutil.AccessDenied as exc:
            identity["executable"] = None
            executable_error = f"executable path access denied: {exc}"
        return ProcessIdentityResult(identity, "identified", executable_error)
    except psutil.NoSuchProcess as exc:
        if os.name == "nt":
            return _windows_process_identity(pid)
        return ProcessIdentityResult(None, "process-exited", str(exc))
    except psutil.AccessDenied as exc:
        if os.name == "nt":
            native = _windows_process_identity(pid)
            if native.identity:
                return native
            return native
        return ProcessIdentityResult(None, "access-denied", str(exc))
    except (psutil.Error, OSError) as exc:
        if os.name == "nt":
            native = _windows_process_identity(pid)
            if native.identity:
                return native
        return ProcessIdentityResult(None, "identity-unavailable", f"{type(exc).__name__}: {exc}")


def _address_matches(requested: str, local: str) -> bool:
    try:
        requested_ip = ipaddress.ip_address(requested)
        local_ip = ipaddress.ip_address(local)
    except ValueError:
        return requested.casefold() == local.casefold() or local in {"0.0.0.0", "::"}
    if local_ip == requested_ip:
        return True
    if local_ip.is_unspecified:
        return local_ip.version == requested_ip.version
    if requested_ip.version == 4 and local_ip.version == 6 and local_ip.ipv4_mapped == requested_ip:
        return True
    return False


def _filter_endpoints(rows: Iterable[Dict[str, Any]], host: str, port: int) -> List[Dict[str, Any]]:
    return [row for row in rows if int(row.get("port", -1)) == port and
            isinstance(row.get("local_address"), str) and _address_matches(host, row["local_address"])]


def identify_tcp_listener(host: str, port: int) -> ListenerIdentityResult:
    """Identify all compatible listeners and require one verifiable process owner."""
    diagnostics: List[str] = []
    discovery_failed = False
    found_endpoints: List[Tuple[str, Dict[str, Any]]] = []
    try:
        primary = _psutil_listener_rows()
        matches = _filter_endpoints(primary, host, port)
        found_endpoints.extend(("psutil", row) for row in matches)
        if not matches:
            diagnostics.append("psutil: no matching listener")
    except Exception as exc:
        discovery_failed = True
        diagnostics.append(f"psutil: {type(exc).__name__}: {exc}")

    identity_rows: List[Dict[str, Any]] = []
    identity_failures: List[str] = []
    identity_categories: List[str] = []
    for backend, endpoint in found_endpoints:
        pid = endpoint.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            identity_failures.append(f"{backend}: listener {endpoint['local_address']}:{port} returned no usable PID")
            continue
        result = _process_identity(pid)
        if result.identity and isinstance(result.identity.get("create_time"), (int, float)):
            identity_rows.append({**endpoint, **result.identity, "discovery_backend": backend,
                                  "verification": "pid-and-creation-time"})
            if result.error:
                diagnostics.append(f"{backend}: {result.error}")
        else:
            identity_categories.append(result.category)
            identity_failures.append(f"{backend}: PID {pid} {result.category}: {result.error or 'identity unavailable'}")

    unique = {(item["pid"], round(float(item["create_time"]), 3)): item for item in identity_rows}
    if len(unique) == 1:
        identity = next(iter(unique.values()))
        return ListenerIdentityResult("identified", identity, tuple(diagnostics))
    if len(unique) > 1:
        return ListenerIdentityResult("ambiguous", None, tuple(diagnostics + ["multiple process identities own matching listener endpoints"]),
                                      tuple(unique.values()))

    if os.name == "nt":
        try:
            native_rows, native_errors = _native_listener_rows()
            diagnostics.extend(native_errors)
            # A complete native table is authoritative when the broader psutil
            # query is unavailable; only native enumeration errors leave the
            # Windows fallback itself incomplete.
            discovery_failed = bool(native_errors)
            matches = _filter_endpoints(native_rows, host, port)
            if not matches:
                diagnostics.append("Windows IP Helper: no matching listening endpoint")
            for endpoint in matches:
                pid = endpoint.get("pid")
                if not isinstance(pid, int) or pid <= 0:
                    identity_failures.append("Windows IP Helper: matching endpoint returned no usable PID")
                    continue
                result = _windows_process_identity(pid)
                if result.identity and isinstance(result.identity.get("create_time"), (int, float)):
                    identity_rows.append({**endpoint, **result.identity, "discovery_backend": "windows-ip-helper",
                                          "verification": "pid-and-creation-time"})
                    if result.error:
                        diagnostics.append(f"Windows process identity: {result.error}")
                else:
                    identity_categories.append(result.category)
                    identity_failures.append(f"Windows process identity: PID {pid} {result.category}: "
                                              f"{result.error or 'identity unavailable'}")
        except Exception as exc:
            discovery_failed = True
            diagnostics.append(f"Windows IP Helper: {type(exc).__name__}: {exc}")

    unique = {(item["pid"], round(float(item["create_time"]), 3)): item for item in identity_rows}
    if len(unique) == 1:
        return ListenerIdentityResult("identified", next(iter(unique.values())), tuple(diagnostics))
    if len(unique) > 1:
        return ListenerIdentityResult("ambiguous", None,
                                      tuple(diagnostics + ["multiple process identities own matching listener endpoints"]),
                                      tuple(unique.values()))
    diagnostics.extend(identity_failures)
    if found_endpoints or identity_failures:
        category = next((item for item in identity_categories if item in {"access-denied", "process-exited"}),
                        "identity-unavailable")
        return ListenerIdentityResult(category, None, tuple(diagnostics))
    if discovery_failed:
        return ListenerIdentityResult("discovery-error", None, tuple(diagnostics))
    return ListenerIdentityResult("not-found", None, tuple(diagnostics))
