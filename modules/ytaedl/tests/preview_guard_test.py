from pathlib import Path

from ytaedl import downloader, extdl


def test_preview_url_detection_includes_query_and_trailer_tokens():
    assert extdl.looks_like_preview_video("https://cdn.example/video.mp4?isPreview=true".lower())
    assert extdl.looks_like_preview_video("https://cdn.example/trailer/123_hq.mp4".lower())
    assert extdl.looks_like_preview_video("https://cdn.example/sample/123.mp4".lower())


def test_fallback_command_disables_playlist_for_raw_candidates(tmp_path):
    cmd = extdl.build_yt_dlp_command_for_candidate(
        "https://cdn.example/video_id_hq.mp4",
        out_dir=tmp_path,
        referer="https://example.com/watch/1",
        origin="https://example.com",
    )

    assert "--no-playlist" in cmd


def test_short_raw_variant_download_is_rejected_and_deleted(tmp_path, monkeypatch):
    output = tmp_path / "123456789_hq.mp4"
    output.write_bytes(b"not actually parsed because ffprobe is mocked")
    monkeypatch.setattr(downloader, "_probe_media_duration_s", lambda path: 60.0)

    rejected, duration_s, path = downloader._reject_short_preview_candidate(
        "https://cdn.example/media/123456789_hq.mp4",
        output,
    )

    assert rejected is True
    assert duration_s == 60.0
    assert path == output
    assert not output.exists()


def test_short_numeric_raw_candidate_is_rejected_and_deleted(tmp_path, monkeypatch):
    output = tmp_path / "62523.mp4"
    output.write_bytes(b"not actually parsed because ffprobe is mocked")
    monkeypatch.setattr(downloader, "_probe_media_duration_s", lambda path: 7.2)

    rejected, duration_s, path = downloader._reject_short_preview_candidate(
        "https://cdn.example/media/62523.mp4",
        output,
    )

    assert rejected is True
    assert duration_s == 7.2
    assert path == output
    assert not output.exists()


def test_short_numeric_collision_suffix_candidate_is_rejected_and_deleted(tmp_path, monkeypatch):
    output = tmp_path / "62523-1.mp4"
    output.write_bytes(b"not actually parsed because ffprobe is mocked")
    monkeypatch.setattr(downloader, "_probe_media_duration_s", lambda path: 7.2)

    rejected, duration_s, path = downloader._reject_short_preview_candidate(
        "https://cdn.example/media/62523-1.mp4",
        output,
    )

    assert rejected is True
    assert duration_s == 7.2
    assert path == output
    assert not output.exists()


def test_long_raw_variant_download_is_kept(tmp_path, monkeypatch):
    output = tmp_path / "123456789_lq.mp4"
    output.write_bytes(b"not actually parsed because ffprobe is mocked")
    monkeypatch.setattr(downloader, "_probe_media_duration_s", lambda path: 5400.0)

    rejected, duration_s, path = downloader._reject_short_preview_candidate(
        "https://cdn.example/media/123456789_lq.mp4",
        output,
    )

    assert rejected is False
    assert duration_s == 5400.0
    assert path == output
    assert output.exists()


def test_completed_mp4_temp_is_promoted_when_probeable(tmp_path, monkeypatch):
    temp_path = tmp_path / "123456789_hq.mp4.temp"
    final_path = tmp_path / "123456789_hq.mp4"
    temp_path.write_bytes(b"not actually parsed because ffprobe is mocked")
    monkeypatch.setattr(downloader, "_probe_media_duration_s", lambda path: 5400.0)

    promoted = downloader._promote_finished_temp_file(temp_path)

    assert promoted == final_path
    assert final_path.exists()
    assert not temp_path.exists()


def test_unprobeable_mp4_temp_is_not_promoted(tmp_path, monkeypatch):
    temp_path = tmp_path / "123456789_hq.mp4.temp"
    temp_path.write_bytes(b"not actually parsed because ffprobe is mocked")
    monkeypatch.setattr(downloader, "_probe_media_duration_s", lambda path: None)

    promoted = downloader._promote_finished_temp_file(temp_path)

    assert promoted is None
    assert temp_path.exists()


def test_probeable_mp4_temp_is_deleted_when_final_exists(tmp_path, monkeypatch):
    final_path = tmp_path / "123456789_hq.mp4"
    temp_path = tmp_path / "123456789_hq.mp4.temp"
    final_path.write_bytes(b"final media")
    temp_path.write_bytes(b"duplicate temp media")
    monkeypatch.setattr(downloader, "_probe_media_duration_s", lambda path: 5400.0)

    promoted = downloader._promote_finished_temp_file(temp_path)

    assert promoted is None
    assert final_path.exists()
    assert not temp_path.exists()
