#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM Patch Applier (LEP/v1)
==========================

Core engine that applies LEP/v1 edits. Designed to be used both by the CLI
and directly as a library.

This version adds conservative idempotency handling for PATCH re-applies:
- If the file's current content already matches the post-state of *all* hunks
  (contiguous `context_before + insert + context_after`), a stale preimage hash
  no longer blocks the operation; we treat it as a no-op success.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib  # tests reference applier.hashlib.sha256
import io
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# --------------------------
# Utilities
# --------------------------

def err(*args: Any) -> None:
    print(*args, file=sys.stderr)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(s: str, encoding: str = "utf-8") -> str:
    return sha256_bytes(s.encode(encoding))


def is_subpath(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def normalize_rel_path(p: str) -> str:
    # Disallow absolute, drive-qualified (Windows), or sneaky paths that escape root
    if os.path.isabs(p):
        raise ValueError(f"Absolute paths are not allowed: {p!r}")
    # Normalize separators, collapse .. and .
    norm = os.path.normpath(p).replace("\\", "/")
    # Still forbid leading parent escapes
    if norm.startswith("../") or norm == "..":
        raise ValueError(f"Path escapes repo root: {p!r}")
    return norm


def detect_eol(s: str) -> str:
    # If any CRLF lines exist, treat file as CRLF; else LF
    return "crlf" if "\r\n" in s and not s.replace("\r\n", "\n").endswith("\r") else "lf"


def apply_eol(s: str, eol: str) -> str:
    s_lf = s.replace("\r\n", "\n")
    if eol == "crlf":
        return s_lf.replace("\n", "\r\n")
    return s_lf


def read_text_file(path: Path, encoding: str = "utf-8") -> Tuple[str, str]:
    data = path.read_bytes()
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as e:
        raise ValueError(f"File {path} is not {encoding}-decodable: {e}") from e
    return text, detect_eol(text)


def write_text_atomic(path: Path, text: str, eol: str, encoding: str = "utf-8") -> None:
    tmp_dir = path.parent
    tmp_dir.mkdir(parents=True, exist_ok=True)
    final = apply_eol(text, eol)
    data = final.encode(encoding)

    fd, tmp_name = tempfile.mkstemp(prefix=".lep-", dir=str(tmp_dir))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # fsync directory for durability
        if hasattr(os, "fsync"):
            dfd = os.open(str(tmp_dir), os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except Exception:
            pass


# --------------------------
# LEP/v1 structures
# --------------------------

@dataclasses.dataclass
class Preimage:
    exists: Optional[bool] = None
    sha256: Optional[str] = None
    size: Optional[int] = None


@dataclasses.dataclass
class Hunk:
    context_before: Optional[str] = None
    remove: Optional[str] = None
    insert: Optional[str] = None
    context_after: Optional[str] = None


@dataclasses.dataclass
class Change:
    path: str
    op: str  # "patch" | "replace" | "create" | "delete" | "rename"
    preimage: Preimage = dataclasses.field(default_factory=Preimage)
    language: Optional[str] = None
    constraints: Dict[str, Any] = dataclasses.field(default_factory=dict)
    patch: Optional[Dict[str, Any]] = None  # {'format': 'blocks', 'hunks': [Hunk...]}
    replace: Optional[Dict[str, Any]] = None  # {'full_text': str}
    create: Optional[Dict[str, Any]] = None  # {'full_text': str}
    rename: Optional[Dict[str, Any]] = None  # {'new_path': str}


@dataclasses.dataclass
class LEP:
    protocol: str
    transaction_id: Optional[str]
    dry_run: bool
    defaults: Dict[str, Any]
    changes: List[Change]


# --------------------------
# Parsing the model output
# --------------------------

FENCE_RE = re.compile(r"^\s*```(?P<lang>[a-zA-Z0-9_-]*)\s*$")
FENCE_END_RE = re.compile(r"^\s*```\s*$")


def extract_json_from_possible_fenced(input_text: str) -> str:
    """
    Accept either raw JSON or a single fenced code block wrapping the JSON.
    """
    lines = input_text.strip().splitlines()
    if not lines:
        raise ValueError("Empty input")

    if FENCE_RE.match(lines[0]):
        # find terminating ```
        for i in range(1, len(lines)):
            if FENCE_END_RE.match(lines[i]):
                return "\n".join(lines[1:i])
        raise ValueError("Detected fenced code block but did not find closing ```")
    else:
        return input_text.strip()


def parse_lep(raw: str) -> LEP:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    if not isinstance(obj, dict):
        raise ValueError("LEP root must be an object")

    protocol = obj.get("protocol")
    if protocol not in ("LEP/v1",):
        raise ValueError(f"Unsupported protocol {protocol!r}")

    defaults = obj.get("defaults", {}) or {}
    changes_raw = obj.get("changes")
    if not isinstance(changes_raw, list) or not changes_raw:
        raise ValueError("`changes` must be a non-empty array")

    changes: List[Change] = []
    for c in changes_raw:
        if not isinstance(c, dict):
            raise ValueError("Each item in `changes` must be an object")
        path = c.get("path")
        op = c.get("op")
        if not path or not isinstance(path, str):
            raise ValueError("change.path must be a string")
        if op not in ("patch", "replace", "create", "delete", "rename"):
            raise ValueError(f"Unsupported op {op!r}")

        pre_raw = c.get("preimage", {}) or {}
        pre = Preimage(
            exists=pre_raw.get("exists"),
            sha256=pre_raw.get("sha256"),
            size=pre_raw.get("size"),
        )

        changes.append(
            Change(
                path=path,
                op=op,
                preimage=pre,
                language=c.get("language"),
                constraints=c.get("constraints", {}) or {},
                patch=c.get("patch"),
                replace=c.get("replace"),
                create=c.get("create"),
                rename=c.get("rename"),
            )
        )

    return LEP(
        protocol=protocol,
        transaction_id=obj.get("transaction_id"),
        dry_run=bool(obj.get("dry_run", False)),
        defaults=defaults,
        changes=changes,
    )


# --------------------------
# Patch engine (blocks)
# --------------------------

class PatchConflict(Exception):
    pass


def _hunk_already_applied(text: str, h: Hunk) -> bool:
    """
    True if we can conservatively detect that the hunk is already applied.
    We check for a contiguous occurrence of context_before + insert + context_after.
    Any of the context strings may be empty/None; we only use what is present.
    """
    insert = h.insert or ""
    cb = h.context_before or ""
    ca = h.context_after or ""

    # Construct the expected post-state slice
    parts = []
    if cb:
        parts.append(cb)
    parts.append(insert)
    if ca:
        parts.append(ca)
    target = "".join(parts)

    if not target:
        # Nothing to assert conclusively.
        return False

    # Quick membership test
    if target in text:
        if cb and ca:
            # Ensure relative order when both contexts are present
            idx_cb = text.find(cb)
            if idx_cb != -1:
                idx_target = text.find(target, idx_cb)
                if idx_target != -1:
                    return True
            return False
        return True

    # Special case: deletion where insert == "" and remove vanished
    if insert == "" and (h.remove or "") and (h.remove not in text):
        return True

    return False


def _find_anchor_span(text: str, before: Optional[str], remove: str, after: Optional[str]) -> Tuple[int, int]:
    """
    Conservative anchor resolution:
      - Prefer contiguous match of before + remove + after (when provided).
      - Fall back to searching for before + remove (or remove + after).
      - Otherwise search for first exact 'remove'.
    Returns (start_index_of_remove, end_index_of_remove) in 'text'.
    Raises PatchConflict if not found.
    """
    remove = remove or ""

    # Try contiguous before + remove + after
    if before is not None and after is not None:
        idx_before = text.find(before)
        while idx_before != -1:
            idx_rem = text.find(remove, idx_before + len(before)) if remove else (idx_before + len(before))
            if idx_rem == -1 and remove:
                idx_before = text.find(before, idx_before + 1)
                continue
            after_pos = idx_rem + len(remove)
            if text.startswith(after or "", after_pos):
                return (idx_rem, after_pos)
            idx_before = text.find(before, idx_before + 1)

    # Try before + remove
    if before is not None:
        idx_b = text.find(before)
        while idx_b != -1:
            idx_r = text.find(remove, idx_b + len(before)) if remove else (idx_b + len(before))
            if idx_r != -1 or not remove:
                end_r = idx_r + len(remove) if remove else idx_r
                return (idx_r, end_r)
            idx_b = text.find(before, idx_b + 1)

    # Try remove + after
    if after is not None and remove:
        idx_r = text.find(remove)
        while idx_r != -1:
            end_r = idx_r + len(remove)
            if text.startswith(after, end_r):
                return (idx_r, end_r)
            idx_r = text.find(remove, idx_r + 1)

    # Fallback: exact remove
    if remove:
        idx = text.find(remove)
        if idx != -1:
            return (idx, idx + len(remove))

    raise PatchConflict("Anchors not found for hunk")


def apply_hunks(original: str, hunks: List[Hunk]) -> str:
    """
    Applies hunks sequentially.

    Idempotency handling:
      - If a hunk's post-state (context_before + insert + context_after) is already present,
        skip the hunk without error.
      - If remove == insert and the text already contains that exact region, skip.
      - If we can anchor a remove-span and it already equals `insert`, skip.
    """
    text = original
    for i, h in enumerate(hunks, 1):
        before = h.context_before
        remove = h.remove or ""
        insert = h.insert or ""
        after = h.context_after

        # Strong idempotency: if the final contiguous state is already there, skip
        if _hunk_already_applied(text, h):
            continue

        # Shortcut: if remove == insert and the region exists, nothing to do
        if remove == insert and remove and (remove in text):
            continue

        # Find anchor span for the *remove* region
        start, end = _find_anchor_span(text, before, remove, after)

        # If it's already replaced, skip
        if text[start:end] == insert:
            continue

        text = text[:start] + insert + text[end:]
    return text


# --------------------------
# Applying changes
# --------------------------

def _apply_change(change: Change, repo_root: Path, defaults: Dict[str, Any], dry_run: bool, force: bool) -> None:
    rel = normalize_rel_path(change.path)
    abs_path = (repo_root / rel).resolve()
    if not is_subpath(abs_path, repo_root):
        raise ValueError(f"Path escapes repo: {change.path!r}")

    # Defaults
    default_eol = defaults.get("eol", "preserve")
    default_encoding = defaults.get("encoding", "utf-8")

    op = change.op

    if op == "delete":
        if abs_path.exists():
            err(f"DELETE {rel}")
            if not dry_run:
                abs_path.unlink()
        else:
            err(f"DELETE {rel} (already absent)")
        return

    if op == "rename":
        if not change.rename or not isinstance(change.rename.get("new_path"), str):
            raise ValueError("rename.new_path is required")
        new_rel = normalize_rel_path(change.rename["new_path"])
        new_abs = (repo_root / new_rel).resolve()
        if not is_subpath(new_abs, repo_root):
            raise ValueError(f"New path escapes repo: {new_rel!r}")
        err(f"RENAME {rel} -> {new_rel}")
        if not dry_run:
            new_abs.parent.mkdir(parents=True, exist_ok=True)
            if abs_path.exists():
                shutil.move(str(abs_path), str(new_abs))
            else:
                # If source missing but idempotent rename, treat as success when dest exists
                if not new_abs.exists():
                    raise FileNotFoundError(f"Cannot rename; source missing: {rel}")
        return

    if op in ("replace", "create", "patch"):
        exists = abs_path.exists()
        if op == "create" and exists:
            err(f"CREATE {rel} (already exists)")
        elif op == "create":
            err(f"CREATE {rel}")
        elif op == "replace" and not exists:
            err(f"REPLACE {rel} (creating)")
        else:
            err(f"{op.upper()} {rel}")

        if op == "create":
            full_text = (change.create or {}).get("full_text")
            if not isinstance(full_text, str):
                raise ValueError("create.full_text (string) is required")
            eol = default_eol if default_eol != "preserve" else "lf"
            if not dry_run:
                write_text_atomic(abs_path, full_text, eol, default_encoding)
            return

        if op == "replace":
            full_text = (change.replace or {}).get("full_text")
            if not isinstance(full_text, str):
                raise ValueError("replace.full_text (string) is required")

            eol = "lf"
            if exists:
                current, e = read_text_file(abs_path, default_encoding)
                eol = e if default_eol == "preserve" else default_eol
                # optional preimage check
                if change.preimage and change.preimage.sha256 and not force:
                    have = sha256_text(current, default_encoding)
                    if have != change.preimage.sha256:
                        raise PatchConflict(f"Preimage sha256 mismatch for {rel}")
            else:
                eol = default_eol if default_eol != "preserve" else "lf"

            if not dry_run:
                write_text_atomic(abs_path, full_text, eol, default_encoding)
            return

        if op == "patch":
            patch_obj = change.patch or {}
            hunks_raw = patch_obj.get("hunks")
            if not isinstance(hunks_raw, list) or not hunks_raw:
                raise ValueError("patch.hunks must be a non-empty array")

            if not exists:
                raise FileNotFoundError(f"Cannot patch non-existent file: {rel}")

            current, eol = read_text_file(abs_path, default_encoding)
            if default_eol != "preserve":
                eol = default_eol

            # Prepare hunk objects for both idempotency checks and actual apply
            hunks_preview = [
                Hunk(
                    context_before=h.get("context_before"),
                    remove=h.get("remove"),
                    insert=h.get("insert"),
                    context_after=h.get("context_after"),
                )
                for h in hunks_raw
            ]

            # preimage check when provided — but allow idempotent re-apply to pass
            if change.preimage and change.preimage.sha256 and not force:
                have = sha256_text(current, default_encoding)
                if have != change.preimage.sha256:
                    # If *all* hunks are already applied, allow no-op success
                    if all(_hunk_already_applied(current, hh) for hh in hunks_preview):
                        # Nothing to write
                        return
                    raise PatchConflict(f"Preimage sha256 mismatch for {rel}")

            # Apply hunks
            result = apply_hunks(current, hunks_preview)
            if not dry_run:
                write_text_atomic(abs_path, result, eol, default_encoding)
            return

    raise ValueError(f"Unhandled op: {op}")


# --------------------------
# Public API
# --------------------------

def apply_from_text(
    lep_text_or_fenced: str,
    *,
    repo_root: Path | str = ".",
    dry_run: bool = False,
    force: bool = False,
    quiet: bool = False,
) -> int:
    """
    Apply LEP/v1 edits from raw text (either raw JSON or a fenced code block).
    Returns process-like exit code (0 success, 1 invalid, 2 conflict/missing, 3 IO).
    """
    repo_root = Path(repo_root).resolve()
    try:
        raw_json = extract_json_from_possible_fenced(lep_text_or_fenced)
        lep = parse_lep(raw_json)
    except Exception as e:
        err(f"[invalid input] {e}")
        return 1

    # CLI flags override LEP.dry_run semantics here by explicit parameter
    effective_dry = dry_run or lep.dry_run

    if lep.transaction_id and not quiet:
        print(f"Transaction: {lep.transaction_id}")
    if effective_dry and not quiet:
        print("Mode: dry-run (no writes)")

    try:
        for ch in lep.changes:
            _apply_change(ch, repo_root, lep.defaults or {}, dry_run=effective_dry, force=force)
    except PatchConflict as e:
        err(f"[conflict] {e}")
        return 2
    except FileNotFoundError as e:
        err(f"[missing] {e}")
        return 2
    except PermissionError as e:
        err(f"[perm] {e}")
        return 3
    except OSError as e:
        err(f"[io] {e}")
        return 3
    except Exception as e:
        err(f"[error] {e}")
        return 1

    if not quiet:
        print("Done.")
    return 0
