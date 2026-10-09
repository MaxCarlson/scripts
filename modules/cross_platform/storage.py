"""Read-only storage media classification for filesystem paths."""

import ctypes
import os
import platform
import plistlib
import re
import subprocess
from enum import Enum
from pathlib import Path
from typing import NamedTuple, Optional, Tuple, Union


class StorageMediaKind(str, Enum):
    """Portable storage categories suitable for conservative policy decisions."""

    SOLID_STATE = "solid_state"
    ROTATIONAL = "rotational"
    UNKNOWN = "unknown"


class StorageMedia(NamedTuple):
    """Classification result for the storage backing a path."""

    kind: StorageMediaKind
    path: str
    detail: str

    @property
    def is_ssd(self) -> Optional[bool]:
        if self.kind == StorageMediaKind.SOLID_STATE:
            return True
        if self.kind == StorageMediaKind.ROTATIONAL:
            return False
        return None


def _existing_path(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def _windows_volume_device(path: str) -> Optional[str]:
    match = re.match(r"^([A-Za-z]):(?:[\\/]|$)", path)
    return rf"\\.\{match.group(1).upper()}:" if match else None


def _windows_seek_penalty(device: str) -> Tuple[Optional[bool], str]:
    """Return the Windows storage seek-penalty flag without requiring elevation."""

    from ctypes import wintypes

    class StoragePropertyQuery(ctypes.Structure):
        _fields_ = [
            ("PropertyId", wintypes.DWORD),
            ("QueryType", wintypes.DWORD),
            ("AdditionalParameters", ctypes.c_ubyte * 1),
        ]

    class DeviceSeekPenaltyDescriptor(ctypes.Structure):
        _fields_ = [
            ("Version", wintypes.DWORD),
            ("Size", wintypes.DWORD),
            ("IncursSeekPenalty", wintypes.BOOLEAN),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError) as exc:
        return None, f"Windows storage API unavailable: {exc}"

    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.DeviceIoControl.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.DeviceIoControl.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    share_read_write_delete = 0x00000001 | 0x00000002 | 0x00000004
    open_existing = 3
    invalid_handle = ctypes.c_void_p(-1).value
    handle = kernel32.CreateFileW(
        device,
        0,
        share_read_write_delete,
        None,
        open_existing,
        0,
        None,
    )
    if handle == invalid_handle:
        return None, f"cannot open {device}: Windows error {ctypes.get_last_error()}"

    try:
        query = StoragePropertyQuery()
        query.PropertyId = 7  # StorageDeviceSeekPenaltyProperty
        query.QueryType = 0  # PropertyStandardQuery
        descriptor = DeviceSeekPenaltyDescriptor()
        returned = wintypes.DWORD()
        ioctl_storage_query_property = 0x002D1400
        success = kernel32.DeviceIoControl(
            handle,
            ioctl_storage_query_property,
            ctypes.byref(query),
            ctypes.sizeof(query),
            ctypes.byref(descriptor),
            ctypes.sizeof(descriptor),
            ctypes.byref(returned),
            None,
        )
        if not success:
            return None, f"seek-penalty query failed: Windows error {ctypes.get_last_error()}"
        return bool(descriptor.IncursSeekPenalty), "Windows seek-penalty property"
    finally:
        kernel32.CloseHandle(handle)


def _windows_media(path: Path) -> Tuple[StorageMediaKind, str]:
    device = _windows_volume_device(str(path))
    if device is None:
        return StorageMediaKind.UNKNOWN, "path is not on a local drive-letter volume"
    penalty, detail = _windows_seek_penalty(device)
    if penalty is None:
        return StorageMediaKind.UNKNOWN, detail
    return (
        StorageMediaKind.ROTATIONAL if penalty else StorageMediaKind.SOLID_STATE,
        detail,
    )


def _decode_mount_field(value: str) -> str:
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _linux_mount_source(
    path: Path,
    mountinfo: Path = Path("/proc/self/mountinfo"),
    resolved_path: Optional[str] = None,
) -> Optional[str]:
    try:
        target = resolved_path or str(path.resolve())
        best: Tuple[int, str] = (-1, "")
        for line in mountinfo.read_text(encoding="utf-8").splitlines():
            left, separator, right = line.partition(" - ")
            if not separator:
                continue
            left_fields = left.split()
            right_fields = right.split()
            if len(left_fields) < 5 or len(right_fields) < 2:
                continue
            mount_point = _decode_mount_field(left_fields[4])
            if (
                target == mount_point
                or mount_point == "/"
                or target.startswith(mount_point.rstrip("/") + "/")
            ):
                if len(mount_point) > best[0]:
                    best = (len(mount_point), _decode_mount_field(right_fields[1]))
        return best[1] or None
    except OSError:
        return None


def _linux_rotational_flag(
    source: str,
    sys_class_block: Path = Path("/sys/class/block"),
    resolved_source: Optional[str] = None,
) -> Optional[bool]:
    try:
        source_path = resolved_source or str(Path(source).resolve())
        if not source_path.startswith("/dev/"):
            return None
        block = sys_class_block / source_path.rsplit("/", 1)[-1]
        candidates = [block / "queue" / "rotational"]
        try:
            candidates.append(block.resolve().parent / "queue" / "rotational")
        except OSError:
            pass
        for candidate in candidates:
            try:
                raw = candidate.read_text(encoding="ascii").strip()
            except OSError:
                continue
            if raw in {"0", "1"}:
                return raw == "1"
    except OSError:
        pass
    return None


def _linux_media(path: Path) -> Tuple[StorageMediaKind, str]:
    source = _linux_mount_source(path)
    if source is None:
        return StorageMediaKind.UNKNOWN, "mount source could not be resolved"
    rotational = _linux_rotational_flag(source)
    if rotational is None:
        return StorageMediaKind.UNKNOWN, f"rotational flag unavailable for {source}"
    return (
        StorageMediaKind.ROTATIONAL if rotational else StorageMediaKind.SOLID_STATE,
        f"Linux rotational flag for {source}",
    )


def _darwin_media(path: Path) -> Tuple[StorageMediaKind, str]:
    try:
        result = subprocess.run(
            ["diskutil", "info", "-plist", str(path)],
            check=False,
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return StorageMediaKind.UNKNOWN, "diskutil could not inspect the path"
        payload = plistlib.loads(result.stdout)
        solid_state = payload.get("SolidState")
        if isinstance(solid_state, bool):
            return (
                StorageMediaKind.SOLID_STATE if solid_state else StorageMediaKind.ROTATIONAL,
                "macOS diskutil SolidState property",
            )
    except (OSError, subprocess.TimeoutExpired, plistlib.InvalidFileException, ValueError) as exc:
        return StorageMediaKind.UNKNOWN, f"diskutil inspection failed: {exc}"
    return StorageMediaKind.UNKNOWN, "diskutil did not report SolidState"


def storage_media_for_path(
    path: Union[str, os.PathLike],
    system: Optional[str] = None,
) -> StorageMedia:
    """Classify the storage backing ``path`` without writing to the device.

    Unknown is returned for ambiguous, virtual, network, inaccessible, or
    unsupported storage. Callers should choose a conservative policy for it.
    """

    candidate = _existing_path(Path(path))
    os_name = (system or platform.system()).lower()
    if os_name == "windows":
        kind, detail = _windows_media(candidate)
    elif os_name == "linux":
        kind, detail = _linux_media(candidate)
    elif os_name == "darwin":
        kind, detail = _darwin_media(candidate)
    else:
        kind, detail = StorageMediaKind.UNKNOWN, f"unsupported platform: {os_name or 'unknown'}"
    return StorageMedia(kind, str(candidate), detail)
