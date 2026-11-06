"""Synthetic tests for AEBN historical download reconciliation."""

from pathlib import Path
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from ytaedl.aebn_reconcile.scanner import parse_scene_inputs, probe_video, scan_reconciliation
from ytaedl.aebn_reconcile.store import ReconciliationStore
from ytaedl.aebn_reconcile.downloader import download_missing
from ytaedl.aebn_reconcile.verifier import verify_replacements
from ytaedl.aebn_reconcile.review import decide_candidate
from ytaedl.aebn_reconcile.deletion import delete_approved
from ytaedl.aebn_reconcile.archive_sync import sync_verified_archives
from ytaedl.aebn_reconcile.cli import make_parser
from ytaedl.domain_index import DomainIndex


MOVIE_URL = "https://straight.aebn.com/straight/movies/322251/busty-vixens-2"
SCENE_URLS = [f"{MOVIE_URL}#scene-{scene_id}" for scene_id in ("1303588", "1303589", "1303590")]


def _probe(duration: float) -> dict:
    return {
        "duration": duration,
        "video": True,
        "video_continuity": {"packet_count": max(1000, int(duration * 25)), "invalid_packets": 0,
                             "dts_regressions": 0, "max_pts_gap_s": 0.04, "max_dts_gap_s": 0.04,
                             "longest_tiny_duration_run": 0, "longest_tiny_dts_run": 0},
        "streams": {
            kind: {"duration": duration, "timestamp_span": duration, "packet_count": 100,
                   "first_pts": 0.0, "last_pts": duration, "time_base": "1/1000"}
            for kind in ("video", "audio")
        },
    }


def test_reconciliation_rejects_internal_video_gap():
    from ytaedl.aebn_reconcile.verifier import _validate_av_coverage
    facts = _probe(700)
    facts["video_continuity"] = {"packet_count": 1000, "invalid_packets": 0, "dts_regressions": 0,
                                 "max_pts_gap_s": 100, "max_dts_gap_s": 100,
                                 "longest_tiny_duration_run": 0, "longest_tiny_dts_run": 0}
    result = _validate_av_coverage(facts, 700)
    assert result["valid"] is False
    assert any("gap" in error for error in result["errors"])


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools unavailable")
def test_probe_video_reports_collapsed_video_separately_from_long_audio(tmp_path):
    output = tmp_path / "collapsed-video.mp4"
    subprocess.run(
        [shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
         "-vf", "setpts=0.1*PTS", "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", str(output)], check=True, capture_output=True, text=True,
    )

    facts = probe_video(output)

    assert facts is not None
    assert facts["duration"] > 2.9
    assert facts["streams"]["video"]["duration"] < 1.0
    assert facts["streams"]["audio"]["duration"] > 2.9
    assert facts["streams"]["video"]["timestamp_span"] < 1.0


def test_parse_scene_inputs_preserves_fragments_and_source_lines(tmp_path):
    url_file = tmp_path / "scenes list.txt"
    url_file.write_text("\n".join([SCENE_URLS[0], "not a URL", SCENE_URLS[1], SCENE_URLS[0]]), encoding="utf-8")

    parsed = parse_scene_inputs([url_file])

    assert [scene.original_url for scene in parsed.requests] == SCENE_URLS[:2]
    assert parsed.requests[0].scene_id == "1303588"
    assert parsed.requests[0].sources == [(str(url_file.resolve()), 1), (str(url_file.resolve()), 4)]
    assert len(parsed.errors) == 1
    assert parsed.errors[0].line_number == 2


