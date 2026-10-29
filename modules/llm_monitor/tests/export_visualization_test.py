import json
from zipfile import ZIP_DEFLATED, ZipFile

from llm_monitor.evidence_export import _csv_safe, preview_evidence_package, verify_evidence_package, write_evidence_package
from llm_monitor.visualization import render_session, write_visualization
from llm_monitor.storage import TelemetryStore


def _empty_session(store):
    store.ingest_poll("opencode", "http://test", "s1",
                      {"polled_at": "2026-01-01T00:00:00+00:00", "normalized_state": "idle",
                       "history_coverage": {"status": "partial", "source": "bounded"}, "errors": {}}, [])


def test_export_requires_explicit_write_and_verifies_tampering(tmp_path):
    database = tmp_path / "telemetry.db"
    target = tmp_path / "evidence.zip"
    with TelemetryStore(database) as store:
        _empty_session(store)
        preview = preview_evidence_package(store=store, session_ids=["s1"], endpoints=None,
                                           output_path=target)
        assert not preview["written"]
        assert not target.exists()
        result = write_evidence_package(store=store, session_ids=["s1"], endpoints=None,
                                        output_path=target)
    assert result["written"] and verify_evidence_package(target)["ok"]
    with ZipFile(target) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        member = next(name for name in manifest["files"] if name.endswith("session.json"))
    tampered = tmp_path / "tampered.zip"
    with ZipFile(target) as source, ZipFile(tampered, "w", ZIP_DEFLATED) as archive:
        for name in source.namelist():
            archive.writestr(name, b"tampered" if name == member else source.read(name))
    verified = verify_evidence_package(tampered)
    assert not verified["ok"]
    assert any("checksum mismatch" in error for error in verified["errors"])
    missing = tmp_path / "missing.zip"
    with ZipFile(target) as source, ZipFile(missing, "w", ZIP_DEFLATED) as archive:
        for name in source.namelist():
            if name != member:
                archive.writestr(name, source.read(name))
    assert any("missing file" in error for error in verify_evidence_package(missing)["errors"])
    assert _csv_safe("  =1+1").startswith("'")


def test_visualization_escapes_untrusted_text_and_writes_only_when_called(tmp_path):
    analysis = {"session": {"session_id": "<img onerror='x'>",
                             "first_observed": "2026-01-01T00:00:00+00:00"},
                "metrics": {"execution": {"observed_wall_seconds": {"value": 1}},
                            "timeline": {"markers": [
                    {"category": "tool", "timestamp": "2026-01-01T00:00:00+00:00",
                     "subtype": "<script>alert(1)</script>"}]}}}
    svg = render_session(analysis)
    assert "&lt;img" in svg and "&lt;script&gt;" in svg
    assert 'class="marker"' in svg
    target = tmp_path / "timeline.svg"
    assert not target.exists()
    write_visualization(target, svg)
    assert target.read_text(encoding="utf-8") == svg
