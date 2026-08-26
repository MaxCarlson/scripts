from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .discovery import save_state_key
from .models import GameRecord, ManifestEntry, SaveSource, SnapshotManifest
from .retention import parse_retention, retained_snapshot_ids
from .utils import format_playtime, iso_now, parse_iso, sanitize_filename, sha256_file


@dataclass
class CaptureResult:
    game_id: str
    snapshot_id: str | None
    changed: bool
    reused_snapshot: bool
    files_seen: int
    changed_files: int
    deleted_files: int
    bytes_added: int


class ArchiveEngine:
    def __init__(self, archive_root: Path, *, file_stability_seconds: float = 0.25) -> None:
        self.root = Path(archive_root)
        self.blobs_root = self.root / "blobs"
        self.manifests_root = self.root / "manifests"
        self.file_stability_seconds = max(0.0, file_stability_seconds)

    def manifest_dir(self, game_id: str) -> Path:
        return self.manifests_root / game_id

    def load_manifest(self, game_id: str, snapshot_id: str) -> SnapshotManifest:
        path = self.manifest_dir(game_id) / f"{snapshot_id}.json"
        return SnapshotManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_manifests(self, game_id: str) -> list[SnapshotManifest]:
        folder = self.manifest_dir(game_id)
        if not folder.exists():
            return []
        manifests: list[SnapshotManifest] = []
        for path in folder.glob("*.json"):
            try:
                manifests.append(SnapshotManifest.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return sorted(manifests, key=lambda item: parse_iso(item.created_at))

    def latest_manifest(self, game: GameRecord) -> SnapshotManifest | None:
        if game.last_snapshot_id:
            try:
                return self.load_manifest(game.id, game.last_snapshot_id)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        manifests = self.list_manifests(game.id)
        return manifests[-1] if manifests else None

    def capture_game(
        self,
        game: GameRecord,
        *,
        reason: str,
        session_id: str | None = None,
        playtime_seconds: float | None = None,
    ) -> CaptureResult:
        self.root.mkdir(parents=True, exist_ok=True)
        latest = self.latest_manifest(game)
        previous = {entry.identity: entry for entry in latest.entries} if latest else {}
        entries: list[ManifestEntry] = []
        bytes_added = 0
        for source in game.save_sources:
            if not source.enabled:
                continue
            for path, relative, raw_bytes, mtime_ns in self._iter_source_items(source):
                identity = f"{source.id}:{relative}"
                old = previous.get(identity)
                size = len(raw_bytes) if raw_bytes is not None else path.stat().st_size
                if raw_bytes is None and old and old.size == size and old.mtime_ns == mtime_ns:
                    digest = old.blob_sha256
                else:
                    digest = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else sha256_file_stable(
                        path, self.file_stability_seconds
                    )
                blob = self._blob_path(digest)
                if not blob.exists():
                    blob.parent.mkdir(parents=True, exist_ok=True)
                    if raw_bytes is not None:
                        temp = blob.with_suffix(".tmp")
                        temp.write_bytes(raw_bytes)
                        os.replace(temp, blob)
                    else:
                        copy_file_stable(path, blob, self.file_stability_seconds)
                    bytes_added += size
                state_key = save_state_key(source.id, relative)
                state_index = ensure_state_index(game, state_key)
                created = iso_now()
                extension = Path(relative).suffix or (".reg" if source.kind == "registry" else ".sav")
                friendly = friendly_save_name(game.name, state_index, created, playtime_seconds or game.effective_playtime_seconds, relative, extension)
                entries.append(
                    ManifestEntry(
                        source_id=source.id,
                        relative_path=relative,
                        blob_sha256=digest,
                        size=size,
                        mtime_ns=mtime_ns,
                        state_key=state_key,
                        state_index=state_index,
                        original_name=Path(relative).name,
                        friendly_name=friendly,
                        captured_at=created,
                        playtime_seconds=float(playtime_seconds if playtime_seconds is not None else game.effective_playtime_seconds),
                    )
                )
        entries.sort(key=lambda item: item.identity.casefold())
        current_hashes = {entry.identity: entry.blob_sha256 for entry in entries}
        previous_hashes = {entry.identity: entry.blob_sha256 for entry in previous.values()}
        changed_identities = sorted(
            identity for identity, digest in current_hashes.items() if previous_hashes.get(identity) != digest
        )
        deleted_identities = sorted(set(previous_hashes) - set(current_hashes))
        if latest and current_hashes == previous_hashes:
            return CaptureResult(game.id, latest.snapshot_id, False, True, len(entries), 0, 0, bytes_added)
        snapshot_id = make_snapshot_id()
        changed_indices = sorted(
            {entry.state_index for entry in entries if entry.identity in set(changed_identities)}
            | {previous[identity].state_index for identity in deleted_identities if identity in previous}
        )
        manifest = SnapshotManifest(
            snapshot_id=snapshot_id,
            game_id=game.id,
            created_at=iso_now(),
            reason=reason,
            playtime_seconds=float(playtime_seconds if playtime_seconds is not None else game.effective_playtime_seconds),
            session_id=session_id,
            entries=entries,
            changed_identities=changed_identities,
            deleted_identities=deleted_identities,
            state_indices_changed=changed_indices,
        )
        target_dir = self.manifest_dir(game.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{snapshot_id}.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, target)
        game.last_snapshot_id = snapshot_id
        game.last_changed_at = manifest.created_at
        game.status = "protected" if entries else "discovered_no_save"
        return CaptureResult(
            game.id,
            snapshot_id,
            True,
            False,
            len(entries),
            len(changed_identities),
            len(deleted_identities),
            bytes_added,
        )

    def pin_exit_checkpoint(
        self,
        game: GameRecord,
        *,
        snapshot_id: str,
        session_id: str,
        keep: int,
        playtime_seconds: float,
    ) -> None:
        game.exit_checkpoints.append(
            {
                "snapshot_id": snapshot_id,
                "session_id": session_id,
                "created_at": iso_now(),
                "playtime_seconds": playtime_seconds,
            }
        )
        game.exit_checkpoints = game.exit_checkpoints[-max(1, keep) :]

    def prune_game(self, game: GameRecord, config: dict) -> tuple[int, int]:
        manifests = self.list_manifests(game.id)
        if not manifests:
            return 0, 0
        policy = parse_retention(config["backup"]["normal_retention"])
        exit_ids = [item["snapshot_id"] for item in game.exit_checkpoints if item.get("snapshot_id")]
        keep = retained_snapshot_ids(
            manifests,
            policy=policy,
            in_session_keep_cycles=int(config["backup"]["in_session_keep_cycles"]),
            exit_snapshot_ids=exit_ids,
        )
        removed = 0
        for manifest in manifests:
            if manifest.snapshot_id in keep:
                continue
            path = self.manifest_dir(game.id) / f"{manifest.snapshot_id}.json"
            if path.exists():
                path.unlink()
                removed += 1
        blobs_removed = self.gc_blobs()
        remaining = self.list_manifests(game.id)
        if remaining:
            game.last_snapshot_id = remaining[-1].snapshot_id
        return removed, blobs_removed

    def gc_blobs(self) -> int:
        referenced: set[str] = set()
        if self.manifests_root.exists():
            for path in self.manifests_root.glob("*/*.json"):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                for entry in raw.get("entries", []):
                    if entry.get("blob_sha256"):
                        referenced.add(entry["blob_sha256"])
        removed = 0
        if not self.blobs_root.exists():
            return 0
        for path in self.blobs_root.glob("*/*"):
            if path.is_file() and path.name not in referenced:
                path.unlink()
                removed += 1
        return removed

    def export_snapshot(self, game: GameRecord, snapshot_id: str, target: Path, *, overwrite: bool = False) -> Path:
        manifest = self.load_manifest(game.id, snapshot_id)
        root = Path(target) / sanitize_filename(game.name) / snapshot_id
        if root.exists() and any(root.iterdir()) and not overwrite:
            raise FileExistsError(f"Export target already exists and is not empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        used_friendly: set[str] = set()
        for entry in manifest.entries:
            identity_target = root / "original" / entry.source_id / Path(entry.relative_path)
            identity_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self._blob_path(entry.blob_sha256), identity_target)
            friendly = entry.friendly_name
            if friendly.casefold() in used_friendly:
                stem = Path(friendly).stem
                suffix = Path(friendly).suffix
                friendly = f"{stem}__{sanitize_filename(Path(entry.relative_path).stem)}{suffix}"
            used_friendly.add(friendly.casefold())
            friendly_target = root / "friendly" / friendly
            friendly_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self._blob_path(entry.blob_sha256), friendly_target)
        return root

    def _blob_path(self, digest: str) -> Path:
        return self.blobs_root / digest[:2] / digest

    def _iter_source_items(self, source: SaveSource) -> Iterable[tuple[Path, str, bytes | None, int]]:
        if source.kind == "registry":
            data = export_registry_bytes(source.path)
            if data is not None:
                yield Path(source.path), "registry.reg", data, 0
            return
        path = Path(source.path).expanduser()
        if path.is_file():
            stat = path.stat()
            yield path, path.name, None, stat.st_mtime_ns
            return
        if not path.is_dir():
            return
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            try:
                stat = child.stat()
                relative = child.relative_to(path).as_posix()
            except (OSError, ValueError):
                continue
            yield child, relative, None, stat.st_mtime_ns