def test_scan_resolves_scenes_and_identifies_full_movie_without_archive_trust(tmp_path):
    root = tmp_path / "media root"
    root.mkdir()
    movie_file = root / "Studio - Busty Vixens 2 1080p.mp4"
    movie_file.write_bytes(b"synthetic full movie")
    scene_file = root / "Studio - Busty Vixens 2 Scene 2 1080p.mp4"
    scene_file.write_bytes(b"synthetic scene")
    url_file = tmp_path / "scenes.txt"
    url_file.write_text("\n".join(SCENE_URLS), encoding="utf-8")

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [
            SimpleNamespace(scene_id="1303588", start_timing=0, end_timing=700),
            SimpleNamespace(scene_id="1303589", start_timing=700, end_timing=1400),
            SimpleNamespace(scene_id="1303590", start_timing=1400, end_timing=2100),
        ]

        def scene_ordinal_for_id(self, scene_id):
            ids = [scene.scene_id for scene in self.scenes]
            return ids.index(scene_id) + 1

    def probe(path):
        return {"duration": 3600 if Path(path) == movie_file else 700, "video": True}

    db = tmp_path / "state.sqlite"
    result = scan_reconciliation(
        files=[url_file],
        download_roots=[root],
        archive_dir=tmp_path / "archive",
        database_path=db,
        movie_factory=lambda _url, _session: FakeMovie(),
        session=object(),
        probe_video_fn=probe,
    )

    assert result.summary["unique_scenes"] == 3
    assert result.summary["verified_scenes"] == 0
    assert result.summary["missing_scenes"] == 2
    assert result.summary["full_movie_candidates"] == 1
    assert not (tmp_path / "archive").exists()

    with ReconciliationStore(db) as store:
        scenes = store.list_scenes()
        assert [scene["ordinal"] for scene in scenes] == [1, 2, 3]
        assert scenes[1]["status"] == "scene_candidate_unverified"
        candidates = store.list_candidates()
        original = next(candidate for candidate in candidates if candidate["classification"] == "full_movie")
        assert original["approval"] == "undecided"
        assert not original["eligible"]
    assert download_missing(db, apply=False)["planned"] == 3
    verification = verify_replacements(db, probe_video_fn=lambda _path: _probe(700))
    assert verification["verified"] == 1
    with ReconciliationStore(db) as store:
        assert store.list_scenes()[1]["status"] == "scene_verified"


def test_metadata_failure_records_unknown_mapping_and_never_invents_ordinal(tmp_path):
    url_file = tmp_path / "one.txt"
    url_file.write_text(SCENE_URLS[0], encoding="utf-8")

    def fail_movie(_url, _session):
        raise OSError("metadata unavailable")

    result = scan_reconciliation(
        files=[url_file], download_roots=[], archive_dir=None, database_path=tmp_path / "state.sqlite",
        movie_factory=fail_movie, session=object(), offline=False,
    )

    assert result.summary["metadata_errors"] == 1
    with ReconciliationStore(tmp_path / "state.sqlite") as store:
        scene = store.list_scenes()[0]
        assert scene["ordinal"] is None
        assert scene["status"] == "metadata_error"


def test_duplicate_scene_ids_in_metadata_fail_closed(tmp_path):
    url_file = tmp_path / "one.txt"
    url_file.write_text(SCENE_URLS[0], encoding="utf-8")

    class DuplicateMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="1303588"), SimpleNamespace(scene_id="1303588")]

        def scene_ordinal_for_id(self, _scene_id):
            raise ValueError("Duplicate AEBN scene ID metadata: 1303588")

    result = scan_reconciliation(
        files=[url_file], download_roots=[], archive_dir=None, database_path=tmp_path / "state.sqlite",
        movie_factory=lambda _url, _session: DuplicateMovie(), session=object(),
    )

    assert result.summary["mapping_errors"] == 1
    with ReconciliationStore(tmp_path / "state.sqlite") as store:
        assert store.list_scenes()[0]["ordinal"] is None
        assert store.list_scenes()[0]["status"] == "mapping_error"


def test_unknown_id_never_matches_by_numeric_order(tmp_path):
    url_file = tmp_path / "unknown.txt"
    url_file.write_text(f"{MOVIE_URL}#scene-9999999", encoding="utf-8")

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="1303588"), SimpleNamespace(scene_id="1303589")]

        def scene_ordinal_for_id(self, scene_id):
            raise ValueError(f"AEBN scene ID {scene_id} not found in movie")

    scan_reconciliation(
        files=[url_file], download_roots=[], archive_dir=None, database_path=tmp_path / "state.sqlite",
        movie_factory=lambda _url, _session: FakeMovie(), session=object(),
    )

    with ReconciliationStore(tmp_path / "state.sqlite") as store:
        assert store.list_scenes()[0]["ordinal"] is None
        assert store.list_scenes()[0]["status"] == "mapping_error"


