from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scene:
    performers: list
    scene_id: str | None = None
    start_timing: int = field(init=False)
    end_timing: int = field(init=False)
    start_segment: int = field(init=False)
    end_segment: int = field(init=False)


@dataclass
class MediaStream:
    human_name: str
    media_type: str
    stream_id: str = field(init=False)
    path: str = field(init=False)
    downloaded_segments: list[str] = field(default_factory=list)
    total_size: int = 0
    downloaded_bytes: int = 0
    network_downloaded_bytes: int = 0
    optional_missing_segments: list[int] = field(default_factory=list)
    track_info: dict | None = None


@dataclass
class AudioStream(MediaStream):
    human_name: str = "audio"
    media_type: str = "a"


@dataclass
class VideoStream(MediaStream):
    human_name: str = "video"
    media_type: str = "v"
    height: int = 0
