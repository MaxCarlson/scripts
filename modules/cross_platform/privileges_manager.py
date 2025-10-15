# cross_platform/privileges_manager.py
from __future__ import annotations

import os
import sys
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, List

from .system_utils import SystemUtils
from .debug_utils import write_debug


@dataclass(frozen=True)
class PermissionsPrereqReport:
    """
    Lightweight report describing whether we can perform permission/ACL actions
    without additional elevation or tooling, and what is missing if not.

    Fields:
        ok: All required capabilities are present.
        needs_admin: Elevation (admin/root) is required for the requested actions.
        missing_tools: Binaries we need but that are not present (e.g., setfacl/getfacl).
        reasons: Human-readable strings explaining constraints.
    """
    ok: bool
    needs_admin: bool
    missing_tools: List[str]
    reasons: List[str]


class PrivilegesManager(SystemUtils):
    """
    Checks and ensures that the script is run with administrative privileges.
    Also supplies helper utilities used by permission/ACL tooling to decide whether
    elevation and/or external tools are needed prior to applying changes.
    """

    # ---------------------------
    # Core admin checks (existing behavior, preserved)
    # ---------------------------
    def require_admin(self) -> None:
        """
        Raise PermissionError if the current process is not elevated.

        Windows: uses IsUserAnAdmin()
        Linux/macOS: requires euid == 0
        """
        write_debug("Checking for administrative privileges...", channel="Debug")
        if self.os_name == "windows":
            try:
                import ctypes
                if not ctypes.windll.shell32.IsUserAnAdmin():
                    write_debug("Not running as administrator on Windows.", channel="Error")
                    raise PermissionError("Administrator privileges required.")
                write_debug("Running as administrator on Windows.", channel="Debug")
            except Exception as e:
                write_debug(f"Error while checking admin privileges on Windows: {e}", channel="Error")
                # For safety and test compatibility, fail closed.
                raise PermissionError("Administrator privileges required.")
        elif self.os_name in ["linux", "darwin"]:
            if not hasattr(os, "geteuid") or os.geteuid() != 0:
                write_debug("Not running as root on Unix-like OS.", channel="Error")
                raise PermissionError("Administrator (root) privileges required.")
            write_debug("Running as root on Unix-like OS.", channel="Debug")
        else:
            write_debug("Unsupported OS for admin privilege check.", channel="Error")
            raise PermissionError("Unsupported OS for privilege checking.")

    def is_admin(self) -> bool:
        """
        Return True if currently elevated (admin/root), else False.
        """
        try:
            if self.os_name == "windows":
                import ctypes
                return bool(ctypes.windll.shell32.IsUserAnAdmin())
            elif self.os_name in ["linux", "darwin"]:
                return hasattr(os, "geteuid") and os.geteuid() == 0
        except Exception as e:
            write_debug(f"is_admin check failed: {e}", channel="Warning")
        return False

    # ---------------------------
    # Optional self-elevation (Windows convenience)
    # ---------------------------
    def try_elevate_self_windows(self, prompt: str | None = None) -> bool:
        """
        Attempt to relaunch the current Python script elevated on Windows via ShellExecute 'runas'.
        Returns True if an elevation request was issued (caller should exit), False otherwise.

        Note: This does not return from the elevated child. Caller should `sys.exit(0)` after True.
        """
        if self.os_name != "windows":
            return False
        if self.is_admin():
            return False
        try:
            import ctypes
            from ctypes import wintypes

            SHELLEXECUTEINFO = ctypes.Structure
            SEE_MASK_NOCLOSEPROCESS = 0x00000040

            class SHELLEXECUTEINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", wintypes.LPVOID),
                    ("lpClass", wintypes.LPCWSTR),
                    ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD),
                    ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE),
                ]

            sei = SHELLEXECUTEINFO()
            sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
            sei.fMask = SEE_MASK_NOCLOSEPROCESS
            sei.hwnd = None
            sei.lpVerb = "runas"
            sei.lpFile = sys.executable
            # Pass through current argv as parameters
            sei.lpParameters = " ".join(f'"{a}"' for a in sys.argv)
            sei.lpDirectory = None
            sei.nShow = 1  # SW_SHOWNORMAL

            if prompt:
                write_debug(prompt, channel="Information")

            if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
                raise OSError("ShellExecuteExW failed")

            write_debug("Elevation requested; elevated process launched (if user accepted).", channel="Information")
            return True
        except Exception as e:
            write_debug(f"Windows elevation attempt failed: {e}", channel="Error")
            return False

    # ---------------------------
    # Tool presence & basic capability checks
    # ---------------------------
    @staticmethod
    def _which(cmd: str) -> bool:
        return shutil.which(cmd) is not None

    def has_icacls(self) -> bool:
        return self.os_name == "windows" and self._which("icacls")

    def has_getfacl(self) -> bool:
        return self.os_name in ["linux", "darwin"] and self._which("getfacl")

    def has_setfacl(self) -> bool:
        return self.os_name in ["linux", "darwin"] and self._which("setfacl")

    def can_chmod(self) -> bool:
        # chmod is a syscall; assume True. os.chmod might still fail on permissions.
        return True

    def can_chown(self) -> bool:
        # chown generally requires root. Some systems allow changing group to a supplementary group.
        return self.is_admin()

    def is_owner(self, path: Path) -> bool:
        try:
            st = path.stat()
            return hasattr(os, "getuid") and os.getuid() == st.st_uid
        except Exception:
            return False

    # ---------------------------
    # Permissions/ACL prereq assessment (for use by tools like perm_clone.py)
    # ---------------------------
    def assess_permissions_prereqs(
        self,
        target: Path,
        *,
        will_change_owner: bool,
        will_change_group: bool,
        will_change_mode: bool,
        will_change_acl: bool,
    ) -> PermissionsPrereqReport:
        """
        Determine whether we can perform the requested changes on 'target' without elevation
        and whether required userland tools are present.

        Heuristics:
        - Windows:
            * Mode/owner mapped via icacls operations.
            * Owner change often requires admin; ACL edits may succeed for owned paths.
        - POSIX:
            * chmod typically OK for files you own; chown requires root.
            * setfacl/getfacl must be present for ACL copying; modifying ACL on a file you own
              is typically allowed; some ACLs or default ACLs on directories may still require extra perms.
        """
        reasons: List[str] = []
        missing: List[str] = []
        needs_admin = False

        if not target.exists():
            reasons.append("Target does not exist.")
            return PermissionsPrereqReport(False, False, [], reasons)

        if self.os_name == "windows":
            if not self.has_icacls():
                missing.append("icacls")
            # Owner change usually requires admin
            if will_change_owner and not self.is_admin():
                needs_admin = True
                reasons.append("Changing owner on Windows generally requires Administrator.")
            # ACL changes can typically be done if you have rights on the object
            # We can't perfectly know without trying; if not admin and not owner, warn.
            if will_change_acl and not (self.is_admin()):
                # Rough heuristic: not admin; may still succeed if current user has WRITE_DAC
                reasons.append("ACL edits without Administrator will depend on current rights (best effort).")
            # Mode is represented via ACL; covered by icacls.
            ok = (len(missing) == 0) and (not needs_admin or self.is_admin())
            return PermissionsPrereqReport(ok, needs_admin, missing, reasons)

        elif self.os_name in ["linux", "darwin"]:
            # Tools
            if will_change_acl:
                if not self.has_getfacl():
                    missing.append("getfacl")
                if not self.has_setfacl():
                    missing.append("setfacl")

            # Ownership
            if (will_change_owner or will_change_group) and not self.can_chown():
                needs_admin = True
                reasons.append("Changing owner/group requires root on POSIX.")

            # chmod: OK if you own the file or are root; otherwise may fail.
            if will_change_mode and not (self.is_admin() or self.is_owner(target)):
                reasons.append("chmod may fail if you are not the owner of the target.")

            ok = (len(missing) == 0) and (not needs_admin)
            return PermissionsPrereqReport(ok, needs_admin, missing, reasons)

        else:
            reasons.append(f"Unsupported OS '{self.os_name}' for permission/ACL operations.")
            return PermissionsPrereqReport(False, False, [], reasons)

    # ---------------------------
    # Convenience: summarize missing prerequisites
    # ---------------------------
    def format_prereq_report(self, report: PermissionsPrereqReport) -> str:
        lines: List[str] = []
        lines.append(f"Prerequisites OK: {report.ok}")
        if report.missing_tools:
            lines.append("Missing tools: " + ", ".join(report.missing_tools))
        if report.needs_admin:
            lines.append("Needs elevation: Administrator/root required for requested changes.")
        for r in report.reasons:
            lines.append(f"- {r}")
        return "\n".join(lines)

    # ---------------------------
    # Simple helper for scripts that want a one-liner guard
    # ---------------------------
    def ensure_or_explain_permissions(
        self,
        target: Path,
        *,
        will_change_owner: bool = False,
        will_change_group: bool = False,
        will_change_mode: bool = False,
        will_change_acl: bool = False,
        auto_elevate_windows: bool = False,
    ) -> None:
        """
        Either confirm we can proceed, or raise PermissionError with a helpful message.
        Optionally attempt Windows self-elevation when not elevated.

        This is intended to be called prior to applying permissions in tools like perm_clone.py.
        """
        report = self.assess_permissions_prereqs(
            target,
            will_change_owner=will_change_owner,
            will_change_group=will_change_group,
            will_change_mode=will_change_mode,
            will_change_acl=will_change_acl,
        )
        write_debug(self.format_prereq_report(report), channel="Information")

        if report.ok:
            return

        if self.os_name == "windows" and report.needs_admin and auto_elevate_windows:
            if self.try_elevate_self_windows("Administrator privileges are required; requesting elevation..."):
                # Parent should exit after returning True; we raise to stop the current flow.
                raise PermissionError("Elevation requested. Please continue in the elevated window.")

        # Compose actionable error
        msg_lines = ["Cannot proceed due to missing prerequisites."]
        if report.missing_tools:
            msg_lines.append("Missing tools: " + ", ".join(report.missing_tools))
        if report.needs_admin:
            msg_lines.append("Requires Administrator/root privileges.")
        if report.reasons:
            msg_lines.extend(report.reasons)
        raise PermissionError("\n".join(msg_lines))