def test_missing_scene_download_uses_scene_id_and_preserves_historical_movie(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    original = root / "Studio - Busty Vixens 2 1080p.mp4"
    original.write_bytes(b"original movie")
    url_file = tmp_path / "scenes.txt"
    url_file.write_text(SCENE_URLS[0], encoding="utf-8")
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "ae-scenes.txt").write_text(f"{SCENE_URLS[0]}\tdownloaded\n", encoding="utf-8")

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="1303588", start_timing=0, end_timing=700)]

        def scene_ordinal_for_id(self, _scene_id):
            return 1

    db = tmp_path / "state.sqlite"
    scan_reconciliation(
        files=[url_file], download_roots=[root], archive_dir=archive, database_path=db,
        movie_factory=lambda _url, _session: FakeMovie(), session=object(),
        probe_video_fn=lambda _path: {"duration": 3600, "video": True},
    )
    calls = []

    def runner(command):
        calls.append(command)
        output_dir = Path(command[command.index("-o") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / "Studio - Busty Vixens 2 Scene 1 1080p.mp4"
        output.write_bytes(b"replacement scene")
        return 0, [{"event": "complete", "path": str(output), "file_size": output.stat().st_size}]

    preview = download_missing(db, apply=False, threads=1, runner=runner)
    assert preview["planned"] == 1
    assert calls == []

    result = download_missing(db, apply=True, threads=1, runner=runner)
    assert result["completed"] == 1
    assert len(calls) == 1
    assert calls[0][calls[0].index("-I") + 1] == "1303588"
    assert calls[0][-1] == SCENE_URLS[0]
    assert original.read_bytes() == b"original movie"
    assert "AEBN Scene Replacements" in calls[0][calls[0].index("-o") + 1]

    verification = verify_replacements(db, probe_video_fn=lambda _path: _probe(700))
    assert verification["verified"] == 1
    with ReconciliationStore(db) as store:
        assert store.list_scenes()[0]["status"] == "scene_verified"

    again = download_missing(db, apply=True, threads=1, runner=runner)
    assert again["completed"] == 0
    assert len(calls) == 1


def test_interrupted_download_is_recovered_and_retryable(tmp_path, monkeypatch):
    from ytaedl.aebn_reconcile import downloader as download_module

    root = tmp_path / "media"
    root.mkdir()
    url_file = tmp_path / "one.txt"
    url_file.write_text(SCENE_URLS[0], encoding="utf-8")

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="1303588", start_timing=0, end_timing=700)]

        def scene_ordinal_for_id(self, _scene_id):
            return 1

    db = tmp_path / "state.sqlite"
    scan_reconciliation(files=[url_file], download_roots=[root], archive_dir=None, database_path=db,
                        movie_factory=lambda _url, _session: FakeMovie(), session=object())
    with ReconciliationStore(db) as store:
        store.execute("UPDATE download_jobs SET status='running',process_id=99999999 WHERE scene_id='1303588'")
    monkeypatch.setattr(download_module, "_process_is_alive", lambda _pid: False)

    output = root / "AEBN Scene Replacements" / "322251" / "Busty Vixens 2 Scene 1.mp4"

    def runner(command):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"scene")
        return 0, [{"event": "complete", "path": str(output)}]

    result = download_missing(db, apply=True, runner=runner)

    assert result["recovered"] == 1
    assert result["completed"] == 1
    with ReconciliationStore(db) as store:
        job = store.list_jobs()[0]
        assert job["status"] == "downloaded"
        assert job["attempts"] == 1
        assert store.execute("SELECT COUNT(*) FROM events WHERE kind='download_interrupted'").fetchone()[0] == 1


