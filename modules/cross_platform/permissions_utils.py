#!/usr/bin/env python3
"""
cross_platform.permissions_utils

Cross-platform permissions inspector/applier and helpers for CLI tools.

Enhancements (this version):
- JSON (de)serialization helpers for PermissionsTemplate (save/load).
- Tree drift scanning: compare a directory tree against a reference (root or provided template).
- Windows inheritance inspection utility.
- Safer, clearer normalization for diffs.
- Public API extended (non-breaking): save_template, load_template, scan_drift, list_non_inheriting_windows.

Notes
- Windows: uses `icacls` for ACLs and owner; optional inheritance toggling.
- POSIX: uses `getfacl`/`setfacl` when available, else falls back to mode/owner/group.
- Diffs are conservative: they show missing/present entries and ownership/mode changes.

Public API (do not rename/remove without approval):
- class PermissionsTemplate
- read_permissions(src_path: str) -> PermissionsTemplate
- diff_permissions(template: PermissionsTemplate, target_path: str) -> dict
- apply_permissions(template: PermissionsTemplate, target_path: str, *, clear_existing=False,
                    owner: str | None = None, group: str | None = None, no_acl: bool = False,
                    disable_inheritance: bool | None = None) -> None
- save_template(template: PermissionsTemplate, out_path: str) -> None
- load_template(in_path: str) -> PermissionsTemplate
- scan_drift(root_path: str, *, reference: PermissionsTemplate | None = None,
             max_depth: int = 0, follow_symlinks: bool = False) -> list[tuple[str, dict]]
- list_non_inheriting_windows(root_path: str, *, max_depth: int = 0, follow_symlinks: bool = False) -> list[str]
"""

from __future__ import annotations

import json
import os
import stat
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Literal, Iterable

from .system_utils import SystemUtils
from .debug_utils import write_debug


@dataclass
class PermissionsTemplate:
    """
    Backend-neutral wrapper for a captured permission set.

    Fields:
        backend: "windows_icacls" | "posix_acl" | "posix_mode"
        payload: str   -> textual representation to apply/compare (icacls/getfacl output)
        mode: Optional[int] -> POSIX mode bits (when available)
        owner: Optional[str] -> owner name (platform-dependent)
        group: Optional[str] -> group name (platform-dependent)
        source_kind: "file" | "dir"
        meta: Optional[dict] -> free-form metadata (e.g., description)
    """
    backend: Literal["windows_icacls", "posix_acl", "posix_mode"]
    payload: str
    mode: Optional[int]
    owner: Optional[str]
    group: Optional[str]
    source_kind: Literal["file", "dir"]
    meta: Optional[dict] = None


