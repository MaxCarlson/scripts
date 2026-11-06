from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from aebn_dl.media_validation import probe_media, validate_media_facts
from aebn_dl.utils import add_metadata, ffmpeg_mux_streams, validate_fragment_timeline


def _facts(video_duration: float = 30.0, audio_duration: float = 30.0) -> dict:
    return {
        "format": {"duration": str(max(video_duration, audio_duration))},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "start_time": "0.0",
                "duration": str(video_duration),
                "time_base": "1/30000",
                "nb_read_packets": "900",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "start_time": "0.0",
                "duration": str(audio_duration),
                "time_base": "1/48000",
                "nb_read_packets": "1408",
            },
        ],
        "packet_timeline": {
            "video": {"min_pts": 0.0, "max_pts": video_duration, "packet_count": 900, "payload_bytes": 1000},
            "audio": {"min_pts": 0.0, "max_pts": audio_duration, "packet_count": 1408, "payload_bytes": 1000},
        },
    }


def test_container_duration_cannot_hide_two_second_video() -> None:
    facts = _facts(video_duration=2.0, audio_duration=1800.0)

    result = validate_media_facts(facts, expected_duration=1800.0)

    assert result["valid"] is False
    assert any("video" in error.lower() for error in result["errors"])
    assert result["evidence"]["container_duration_s"] == 1800.0
    assert result["evidence"]["streams"]["video"]["duration_s"] == 2.0


def test_packet_timestamp_span_is_checked_even_if_stream_duration_claims_full_length() -> None:
    facts = _facts(video_duration=1800.0, audio_duration=1800.0)
    facts["packet_timeline"]["video"].update({"min_pts": 0.0, "max_pts": 2.0})

    result = validate_media_facts(facts, expected_duration=1800.0)

    assert result["valid"] is False
    assert any("timestamp" in error.lower() or "timeline" in error.lower() for error in result["errors"])


def test_missing_packet_timestamp_evidence_fails_closed() -> None:
    facts = _facts()
    facts.pop("packet_timeline")

    result = validate_media_facts(facts, expected_duration=30.0)

    assert result["valid"] is False
    assert any("timestamp" in error.lower() or "packet" in error.lower() for error in result["errors"])


def test_missing_required_audio_fails_closed() -> None:
    facts = _facts()
    facts["streams"] = facts["streams"][:1]
    facts["packet_timeline"].pop("audio")

    result = validate_media_facts(facts, expected_duration=30.0)

    assert result["valid"] is False
    assert any("audio" in error.lower() for error in result["errors"])


def test_unknown_expected_duration_fails_closed() -> None:
    result = validate_media_facts(_facts(), expected_duration=None)

    assert result["valid"] is False
    assert result["status"] == "unknown"