def test_download_failure_cannot_make_original_deletion_eligible(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    original = root / "Studio - Busty Vixens 2 1080p.mp4"
    original.write_bytes(b"synthetic original")
    url_file = tmp_path / "one.txt"
    url_file.write_text(SCENE_URLS[0], encoding="utf-8")

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="1303588", start_timing=0, end_timing=700)]

        def scene_ordinal_for_id(self, _scene_id):
            return 1

    db = tmp_path / "state.sqlite"
    scan_reconciliation(files=[url_file], download_roots=[root], archive_dir=None, database_path=db,
                        movie_factory=lambda _url, _session: FakeMovie(), session=object(),
                        probe_video_fn=lambda _path: {"duration": 3600, "video": True})
    result = download_missing(db, apply=True, runner=lambda _command: (3, [{"event": "error", "message": "synthetic failure"}]))

    assert result["failed"] == 1
    with ReconciliationStore(db) as store:
        candidate_id = store.execute("SELECT candidate_id FROM media_candidates WHERE classification='full_movie'").fetchone()[0]
        with pytest.raises(ValueError, match="verified"):
            decide_candidate(store, candidate_id, "approve", confirm_identity=True)
    preview = delete_approved(db, apply=False, in_use_check=lambda _path: False,
                              probe_video_fn=lambda _path: _probe(700))
    assert preview["planned"] == []
    assert original.exists()


def test_verification_rejects_movie_length_output_mislabeled_as_scene(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    url_file = tmp_path / "one.txt"
    url_file.write_text(SCENE_URLS[0], encoding="utf-8")

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="1303588", start_timing=0, end_timing=700)]

        def scene_ordinal_for_id(self, _scene_id):
            return 1

    db = tmp_path / "state.sqlite"
    scan_reconciliation(files=[url_file], download_roots=[root], archive_dir=None, database_path=db,
                        movie_factory=lambda _url, _session: FakeMovie(), session=object())
    output = root / "AEBN Scene Replacements" / "322251" / "Studio - Busty Vixens 2 Scene 1 1080p.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"synthetic output")
    with ReconciliationStore(db) as store:
        store.execute("UPDATE download_jobs SET status='downloaded',exit_code=0,output_path=? WHERE scene_id=?",
                      (str(output), "1303588"))

    result = verify_replacements(db, probe_video_fn=lambda _path: _probe(3600))

    assert result["failed"] == 1
    with ReconciliationStore(db) as store:
        scene = store.list_scenes()[0]
        assert scene["status"] == "scene_invalid"
        job = store.list_jobs()[0]
        assert job["verification_status"] == "failed"


def test_reconciliation_rejects_two_second_video_with_full_scene_audio(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    url_file = tmp_path / "one.txt"
    url_file.write_text(SCENE_URLS[0], encoding="utf-8")

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="1303588", start_timing=0, end_timing=700)]

        def scene_ordinal_for_id(self, _scene_id):
            return 1

    db = tmp_path / "state.sqlite"
    scan_reconciliation(files=[url_file], download_roots=[root], archive_dir=None, database_path=db,
                        movie_factory=lambda _url, _session: FakeMovie(), session=object())
    output = root / "AEBN Scene Replacements" / "322251" / "Studio - Busty Vixens 2 Scene 1 1080p.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"synthetic corrupted replacement")
    with ReconciliationStore(db) as store:
        store.execute("UPDATE download_jobs SET status='downloaded',exit_code=0,output_path=? WHERE scene_id=?",
                      (str(output), "1303588"))

    corrupted = _probe(700)
    corrupted["streams"]["video"].update({"duration": 2.0, "timestamp_span": 2.0, "packet_count": 2200})
    result = verify_replacements(db, probe_video_fn=lambda _path: corrupted)

    assert result["failed"] == 1
    with ReconciliationStore(db) as store:
        scene = store.list_scenes()[0]
        job = store.list_jobs()[0]
        assert scene["status"] == "scene_invalid"
        assert "video" in scene["status_detail"]
        evidence = json.loads(job["verification_json"])
        assert evidence["verification_contract"] == 4
        assert job["verification_status"] == "failed"