def ensure_state_index(game: GameRecord, state_key: str) -> int:
    if state_key in game.state_overrides:
        index = int(game.state_overrides[state_key])
        game.save_states[state_key] = index
        return index
    if state_key in game.save_states:
        return int(game.save_states[state_key])
    used = set(game.save_states.values()) | set(game.state_overrides.values())
    index = 0
    while index in used:
        index += 1
    game.save_states[state_key] = index
    return index


def friendly_save_name(
    game_name: str,
    state_index: int,
    created_at: str,
    playtime_seconds: float,
    relative_path: str,
    extension: str,
) -> str:
    stamp = parse_iso(created_at).astimezone().strftime("%Y%m%d-%H%M%S")
    original_stem = sanitize_filename(Path(relative_path).stem)
    prefix = f"{sanitize_filename(game_name)}_{state_index}_{stamp}_{format_playtime(playtime_seconds)}"
    return f"{prefix}__{original_stem}{extension}"


def make_snapshot_id() -> str:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    return f"{stamp}Z-{uuid.uuid4().hex[:10]}"


def sha256_file_stable(path: Path, settle_seconds: float, attempts: int = 5) -> str:
    for _ in range(attempts):
        before = path.stat()
        digest = sha256_file(path)
        if settle_seconds:
            time.sleep(settle_seconds)
        after = path.stat()
        if before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns:
            return digest
    raise RuntimeError(f"Save file remained unstable while hashing: {path}")


def copy_file_stable(path: Path, target: Path, settle_seconds: float, attempts: int = 5) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(attempts):
        before = path.stat()
        temp = target.with_suffix(".tmp")
        shutil.copyfile(path, temp)
        if settle_seconds:
            time.sleep(settle_seconds)
        after = path.stat()
        if before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns:
            os.replace(temp, target)
            return
        temp.unlink(missing_ok=True)
    raise RuntimeError(f"Save file remained unstable while copying: {path}")


def export_registry_bytes(key: str) -> bytes | None:
    if os.name != "nt":
        return None
    with tempfile.TemporaryDirectory(prefix="saved-game-archiver-reg-") as temp_dir:
        target = Path(temp_dir) / "save.reg"
        process = subprocess.run(
            ["reg", "export", key, str(target), "/y"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode != 0 or not target.exists():
            return None
        return target.read_bytes()