def test_metadata_rewrite_writes_candidate_without_replacing_intermediate(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "assembled.mp4"
    candidate = tmp_path / "candidate.mp4"
    source.write_bytes(b"preserve this intermediate")
    movie = SimpleNamespace(
        title="Fixture movie",
        scenes=[SimpleNamespace(start_timing=0, end_timing=30, performers=["Fixture"])],
    )

    def fake_ffmpeg(command, **kwargs):
        candidate.write_bytes(b"metadata candidate")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("aebn_dl.utils.subprocess.run", fake_ffmpeg)
    add_metadata(source, movie, output_path=candidate)

    assert source.read_bytes() == b"preserve this intermediate"
    assert candidate.is_file()


def _fake_valid_evidence() -> dict:
    streams = {
        kind: {"duration_s": 30.0, "packet_count": 90, "start_time_s": 0.0}
        for kind in ("video", "audio")
    }
    return {"valid": True, "status": "passed", "errors": [],
            "evidence": {"streams": streams, "expected_duration_s": 30.0}}


def _offline_downloader(tmp_path: Path, monkeypatch, *, metadata_valid: bool = True):
    from aebn_dl.downloader import Downloader

    movie = SimpleNamespace(
        studio_name="Fixture Studio", title="Fixture Movie", movie_id="123", performers=[],
        scenes=[SimpleNamespace(start_timing=0, end_timing=30, performers=["Fixture"])],
        total_duration_seconds=30,
    )
    instance = Downloader(
        "https://straight.aebn.com/straight/movies/123/fixture", output_dir=str(tmp_path),
        work_dir=str(tmp_path / "work"), json_output=True, no_part=True,
    )
    monkeypatch.setattr(instance, "_initialize_download", lambda: None)
    monkeypatch.setattr(instance, "_scrape_movie_info", lambda: movie)

    class ManifestStub:
        total_number_of_data_segments = 1
        video_stream = SimpleNamespace(height=480, human_name="video", media_type="v", stream_id="video")
        audio_stream = SimpleNamespace(human_name="audio", media_type="a", stream_id="audio")

    monkeypatch.setattr(instance, "_process_manifest", lambda _movie: setattr(instance, "manifest", ManifestStub()))
    monkeypatch.setattr(instance, "_download_streams", lambda _movie: None)
    monkeypatch.setattr(instance, "_process_streams", lambda output: Path(output).write_bytes(b"assembled-intermediate"))
    metadata_calls = []

    def write_candidate(source, _movie, *, output_path, scene_n=None):
        metadata_calls.append((Path(source), Path(output_path), scene_n))
        Path(output_path).write_bytes(b"metadata-candidate" if metadata_valid else b"bad-metadata-candidate")
        return Path(output_path)

    monkeypatch.setattr("aebn_dl.downloader.utils.add_metadata", write_candidate)
    monkeypatch.setattr(
        instance,
        "_validate_output",
        lambda path, _expected: ({**_fake_valid_evidence(), "valid": False, "errors": ["video coverage truncated"]}
                                 if "metadata-" in str(path) and not metadata_valid else _fake_valid_evidence()),
    )
    monkeypatch.setattr(instance, "_cleanup", lambda: None)
    return instance, metadata_calls


def test_complete_event_is_after_metadata_and_reports_final_size(tmp_path: Path, monkeypatch, capsys) -> None:
    instance, metadata_calls = _offline_downloader(tmp_path, monkeypatch)

    instance.run()

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    complete = next(event for event in events if event["event"] == "complete")
    output = Path(complete["path"])
    assert metadata_calls
    assert metadata_calls[0][1].parent == output.parent
    assert metadata_calls[0][1].name.startswith(output.name + ".metadata-")
    assert events.index(complete) > max(i for i, event in enumerate(events) if event["event"] == "media_validation")
    assert complete["file_size"] == output.stat().st_size == len(b"metadata-candidate")
    assert output.read_bytes() == b"metadata-candidate"


def test_bad_metadata_candidate_never_replaces_intermediate_or_emits_complete(tmp_path: Path, monkeypatch, capsys) -> None:
    instance, metadata_calls = _offline_downloader(tmp_path, monkeypatch, metadata_valid=False)

    with pytest.raises(ValueError, match="failed validation"):
        instance.run()

    output_files = list(tmp_path.glob("*.mp4"))
    assert len(metadata_calls) == 1
    assert metadata_calls[0][0].read_bytes() == b"assembled-intermediate"
    assert metadata_calls[0][1].read_bytes() == b"bad-metadata-candidate"
    assert not any("Fixture Studio - Fixture Movie" in path.name and path.name.endswith("480p.mp4") for path in output_files)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert not any(event["event"] == "complete" for event in events)


def test_exhausted_required_segment_task_propagates_failure(tmp_path: Path, monkeypatch) -> None:
    from aebn_dl.downloader import Downloader
    from aebn_dl.models import VideoStream

    instance = Downloader(
        "https://straight.aebn.com/straight/movies/123/fixture", work_dir=str(tmp_path),
        output_dir=str(tmp_path), no_part=True,
    )
    stream = VideoStream()
    stream.stream_id = "fixture"
    instance.movie_work_dir = str(tmp_path)
    instance.manifest = SimpleNamespace(process_manifest=lambda: None)

    def fake_segment(_stream, _bar, segment_number=None):
        if segment_number == 1:
            raise OSError("fixture segment permanently unavailable")

    monkeypatch.setattr(instance, "_download_segment", fake_segment)
    with pytest.raises(RuntimeError, match="missing required segments"):
        instance._download_stream(stream, (0, 1), no_progress_bar=True)


def test_invalid_segment_response_is_never_promoted_from_temporary_file(tmp_path: Path) -> None:
    from aebn_dl.downloader import Downloader
    from aebn_dl.models import VideoStream

    instance = Downloader(
        "https://straight.aebn.com/straight/movies/123/fixture", work_dir=str(tmp_path),
        output_dir=str(tmp_path), no_part=True,
    )
    stream = VideoStream()
    stream.stream_id = "fixture"
    instance.movie_work_dir = str(tmp_path)
    instance.manifest = SimpleNamespace(base_stream_url="https://fixture.invalid", total_number_of_data_segments=1)
    instance.session = SimpleNamespace(get=lambda _url: SimpleNamespace(ok=True, content=b"truncated response"))

    with pytest.raises(ValueError, match="complete MP4 fragment"):
        instance._download_segment(stream, None, segment_number=0)

    assert not (tmp_path / "v_fixture_0.mp4").exists()
    assert not list(tmp_path.glob("*.tmp-*"))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg unavailable")
def test_fragment_timeline_rejects_repeated_video_fragment(tmp_path: Path, monkeypatch, capsys) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg
    source = tmp_path / "fragmented-source.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=320x180:rate=30:duration=5", "-an", "-c:v", "libx264", "-g", "30",
         "-movflags", "+empty_moov+frag_keyframe+default_base_moof", "-frag_duration", "1000000", str(source)],
        check=True, capture_output=True, text=True,
    )

    data = source.read_bytes()
    offset = 0
    initialization = bytearray()
    fragments = []
    current = bytearray()
    while offset + 8 <= len(data):
        size, box_type = struct.unpack_from(">I4s", data, offset)
        header_size = 8
        if size == 1:
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header_size = 16
        elif size == 0:
            size = len(data) - offset
        assert size >= header_size
        box = data[offset:offset + size]
        if box_type == b"moof":
            if current:
                fragments.append(bytes(current))
                current.clear()
            current.extend(box)
        elif current:
            current.extend(box)
        else:
            initialization.extend(box)
        offset += size
    if current:
        fragments.append(bytes(current))
    assert len(initialization) > 0
    assert len(fragments) >= 3
    paths = []
    for index, fragment in enumerate(fragments):
        path = tmp_path / f"video_{index}.mp4"
        path.write_bytes(fragment)
        paths.append(path)

    validate_fragment_timeline(paths)

    repeated = [paths[0], paths[0], *paths[2:]]
    with pytest.raises(ValueError, match="decode timestamp"):
        validate_fragment_timeline(repeated)

    from aebn_dl.downloader import Downloader
    from aebn_dl.models import VideoStream

    instance = Downloader("https://straight.aebn.com/straight/movies/123/fixture",
                          no_part=True, json_output=True, threads=2)
    instance.movie_work_dir = str(tmp_path)
    instance.manifest = SimpleNamespace(process_manifest=lambda: None,
                                        total_number_of_data_segments=len(repeated) - 1)
    stream = VideoStream()
    stream.stream_id = "fixture"

    def write_repeated_segment(_stream, _bar, segment_number=None):
        if segment_number is None:
            return
        path = tmp_path / f"v_fixture_{segment_number}.mp4"
        shutil.copyfile(repeated[segment_number], path)
        stream.downloaded_segments.append(str(path))

    monkeypatch.setattr(instance, "_download_segment", write_repeated_segment)
    with pytest.raises(RuntimeError, match="Required AEBN stream downloads failed"):
        instance._download_streams_json([stream], (0, len(repeated) - 1))
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert not any(event["event"] == "segments_complete" for event in events)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools unavailable")
def test_fragmented_metadata_rewrite_preserves_stream_coverage_and_frames(tmp_path: Path) -> None:
    source = tmp_path / "fragmented.mp4"
    candidate = tmp_path / "fragmented-with-metadata.mp4"
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg and ffprobe
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=48000",
            "-t",
            "8",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+empty_moov+frag_keyframe+default_base_moof",
            "-frag_duration",
            "2000000",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    movie = SimpleNamespace(
        title="Fixture movie",
        scenes=[SimpleNamespace(start_timing=0, end_timing=8, performers=["Fixture"])],
    )

    add_metadata(source, movie, output_path=candidate)

    def probe(path: Path) -> dict:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-count_packets",
                "-count_frames",
                "-show_streams",
                "-show_format",
                "-show_chapters",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    before = probe(source)
    after = probe(candidate)
    before_av = [stream for stream in before["streams"] if stream.get("codec_type") in {"audio", "video"}]
    after_av = [stream for stream in after["streams"] if stream.get("codec_type") in {"audio", "video"}]

    assert len(after_av) == 2
    assert {stream["codec_type"] for stream in after_av} == {"audio", "video"}
    assert {stream["codec_type"]: stream["nb_read_packets"] for stream in after_av} == {
        stream["codec_type"]: stream["nb_read_packets"] for stream in before_av
    }
    assert {stream["codec_type"]: stream["duration"] for stream in after_av} == {
        stream["codec_type"]: stream["duration"] for stream in before_av
    }
    assert len(after.get("chapters", [])) == 1


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools unavailable")
def test_metadata_remux_does_not_create_or_hide_collapsed_video_timestamps(tmp_path: Path) -> None:
    source = tmp_path / "collapsed-video.mp4"
    candidate = tmp_path / "collapsed-video-metadata.mp4"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=30",
         "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=30",
         "-vf", "setpts=0.066733*PTS", "-fps_mode", "passthrough",
         "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-c:a", "aac",
         "-movflags", "+empty_moov+frag_keyframe+default_base_moof", "-frag_duration", "2000000",
         str(source)], check=True, capture_output=True, text=True,
    )
    movie = SimpleNamespace(
        title="Synthetic 30-second feature",
        scenes=[SimpleNamespace(start_timing=0, end_timing=30, performers=[])],
    )

    add_metadata(source, movie, output_path=candidate, scene_n=1)

    before = probe_media(source)
    after = probe_media(candidate)
    assert before and after
    assert before["streams"][0]["duration"] == after["streams"][0]["duration"]
    before_video = next(stream for stream in before["streams"] if stream["codec_type"] == "video")
    after_video = next(stream for stream in after["streams"] if stream["codec_type"] == "video")
    assert before_video["nb_read_packets"] == after_video["nb_read_packets"]
    for facts in (before, after):
        validation = validate_media_facts(facts, expected_duration=30.0)
        assert validation["valid"] is False
        assert any("video" in error.lower() or "timeline" in error.lower() for error in validation["errors"])


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools unavailable")
def test_offline_mux_metadata_pipeline_accepts_healthy_and_rejects_truncated_video(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg

    def stream_fixture(stem: str, *, video: bool, duration: int, collapse: bool = False) -> Path:
        path = tmp_path / f"{stem}.mp4"
        if video:
            source = f"testsrc2=size=320x180:rate=30:duration={duration}"
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", source]
            if collapse:
                command += ["-vf", "setpts=0.066733*PTS", "-fps_mode", "passthrough"]
            command += ["-an", "-c:v", "libx264", "-preset", "ultrafast", "-g", "30"]
        else:
            source = f"sine=frequency=770:sample_rate=48000:duration={duration}"
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", source,
                       "-vn", "-c:a", "aac"]
        command += ["-movflags", "+empty_moov+frag_keyframe+default_base_moof", "-frag_duration", "2000000", str(path)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        return path

    video = stream_fixture("healthy-video", video=True, duration=8)
    audio = stream_fixture("healthy-audio", video=False, duration=8)
    muxed = tmp_path / "healthy-muxed.mp4"
    chaptered = tmp_path / "healthy-final.mp4"
    ffmpeg_mux_streams(str(audio), str(video), str(muxed))
    movie = SimpleNamespace(title="Healthy synthetic", scenes=[SimpleNamespace(start_timing=0, end_timing=8, performers=[])])
    add_metadata(muxed, movie, output_path=chaptered, scene_n=1)
    healthy = probe_media(chaptered)
    assert healthy
    assert validate_media_facts(healthy, expected_duration=8.0)["valid"]

    short_video = stream_fixture("truncated-video", video=True, duration=30, collapse=True)
    long_audio = stream_fixture("long-audio", video=False, duration=30)
    corrupt_muxed = tmp_path / "truncated-muxed.mp4"
    corrupt_final = tmp_path / "truncated-final.mp4"
    ffmpeg_mux_streams(str(long_audio), str(short_video), str(corrupt_muxed))
    movie = SimpleNamespace(title="Corrupt synthetic", scenes=[SimpleNamespace(start_timing=0, end_timing=30, performers=[])])
    add_metadata(corrupt_muxed, movie, output_path=corrupt_final, scene_n=1)
    corrupted = probe_media(corrupt_final)
    assert corrupted
    assert float(corrupted["format"]["duration"]) > 29
    assert validate_media_facts(corrupted, expected_duration=30.0)["valid"] is False