def test_approval_requires_every_linked_scene_verified_and_binds_evidence(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    original = root / "Studio - Busty Vixens 2 1080p.mp4"
    original.write_bytes(b"movie")
    url_file = tmp_path / "three.txt"
    url_file.write_text("\n".join(SCENE_URLS), encoding="utf-8")

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id=scene_id, start_timing=i * 700, end_timing=(i + 1) * 700)
                  for i, scene_id in enumerate(("1303588", "1303589", "1303590"))]

        def scene_ordinal_for_id(self, scene_id):
            return [scene.scene_id for scene in self.scenes].index(scene_id) + 1

    db = tmp_path / "state.sqlite"
    scan_reconciliation(files=[url_file], download_roots=[root], archive_dir=None, database_path=db,
                        movie_factory=lambda _url, _session: FakeMovie(), session=object(),
                        probe_video_fn=lambda _path: {"duration": 3600, "video": True})
    with ReconciliationStore(db) as store:
        candidate = store.execute("SELECT candidate_id FROM media_candidates WHERE classification='full_movie'").fetchone()
        candidate_id = candidate[0]
        with pytest.raises(ValueError, match="all requested"):
            decide_candidate(store, candidate_id, "approve", confirm_identity=True)
        for ordinal, scene_id in enumerate(("1303588", "1303589", "1303590"), 1):
            output = root / "AEBN Scene Replacements" / "322251" / f"Busty Vixens 2 Scene {ordinal}.mp4"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(scene_id.encode())
            store.execute("UPDATE requested_scenes SET status='scene_verified' WHERE scene_id=?", (scene_id,))
            stat = output.stat()
            store.execute("UPDATE download_jobs SET status='downloaded',exit_code=0,output_path=? WHERE scene_id=?",
                          (str(output), scene_id))
    verify_replacements(db, probe_video_fn=lambda _path: _probe(700))
    with ReconciliationStore(db) as store:
        result = decide_candidate(store, candidate_id, "approve", confirm_identity=True)
        assert result["approval_fingerprint"]
        candidate = store.list_candidates()[0]
        assert candidate["eligible"]
        assert candidate["approval"] == "approved"
        job = store.list_jobs()[0]
        old_evidence = json.loads(job["verification_json"])
        old_evidence["verification_contract"] = 2
        store.execute("UPDATE download_jobs SET verification_json=? WHERE movie_key=? AND scene_id=?",
                      (json.dumps(old_evidence), job["movie_key"], job["scene_id"]))
        with pytest.raises(ValueError, match="current audio/video verification"):
            decide_candidate(store, candidate_id, "approve", confirm_identity=True)


def test_delete_requires_recorded_approval_and_quarantines_synthetic_original(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    original = root / "Studio - Busty Vixens 2 1080p.mp4"
    original.write_bytes(b"synthetic original movie")
    url_file = tmp_path / "one.txt"
    url_file.write_text(SCENE_URLS[0], encoding="utf-8")

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="1303588", start_timing=0, end_timing=700)]

        def scene_ordinal_for_id(self, _scene_id):
            return 1

    replacement = root / "AEBN Scene Replacements" / "322251" / "Studio - Busty Vixens 2 Scene 1 1080p.mp4"
    replacement.parent.mkdir(parents=True)
    replacement.write_bytes(b"synthetic scene")
    db = tmp_path / "state.sqlite"
    scan_reconciliation(files=[url_file], download_roots=[root], archive_dir=None, database_path=db,
                        movie_factory=lambda _url, _session: FakeMovie(), session=object(),
                        probe_video_fn=lambda path: _probe(3600 if Path(path) == original else 700))
    with ReconciliationStore(db) as store:
        store.execute("UPDATE download_jobs SET status='downloaded',exit_code=0,output_path=? WHERE scene_id='1303588'",
                      (str(replacement),))
    verify_replacements(db, probe_video_fn=lambda _path: _probe(700))
    with ReconciliationStore(db) as store:
        candidate_id = store.execute("SELECT candidate_id FROM media_candidates WHERE classification='full_movie'").fetchone()[0]
        decide_candidate(store, candidate_id, "approve", confirm_identity=True)

    def probe(path):
        return _probe(3600 if Path(path) == original else 700)
    preview = delete_approved(db, apply=False, in_use_check=lambda _path: False, probe_video_fn=probe)
    assert len(preview["planned"]) == 1, preview
    assert original.exists()
    assert preview["total_bytes"] == len(b"synthetic original movie")
    with pytest.raises(ValueError, match="exactly"):
        delete_approved(db, apply=True, confirm="", in_use_check=lambda _path: False, probe_video_fn=probe)

    result = delete_approved(db, apply=True, confirm="DELETE 1", in_use_check=lambda _path: False, probe_video_fn=probe)

    assert result["removed"][0]["state"] == "quarantined"
    assert not original.exists()
    assert replacement.exists()
    destination = Path(result["removed"][0]["destination"])
    assert destination.exists()
    assert destination.read_bytes() == b"synthetic original movie"