class PermissionsUtils(SystemUtils):
    """
    Implementation helper class. End-users should call module-level functions.
    """

    # ---------- Probe utilities ----------
    @staticmethod
    def _which(cmd: str) -> bool:
        return shutil.which(cmd) is not None

    def _is_posix(self) -> bool:
        return self.os_name in ("linux", "darwin")

    # ---------- Capture ----------
    def capture(self, src: Path) -> PermissionsTemplate:
        src = src.resolve()
        if not src.exists():
            raise FileNotFoundError(f"Source path does not exist: {src}")

        source_kind = "dir" if src.is_dir() else "file"
        write_debug(f"Capturing permissions from {src} ({source_kind}) on {self.os_name}", channel="Information")

        if self.os_name == "windows":
            return self._capture_windows_icacls(src, source_kind)
        else:
            return self._capture_posix(src, source_kind)

    def _capture_windows_icacls(self, src: Path, source_kind: str) -> PermissionsTemplate:
        try:
            proc = subprocess.run(["icacls", str(src)], capture_output=True, text=True, check=True)
            payload = proc.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"icacls failed on {src}: {e.stderr or e.stdout}") from e

        owner = self._get_owner_windows(src)
        group = None  # Windows: no single "group owner" like POSIX

        return PermissionsTemplate(
            backend="windows_icacls",
            payload=payload,
            mode=None,
            owner=owner,
            group=group,
            source_kind=source_kind,  # type: ignore[arg-type]
        )

    def _get_owner_windows(self, p: Path) -> Optional[str]:
        ps = shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")
        if not ps:
            return None
        try:
            proc = subprocess.run(
                [ps, "-NoProfile", "-Command", f"(Get-Acl '{str(p)}').Owner"],
                capture_output=True, text=True, check=True
            )
            val = proc.stdout.strip()
            return val if val else None
        except Exception:
            return None

    def _capture_posix(self, src: Path, source_kind: str) -> PermissionsTemplate:
        st = src.stat()
        mode = stat.S_IMODE(st.st_mode)
        owner = None
        group = None

        try:
            import pwd, grp  # noqa: F401
            owner = pwd.getpwuid(st.st_uid).pw_name  # type: ignore[attr-defined]
            group = grp.getgrgid(st.st_gid).gr_name  # type: ignore[attr-defined]
        except Exception:
            pass

        if self._which("getfacl"):
            try:
                proc = subprocess.run(
                    ["getfacl", "-p", str(src)],
                    capture_output=True, text=True, check=True
                )
                payload = proc.stdout.strip()
                backend: Literal["posix_acl", "posix_mode"] = "posix_acl"
            except subprocess.CalledProcessError as e:
                write_debug(f"getfacl failed, falling back to mode-only: {e}", channel="Warning")
                payload = ""
                backend = "posix_mode"
        else:
            payload = ""
            backend = "posix_mode"

        return PermissionsTemplate(
            backend=backend,
            payload=payload,
            mode=mode,
            owner=owner,
            group=group,
            source_kind=source_kind,  # type: ignore[arg-type]
        )

    # ---------- Inspect target ----------
    def _dump_windows_icacls(self, p: Path) -> str:
        try:
            proc = subprocess.run(["icacls", str(p)], capture_output=True, text=True, check=True)
            return proc.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"icacls failed on {p}: {e.stderr or e.stdout}") from e

    def _dump_posix_acl(self, p: Path) -> tuple[str, Optional[int], Optional[str], Optional[str]]:
        st = p.stat()
        mode = stat.S_IMODE(st.st_mode)
        owner = None
        group = None
        try:
            import pwd, grp  # noqa: F401
            owner = pwd.getpwuid(st.st_uid).pw_name  # type: ignore[attr-defined]
            group = grp.getgrgid(st.st_gid).gr_name  # type: ignore[attr-defined]
        except Exception:
            pass

        text = ""
        if self._which("getfacl"):
            try:
                proc = subprocess.run(["getfacl", "-p", str(p)], capture_output=True, text=True, check=True)
                text = proc.stdout.strip()
            except subprocess.CalledProcessError:
                text = ""
        return text, mode, owner, group

    # ---------- Diff ----------
    def diff(self, template: PermissionsTemplate, target: Path) -> dict:
        """
        Returns a dict with keys:
            backend: str
            added: list[str]
            removed: list[str]
            mode_change: "XXXX->YYYY" or None (POSIX)
            owner_change: "from->to" or None
            group_change: "from->to" or None
        Only includes entries relevant to the running backend.
        """
        target = target.resolve()
        result = {
            "backend": template.backend,
            "added": [],
            "removed": [],
            "mode_change": None,
            "owner_change": None,
            "group_change": None,
        }

        if template.backend == "windows_icacls":
            src_lines = self._normalize_icacls(template.payload).splitlines()
            tgt_lines = self._normalize_icacls(self._dump_windows_icacls(target)).splitlines()
            added = sorted([ln for ln in src_lines if ln not in tgt_lines])
            removed = sorted([ln for ln in tgt_lines if ln not in src_lines])
            result["added"] = added
            result["removed"] = removed
            # Owner diff on Windows (best effort)
            src_owner = template.owner
            tgt_owner = self._get_owner_windows(target)
            if src_owner and tgt_owner and src_owner != tgt_owner:
                result["owner_change"] = f"{tgt_owner} -> {src_owner}"
            return result

        # POSIX
        tgt_acl, tgt_mode, tgt_owner, tgt_group = self._dump_posix_acl(target)

        if template.mode is not None and tgt_mode is not None:
            if template.mode != tgt_mode:
                result["mode_change"] = f"{oct(tgt_mode)} -> {oct(template.mode)}"

        if template.owner and tgt_owner and template.owner != tgt_owner:
            result["owner_change"] = f"{tgt_owner} -> {template.owner}"
        if template.group and tgt_group and template.group != tgt_group:
            result["group_change"] = f"{tgt_group} -> {template.group}"

        if template.backend == "posix_acl" and tgt_acl:
            src_lines = self._normalize_getfacl(template.payload).splitlines()
            tgt_lines = self._normalize_getfacl(tgt_acl).splitlines()
            result["added"] = sorted([ln for ln in src_lines if ln not in tgt_lines])
            result["removed"] = sorted([ln for ln in tgt_lines if ln not in src_lines])

        return result

    @staticmethod
    def _normalize_icacls(text: str) -> str:
        # Keep only ACE-like lines: "ACCOUNT:(F)" etc.; drop path headers and status lines
        lines = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("Successfully") or s.startswith("processed file:"):
                continue
            # Skip lines that are just the path followed by entries
            if ":" in s:
                left, right = s.split(":", 1)
                # If the left contains backslashes and looks like a filesystem path, skip header
                if "\\" in left or "/" in left:
                    continue
                s = f"{left}:{right}".strip()
            if "(" in s and ")" in s and ":" in s:
                lines.append(s)
        return "\n".join(lines)

    @staticmethod
    def _normalize_getfacl(text: str) -> str:
        # Drop comments and file path lines
        lines = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s or s.startswith("#") or s.startswith("file:"):
                continue
            lines.append(s)
        return "\n".join(lines)

    # ---------- Apply ----------
    def apply(self,
              template: PermissionsTemplate,
              target: Path,
              *,
              clear_existing: bool = False,
              owner: Optional[str] = None,
              group: Optional[str] = None,
              no_acl: bool = False,
              disable_inheritance: Optional[bool] = None) -> None:
        """
        Apply the captured template to target.

        Arguments:
            clear_existing: When True, clear existing ACL entries before applying (Windows: /reset; POSIX: setfacl -b).
            owner/group: Override owner/group to set on target (platform permitting).
            no_acl: If True, only ownership/mode bits are applied (skip ACL payloads).
            disable_inheritance: Windows only; set to True to disable, False to enable. None = leave unchanged.
        """
        target = target.resolve()
        write_debug(f"Applying permissions to {target}", channel="Information")

        if self.os_name == "windows":
            self._apply_windows(template, target, clear_existing=clear_existing,
                                owner=owner, no_acl=no_acl, disable_inheritance=disable_inheritance)
        else:
            self._apply_posix(template, target, clear_existing=clear_existing,
                              owner=owner, group=group, no_acl=no_acl)

    def _apply_windows(self,
                       template: PermissionsTemplate,
                       target: Path,
                       *,
                       clear_existing: bool,
                       owner: Optional[str],
                       no_acl: bool,
                       disable_inheritance: Optional[bool]) -> None:
        if clear_existing:
            subprocess.run(["icacls", str(target), "/reset"], check=False)

        if owner:
            subprocess.run(["icacls", str(target), "/setowner", owner], check=False)

        if disable_inheritance is True:
            subprocess.run(["icacls", str(target), "/inheritance:d"], check=False)
        elif disable_inheritance is False:
            subprocess.run(["icacls", str(target), "/inheritance:e"], check=False)

        if no_acl:
            return

        if template.backend != "windows_icacls":
            write_debug("Template backend != windows_icacls; skipping ACL import, nothing to apply.", channel="Warning")
            return

        # Best-effort: add/replace ACEs from normalized payload via /grant:r
        src_lines = [ln for ln in self._normalize_icacls(template.payload).splitlines() if ":" in ln]
        for ln in src_lines:
            try:
                acct, rest = ln.split(":", 1)
                perms = rest.strip().strip("()")
                if not acct or not perms:
                    continue
                subprocess.run(["icacls", str(target), "/grant:r", f"{acct}:{perms}"], check=False)
            except Exception as e:
                write_debug(f"Failed to translate ACE '{ln}': {e}", channel="Warning")

    def _apply_posix(self,
                     template: PermissionsTemplate,
                     target: Path,
                     *,
                     clear_existing: bool,
                     owner: Optional[str],
                     group: Optional[str],
                     no_acl: bool) -> None:
        # Ownership
        if owner or group:
            try:
                os.chown(target, *self._resolve_ids(owner, group))  # type: ignore[arg-type]
            except PermissionError:
                if shutil.which("chown"):
                    chown_spec = ""
                    if owner and group:
                        chown_spec = f"{owner}:{group}"
                    elif owner:
                        chown_spec = owner
                    else:
                        chown_spec = f":{group}"
                    subprocess.run(["chown", chown_spec, str(target)], check=False)
                else:
                    write_debug("chown not available and direct chown failed.", channel="Warning")

        # Mode bits
        if template.mode is not None:
            try:
                os.chmod(target, template.mode)
            except PermissionError:
                if shutil.which("chmod"):
                    subprocess.run(["chmod", oct(template.mode), str(target)], check=False)  # type: ignore[arg-type]
                else:
                    write_debug("chmod not available and os.chmod failed.", channel="Warning")

        if no_acl:
            return

        if template.backend == "posix_acl" and self._which("setfacl") and template.payload:
            if clear_existing:
                subprocess.run(["setfacl", "-b", str(target)], check=False)
            try:
                from tempfile import NamedTemporaryFile
                with NamedTemporaryFile("w", encoding="utf-8", delete=True) as tf:
                    tf.write(template.payload)
                    tf.flush()
                    subprocess.run(["setfacl", "--restore", tf.name], check=False)
            except Exception as e:
                write_debug(f"setfacl restore failed: {e}", channel="Warning")

    def _resolve_ids(self, owner: Optional[str], group: Optional[str]) -> tuple[int, int]:
        st = os.stat(".")
        uid = st.st_uid
        gid = st.st_gid
        try:
            import pwd, grp  # noqa: F401
            if owner:
                uid = pwd.getpwnam(owner).pw_uid  # type: ignore[attr-defined]
            if group:
                gid = grp.getgrnam(group).gr_gid  # type: ignore[attr-defined]
        except Exception:
            pass
        return uid, gid

    # ---------- JSON (de)serialization ----------
    def to_dict(self, template: PermissionsTemplate) -> dict:
        d = asdict(template)
        # Ensure mode is JSON-serializable; keep as int, but also include oct string for readability.
        if template.mode is not None:
            d["mode_octal"] = oct(template.mode)
        return d

    def from_dict(self, data: dict) -> PermissionsTemplate:
        # Mode can be int or oct string; prefer 'mode' if present and int-like.
        mode = data.get("mode", None)
        if isinstance(mode, str):
            try:
                mode = int(mode, 8) if mode.startswith("0o") or mode.startswith("0O") else int(mode)
            except Exception:
                mode = None
        return PermissionsTemplate(
            backend=data["backend"],
            payload=data.get("payload", ""),
            mode=mode,
            owner=data.get("owner"),
            group=data.get("group"),
            source_kind=data.get("source_kind", "file"),
            meta=data.get("meta"),
        )

    # ---------- Tree helpers ----------
    def iter_with_depth(self, root: Path, max_depth: int, follow_symlinks: bool) -> Iterable[Path]:
        root = root.resolve()
        yield root
        if max_depth <= 0:
            return
        from collections import deque
        dq: "deque[tuple[Path,int]]" = deque()
        dq.append((root, 0))
        while dq:
            current, depth = dq.popleft()
            if depth >= max_depth:
                continue
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        try:
                            p = Path(entry.path)
                            if entry.is_symlink() and not follow_symlinks:
                                continue
                            yield p
                            if entry.is_dir(follow_symlinks=follow_symlinks):
                                dq.append((p, depth + 1))
                        except FileNotFoundError:
                            continue
            except (NotADirectoryError, PermissionError, FileNotFoundError):
                continue

    def scan_drift(self,
                   root: Path,
                   *,
                   reference: PermissionsTemplate | None,
                   max_depth: int,
                   follow_symlinks: bool) -> list[tuple[str, dict]]:
        """
        Compare each path under 'root' with a reference template (or root's own template if None).
        Returns a list of (relative_path, diff_dict) where there is a non-empty change.
        """
        root = root.resolve()
        if reference is None:
            reference = self.capture(root)

        diffs: list[tuple[str, dict]] = []
        for p in self.iter_with_depth(root, max_depth, follow_symlinks):
            try:
                d = self.diff(reference, p)
                # Determine 'non-empty' diff
                changed = bool(d.get("added") or d.get("removed") or d.get("mode_change") or
                               d.get("owner_change") or d.get("group_change"))
                if changed:
                    rel = p.relative_to(root)
                    diffs.append((str(rel) if str(rel) != "." else ".", d))
            except Exception as e:
                write_debug(f"Drift scan diff failed for {p}: {e}", channel="Warning")
        return diffs

    def list_non_inheriting_windows(self, root: Path, *, max_depth: int, follow_symlinks: bool) -> list[str]:
        """
        On Windows, list paths where ACL inheritance appears disabled (best-effort heuristic).
        """
        if self.os_name != "windows":
            return []
        hits: list[str] = []
        for p in self.iter_with_depth(root, max_depth, follow_symlinks):
            try:
                dump = self._dump_windows_icacls(p)
                # Heuristic: icacls prints "(I)" on inherited ACEs; objects with only explicit ACEs and
                # lines like "Inheritance is disabled" in certain locales; fallback to absence of "(I)".
                norm = self._normalize_icacls(dump)
                has_inherited = "(I)" in dump or "Inherited" in dump
                if not has_inherited and norm:
                    hits.append(str(p))
            except Exception:
                continue
        return hits


