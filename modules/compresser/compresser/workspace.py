"""Compression-owned artifact paths; never migrates or claims unrelated state."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from threading import RLock

from .inventory_pipeline import linked

_PUBLICATION_LOCK = RLock()


def _unlinked(path: Path) -> None:
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if linked(info):
            raise ValueError(f"Compression workspace paths must not be linked: {item}")


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except FileNotFoundError:
        return False


@dataclass(frozen=True)
class CompressionWorkspace:
    root: Path
    inventory_file: Path
    trial_cache_file: Path
    target: Path
    owner: str

    @property
    def plans_dir(self) -> Path:
        return self.root / "plans"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def previews_dir(self) -> Path:
        return self.root / "previews"

    def identity(self) -> dict:
        return {
            "schema": 2,
            "target": str(self.target),
            "owner": self.owner,
            "inventory": str(self.inventory_file),
            "trials": str(self.trial_cache_file),
        }


def resolve_workspace(
    target: Path,
    parent: Path | None,
    *,
    owner: str,
) -> CompressionWorkspace:
    _unlinked(target.expanduser().absolute())
    target = target.expanduser().resolve()
    if owner not in ("mangadl-pages", "compresser"):
        raise ValueError("Unsupported compression workspace owner")
    leaf = target.name
    if not leaf:
        raise ValueError("Choose a target with a folder/file name, not a drive root")
    base = (parent or target.parent).expanduser().absolute()
    _unlinked(base)
    if base.is_file() or (
        not base.is_dir() and base.suffix.lower() in (".sqlite3", ".sqlite", ".db")
    ):
        raise ValueError("Workspace requires a parent directory, not an inventory file")
    if any(part.lower() in (".mangadl", ".compresser") for part in target.parts):
        raise ValueError("Input must not be inside a compression artifact container")
    suffix = "mangadl" if owner == "mangadl-pages" else "compresser"
    root = base.resolve() / f".{suffix}" / leaf
    inventory = root / "inventory.sqlite3"
    trials = root / "trials.sqlite3"
    for path in (
        root,
        inventory,
        trials,
        root / "reports",
        root / "previews",
        root / "plans",
        root / "workspace.json",
    ):
        _unlinked(path)
        resolved = path.resolve()
        if resolved == target or (target.is_dir() and target in resolved.parents):
            raise ValueError("Compression artifacts must be outside the input tree")
    if inventory.is_dir() or trials.is_dir() or inventory.resolve() == trials.resolve():
        raise ValueError("Inventory and trial cache require distinct file paths")
    return CompressionWorkspace(
        root,
        inventory.resolve(),
        trials.resolve(),
        target,
        owner,
    )


def _validate_manifest(workspace: CompressionWorkspace) -> None:
    for path in (
        workspace.root,
        workspace.inventory_file,
        workspace.trial_cache_file,
        workspace.reports_dir,
        workspace.previews_dir,
        workspace.plans_dir,
    ):
        _unlinked(path)
    for database in (workspace.inventory_file, workspace.trial_cache_file):
        if database.exists() and (
            not database.is_file() or database.stat().st_nlink > 1
        ):
            raise ValueError(
                "Workspace databases must be distinct files without hardlinks"
            )
    if _same_file(workspace.inventory_file, workspace.trial_cache_file):
        raise ValueError("Inventory and trial cache must use different files")
    manifest = workspace.root / "workspace.json"
    _unlinked(manifest)
    if manifest.exists():
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ValueError(
                f"Invalid workspace manifest {manifest}; choose another -I parent"
            ) from exc
        if not isinstance(value, dict) or any(
            value.get(k) != v for k, v in workspace.identity().items()
        ):
            raise ValueError(
                "Workspace belongs to a different target, owner or storage policy; choose another -I parent"
            )
    elif workspace.root.exists() and any(workspace.root.iterdir()):
        raise ValueError(
            f"Refusing nonempty unowned workspace: {workspace.root}; choose another -I parent"
        )


@contextmanager
def workspace_publication(workspace: CompressionWorkspace):
    from cross_platform.locks import folder_write_lock

    with _PUBLICATION_LOCK:
        with folder_write_lock(
            workspace.root, operation="compression artifact publication"
        ):
            _validate_manifest(workspace)
            yield


def initialize_workspace(workspace: CompressionWorkspace) -> None:
    with workspace_publication(workspace):
        workspace.root.mkdir(parents=True, exist_ok=True)
        manifest = workspace.root / "workspace.json"
        if manifest.exists():
            return
        descriptor, temp = tempfile.mkstemp(prefix=".workspace-", dir=workspace.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        **workspace.identity(),
                        "created": datetime.now(timezone.utc).isoformat(),
                    },
                    stream,
                    indent=2,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, manifest)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)


def configure_workspace(args, target: Path, *, owner: str) -> CompressionWorkspace:
    existing = getattr(args, "_workspace", None)
    if existing:
        return existing
    argument = getattr(args, "inventory_file", None)
    if argument:
        argument = Path(argument).expanduser()
    ws = resolve_workspace(target, argument, owner=owner)
    cache = getattr(args, "cache_file", None)
    if cache:
        cache = Path(cache).expanduser().absolute()
        _unlinked(cache)
        resolved_cache = cache.resolve()
        manifest = ws.root / "workspace.json"
        reserved = [ws.inventory_file, manifest]
        for directory in (ws.reports_dir, ws.previews_dir, ws.plans_dir):
            if (
                resolved_cache == directory.resolve()
                or directory.resolve() in resolved_cache.parents
            ):
                raise ValueError(
                    f"Analysis cache cannot use a reserved workspace artifact: {resolved_cache}"
                )
            if directory.is_dir():
                reserved.extend(path for path in directory.rglob("*") if path.is_file())
        if cache.is_dir() or any(
            resolved_cache == path.resolve() or _same_file(cache, path)
            for path in reserved
        ):
            raise ValueError(
                "Inventory, trial cache and reserved workspace artifacts must use different files"
            )
        if resolved_cache == ws.target or (
            ws.target.is_dir() and ws.target in resolved_cache.parents
        ):
            raise ValueError("Analysis cache must be outside the input tree")
        from dataclasses import replace

        ws = replace(ws, trial_cache_file=resolved_cache)
    args._workspace = ws
    if getattr(args, "preview_dir", None) == Path("__workspace_preview__"):
        args.preview_dir = ws.previews_dir
    return ws