def test_metadata_is_cached_and_available_to_offline_scans(tmp_path):
    url_file = tmp_path / "scenes.txt"
    url_file.write_text(SCENE_URLS[0], encoding="utf-8")
    calls = []

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="1303588", start_timing=0, end_timing=700)]

        def scene_ordinal_for_id(self, _scene_id):
            return 1

    db = tmp_path / "state.sqlite"

    def factory(url, session):
        calls.append((url, session))
        return FakeMovie()

    scan_reconciliation(files=[url_file], download_roots=[], archive_dir=None, database_path=db,
                        movie_factory=factory, session=object())
    result = scan_reconciliation(files=[url_file], download_roots=[], archive_dir=None, database_path=db,
                                 offline=True)

    assert len(calls) == 1
    assert result.summary["mapping_errors"] == 0
    with ReconciliationStore(db) as store:
        assert store.list_scenes()[0]["ordinal"] == 1


def test_rescan_keeps_earlier_scenes_required_for_original_eligibility(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "Studio - Busty Vixens 2.mp4").write_bytes(b"synthetic movie")
    first_file, second_file = tmp_path / "first.txt", tmp_path / "second.txt"
    first_file.write_text(SCENE_URLS[0], encoding="utf-8")
    second_file.write_text(SCENE_URLS[1], encoding="utf-8")

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="1303588", start_timing=0, end_timing=700),
                  SimpleNamespace(scene_id="1303589", start_timing=700, end_timing=1400)]

        def scene_ordinal_for_id(self, scene_id):
            return [scene.scene_id for scene in self.scenes].index(scene_id) + 1

    db = tmp_path / "state.sqlite"
    factory_calls = []

    def factory(_url, _session):
        factory_calls.append(1)
        return FakeMovie()

    kwargs = {"download_roots": [root], "archive_dir": None, "database_path": db,
              "movie_factory": factory, "session": object(),
              "probe_video_fn": lambda _path: {"duration": 3600, "video": True}}
    scan_reconciliation(files=[first_file], **kwargs)
    scan_reconciliation(files=[second_file], **kwargs)

    with ReconciliationStore(db) as store:
        assert len(store.list_scenes()) == 2
        candidate = store.list_candidates()[0]
        assert candidate["classification"] == "full_movie"
        assert candidate["required_scene_count"] == 2
        assert candidate["verified_scene_count"] == 0
    assert len(factory_calls) == 1