# -------- Module-level facade (public API) --------

def read_permissions(src_path: str) -> PermissionsTemplate:
    return PermissionsUtils().capture(Path(src_path))


def diff_permissions(template: PermissionsTemplate, target_path: str) -> dict:
    return PermissionsUtils().diff(template, Path(target_path))


def apply_permissions(template: PermissionsTemplate,
                      target_path: str,
                      *,
                      clear_existing: bool = False,
                      owner: str | None = None,
                      group: str | None = None,
                      no_acl: bool = False,
                      disable_inheritance: bool | None = None) -> None:
    PermissionsUtils().apply(
        template, Path(target_path),
        clear_existing=clear_existing,
        owner=owner, group=group,
        no_acl=no_acl,
        disable_inheritance=disable_inheritance
    )


def save_template(template: PermissionsTemplate, out_path: str) -> None:
    pu = PermissionsUtils()
    data = pu.to_dict(template)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def load_template(in_path: str) -> PermissionsTemplate:
    pu = PermissionsUtils()
    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return pu.from_dict(data)


def scan_drift(root_path: str,
               *,
               reference: PermissionsTemplate | None = None,
               max_depth: int = 0,
               follow_symlinks: bool = False) -> list[tuple[str, dict]]:
    return PermissionsUtils().scan_drift(Path(root_path),
                                         reference=reference,
                                         max_depth=max_depth,
                                         follow_symlinks=follow_symlinks)


def list_non_inheriting_windows(root_path: str,
                                *,
                                max_depth: int = 0,
                                follow_symlinks: bool = False) -> list[str]:
    return PermissionsUtils().list_non_inheriting_windows(Path(root_path),
                                                          max_depth=max_depth,
                                                          follow_symlinks=follow_symlinks)
