from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from vdedup.models import FrameSignature, VideoSignature


SCHEMA_VERSION = 1


def _signature_to_record(signature: VideoSignature, *, size: int, mtime_ns: int) -> Dict[str, Any]:
    record = signature.to_json_dict()
    record.update({
        "schema_version": SCHEMA_VERSION,
        "size": int(size),
        "mtime_ns": int(mtime_ns),
        "backend": signature.extraction_backend,
        "profile": signature.sampling_profile,
    })
    return record


def _record_to_signature(record: Dict[str, Any]) -> VideoSignature:
    if "signatures" not in record and "frames" in record:
        path = str(record["path"])
        video_id = str(Path(path))
        record = dict(record)
        record["video_id"] = record.get("video_id", video_id)
        record["sampled_frame_count"] = len(record.get("frames", []))
        record["valid_frame_count"] = sum(1 for frame in record.get("frames", []) if frame.get("valid_for_matching"))
        record["extraction_backend"] = record.get("extraction_backend", record.get("backend"))
        record["sampling_profile"] = record.get("sampling_profile", record.get("profile"))
        record["signatures"] = [
            {"path": path, "video_id": video_id, **frame}
            for frame in record.get("frames", [])
        ]
    return VideoSignature.from_json_dict(record)


class GpuSignatureCache:
    def __init__(self, path: Optional[Path]):
        self.path = path
        self._map: Dict[Tuple[str, int, int, str, str], Dict[str, Any]] = {}
        if path:
            self._load()

    def _key(self, path: Path, size: int, mtime_ns: int, profile: str, backend: str) -> Tuple[str, int, int, str, str]:
        return (str(path), int(size), int(mtime_ns), str(profile), str(backend))

    def _load(self) -> None:
        assert self.path is not None
        path = Path(self.path).expanduser()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            return
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                    if int(record.get("schema_version", 0)) != SCHEMA_VERSION:
                        continue
                    key = self._key(
                        Path(record["path"]),
                        int(record["size"]),
                        int(record["mtime_ns"]),
                        str(record["profile"]),
                        str(record["backend"]),
                    )
                    self._map[key] = record
                except Exception:
                    continue

    def get(
        self,
        path: Path,
        size: int,
        mtime_ns: int,
        profile: str,
        backend: str,
    ) -> Optional[VideoSignature]:
        record = self._map.get(self._key(path, size, mtime_ns, profile, backend))
        if record is None:
            return None
        try:
            return _record_to_signature(record)
        except Exception:
            return None

    def put(self, signature: VideoSignature, *, size: int, mtime_ns: int) -> None:
        key = self._key(signature.path, size, mtime_ns, signature.sampling_profile, signature.extraction_backend)
        record = _signature_to_record(signature, size=size, mtime_ns=mtime_ns)
        self._map[key] = record
        if not self.path:
            return
        path = Path(self.path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