def test_archive_sync_is_targeted_locked_and_idempotent(tmp_path):
    source_dir = tmp_path / "ae-stars"
    source_dir.mkdir()
    url_file = source_dir / "scenes.txt"
    url_file.write_text(SCENE_URLS[0], encoding="utf-8")
    archive = tmp_path / "archive"
    archive.mkdir()
    archive_file = archive / "ae-scenes.txt"
    archive_file.write_text(f"already\t0.100\tdate\t1MiB\t\t{SCENE_URLS[0]}\n", encoding="utf-8")
    index = DomainIndex.build([url_file])
    index.save(archive / "domain_index.json")

    class FakeMovie:
        movie_id = "322251"
        url_content_type = "straight"
        title = "Busty Vixens 2"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="1303588", start_timing=0, end_timing=700)]

        def scene_ordinal_for_id(self, _scene_id):
            return 1

    root = tmp_path / "media"
    root.mkdir()
    scene_file = root / "Studio - Busty Vixens 2 Scene 1 1080p.mp4"
    scene_file.write_bytes(b"scene")
    db = tmp_path / "state.sqlite"
    scan_reconciliation(files=[url_file], download_roots=[root], archive_dir=archive, database_path=db,
                        movie_factory=lambda _url, _session: FakeMovie(), session=object(),
                        probe_video_fn=lambda _path: {"duration": 700, "video": True})
    verify_replacements(db, probe_video_fn=lambda _path: _probe(700))

    preview = sync_verified_archives(db, apply=False)
    assert preview["planned_urls"] == 1
    assert "already" in archive_file.read_text(encoding="utf-8")
    applied = sync_verified_archives(db, apply=True)

    assert applied["updated"] == 1
    lines = archive_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert lines[0].split("\t", 1)[0] == "downloaded"
    assert lines[0].split("\t")[-1] == SCENE_URLS[0]
    assert DomainIndex.load(archive / "domain_index.json").is_finished(SCENE_URLS[0])
    assert sync_verified_archives(db, apply=True)["updated"] == 1


def test_reconcile_cli_parser_exposes_all_workflow_stages():
    parser = make_parser()
    for command in ("scan", "status", "download", "verify", "review", "delete", "archive-sync", "export"):
        extra = ["-f", "input.txt", "-L", "media"] if command == "scan" else []
        parsed = parser.parse_args([command, "-p", "state.sqlite"] + extra)
        assert parsed.command == command


def test_same_title_different_movie_ids_remain_ambiguous(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    scene_file = root / "Studio - Same Movie Title Scene 1 1080p.mp4"
    scene_file.write_bytes(b"ambiguous scene")
    url_file = tmp_path / "same-title.txt"
    urls = [
        "https://straight.aebn.com/straight/movies/111/same-movie-title#scene-1001",
        "https://straight.aebn.com/straight/movies/222/same-movie-title#scene-2001",
    ]
    url_file.write_text("\n".join(urls), encoding="utf-8")

    class FakeMovie:
        url_content_type = "straight"
        title = "Same Movie Title"
        studio_name = "Studio"
        total_duration_seconds = 3600
        scenes = [SimpleNamespace(scene_id="", start_timing=0, end_timing=700)]

        def __init__(self, movie_id, scene_id):
            self.movie_id = movie_id
            self.scenes = [SimpleNamespace(scene_id=scene_id, start_timing=0, end_timing=700)]

        def scene_ordinal_for_id(self, scene_id):
            return 1 if self.scenes[0].scene_id == scene_id else (_ for _ in ()).throw(ValueError("unknown"))

    def factory(url, _session):
        movie_id = url.split("/movies/")[1].split("/")[0]
        scene_id = "1001" if movie_id == "111" else "2001"
        return FakeMovie(movie_id, scene_id)

    db = tmp_path / "state.sqlite"
    result = scan_reconciliation(files=[url_file], download_roots=[root], archive_dir=None, database_path=db,
                                 movie_factory=factory, session=object(),
                                 probe_video_fn=lambda _path: {"duration": 700, "video": True})

    assert result.summary["verified_scenes"] == 0
    with ReconciliationStore(db) as store:
        assert {scene["status"] for scene in store.list_scenes()} == {"scene_ambiguous"}
        candidates = store.list_candidates()
        assert len(candidates) == 2
        assert {candidate["classification"] for candidate in candidates} == {"unknown"}
        with pytest.raises(ValueError, match="multiple AEBN movie IDs"):
            decide_candidate(store, candidates[0]["candidate_id"], "approve", confirm_identity=True)
