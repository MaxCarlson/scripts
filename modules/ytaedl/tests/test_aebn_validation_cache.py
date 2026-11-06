from pathlib import Path

from ytaedl.aebn_validation_cache import current_verified_urls, record_verified_output, validated_aebn_event
from ytaedl.domain_index import DomainIndex


URL = "https://straight.aebn.com/straight/movies/123/test#scene-456"


def event(path: Path):
    stream = {"duration_s": 30.0, "packet_span_s": 29.96, "packet_count": 750}
    return {"event": "complete", "path": str(path), "file_size": path.stat().st_size,
            "validation": {"valid": True, "validation_contract": 3,
            "evidence": {"expected_duration_s": 30, "streams": {"video": stream, "audio": stream},
                         "video_continuity": {"packet_count": 750, "invalid_packets": 0,
                                              "dts_regressions": 0, "max_pts_gap_s": 0.04,
                                              "max_dts_gap_s": 0.04, "longest_tiny_duration_run": 0,
                                              "longest_tiny_dts_run": 0}}}}


def test_verified_cache_binds_current_contract_and_file_identity(tmp_path):
    output = tmp_path / "scene.mp4"
    output.write_bytes(b"valid fixture")
    archive = tmp_path / "archive"
    assert record_verified_output(archive, URL, event(output))
    assert current_verified_urls(archive) == {URL}
    output.write_bytes(b"changed fixture bytes")
    assert current_verified_urls(archive) == set()


def test_old_or_incomplete_validation_is_not_trusted(tmp_path):
    output = tmp_path / "scene.mp4"
    output.write_bytes(b"fixture")
    old = event(output)
    old["validation"]["validation_contract"] = 2
    assert not validated_aebn_event(old)
    assert not record_verified_output(tmp_path / "archive", URL, old)
    assert not validated_aebn_event({"event": "complete", "validation": {"valid": True}})
    wrong_size = event(output)
    wrong_size["file_size"] += 1
    assert not validated_aebn_event(wrong_size)
    incomplete = event(output)
    incomplete["validation"]["evidence"]["streams"]["video"] = {}
    assert not validated_aebn_event(incomplete)
    malformed_path = event(output)
    malformed_path["path"] = {"not": "a path"}
    assert not validated_aebn_event(malformed_path)


def test_aebn_json_parser_preserves_validation_evidence(tmp_path):
    import json
    from procparsers.aebndl import parse_line
    output = tmp_path / "scene.mp4"
    output.write_bytes(b"fixture")
    original = event(output)
    assert validated_aebn_event(parse_line(json.dumps(original)))


def test_domain_index_requeues_only_unverified_aebn_successes(tmp_path):
    other = "https://example.com/video"
    verified = "https://straight.aebn.com/straight/movies/123/test#scene-457"
    path = tmp_path / "urls.txt"
    path.write_text("\n".join([URL, verified, other]), encoding="utf-8")
    index = DomainIndex.build([path], finished_urls={URL: "downloaded", verified: "already", other: "downloaded"})
    assert index.requeue_unverified_aebn({verified}) == 1
    assert not index.is_finished(URL)
    assert index.is_finished(verified) and index.is_finished(other)


def test_archive_seeding_requires_current_aebn_file_identity(tmp_path):
    from ytaedl.manager import _load_archive_finished_urls
    archive = tmp_path / "archive"
    archive.mkdir()
    other = "https://example.com/video"
    (archive / "yt-test.txt").write_text(
        f"downloaded\t1\tdate\t1MiB\t\t{URL}\n"
        f"downloaded\t1\tdate\t1MiB\t\t{other}\n", encoding="utf-8")
    assert _load_archive_finished_urls(archive) == {other: "downloaded"}
    output = tmp_path / "scene.mp4"
    output.write_bytes(b"fixture")
    assert record_verified_output(archive, URL, event(output))
    assert _load_archive_finished_urls(archive) == {URL: "downloaded", other: "downloaded"}
    output.write_bytes(b"modified fixture")
    assert _load_archive_finished_urls(archive) == {other: "downloaded"}


def test_persisted_index_restores_unverified_aebn_success(tmp_path):
    urlfile = tmp_path / "urls.txt"
    urlfile.write_text(URL, encoding="utf-8")
    path = tmp_path / "index.json"
    DomainIndex.build([urlfile], finished_urls={URL: "downloaded"}).save(path)
    index = DomainIndex.load(path)
    assert index.is_finished(URL)
    assert index.requeue_unverified_aebn(set()) == 1
    index.save(path)
    assert not DomainIndex.load(path).is_finished(URL)


def test_concurrent_verification_records_are_not_lost(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    output = tmp_path / "scene.mp4"
    output.write_bytes(b"fixture")
    archive = tmp_path / "archive"
    urls = [f"https://straight.aebn.com/straight/movies/123/test#scene-{i}" for i in range(8)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda url: record_verified_output(archive, url, event(output)), urls))
    assert all(results)
    assert current_verified_urls(archive) == set(urls)
