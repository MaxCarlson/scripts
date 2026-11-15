"""Red/green hardening tests for H4.8 bundle integrity, determinism, extraction, and manifest enforcement."""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path

import pytest

from tools.h4_qualification import bundle_builder, source_integrity, windows_acceptance


def _build_test_bundle(tmp_path: Path, name: str = "build1") -> tuple[Path, Path, str]:
    out = tmp_path / name
    res = bundle_builder.build_bundle(
        repo_root=Path(__file__).resolve().parents[3],
        output_dir=out,
        new_ref="c1e66897167ae7575eb2fea9f2d3a9089d9fb653",
        apply=True,
    )
    return out, Path(res["archive_path"]), res["archive_sha256"]


def _repack_zip_with_edit(src_zip: Path, dst_zip: Path, target_suffix: str, new_bytes: bytes) -> None:
    with zipfile.ZipFile(src_zip, "r") as src, zipfile.ZipFile(dst_zip, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith(target_suffix):
                data = new_bytes
            dst.writestr(info, data)


@pytest.mark.parametrize("target_suffix", [
    "harness/windows_acceptance.py",
    "harness/source_integrity.py",
    "scripts/Verify-H4GuestBundle.ps1",
    "dependencies/requirements.txt",
    "dependencies/dependency-lock.json",
    "config/config.production-template.yaml",
    "sources/rc-1.0.0/modules/resource_metrics/resource_metrics/__init__.py",
])
def test_b1_component_tampering_is_rejected(tmp_path, target_suffix):
    _, zip_path, expected_sha = _build_test_bundle(tmp_path)
    tampered = tmp_path / "tampered.zip"
    _repack_zip_with_edit(zip_path, tampered, target_suffix, b"# tampered payload\n")
    tampered_sha = hashlib.sha256(tampered.read_bytes()).hexdigest()

    # Even if an attacker supplies the tampered ZIP's own SHA, internal component manifest must reject it.
    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        bundle_builder.verify_bundle_archive(tampered, expected_archive_sha256=tampered_sha)
    assert exc.value.code in {"bundle_component_mismatch", "bundle_component_missing"}


def test_c1_trusted_external_archive_digest_is_enforced(tmp_path):
    _, zip_path, expected_sha = _build_test_bundle(tmp_path)

    verified = bundle_builder.verify_bundle_archive(zip_path, expected_archive_sha256=expected_sha)
    assert verified["verified"] is True

    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        bundle_builder.verify_bundle_archive(zip_path, expected_archive_sha256="0" * 64)
    assert exc.value.code == "bundle_archive_digest_mismatch"

    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        bundle_builder.verify_bundle_archive(zip_path)
    assert exc.value.code == "bundle_archive_digest_required"


def test_d1_two_builds_produce_byte_identical_archives(tmp_path):
    _, zip1, sha1 = _build_test_bundle(tmp_path, "build_one")
    time.sleep(0.05)
    _, zip2, sha2 = _build_test_bundle(tmp_path, "build_two")

    assert sha1 == sha2
    assert zip1.read_bytes() == zip2.read_bytes()


def test_e1_guest_mutation_profiles_require_source_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("RC_H4_DISPOSABLE_GUEST_AUTHORIZED", windows_acceptance.AUTHORIZATION_PHRASE)
    run_root = tmp_path / "h4-rc-no-manifest"
    run_root.mkdir()
    guest = {
        "os": {"caption": "Windows 11"},
        "computer": {"manufacturer": "Microsoft Corporation", "model": "Virtual Machine", "hypervisor_present": True},
        "queries": {"tasks": "ok", "services": "ok", "processes": "ok"},
        "rc_tasks": [], "rc_services": [], "rc_processes": [],
    }
    for profile in ("install", "upgrade", "rollback", "full"):
        rc = windows_acceptance.main([
            "--test-root", str(run_root), "--apply", "--profile", profile,
            "--authorization", windows_acceptance.AUTHORIZATION_PHRASE,
            "--authorize-guest-mutation", "--json",
        ], evidence_override=guest, is_windows=True)
        assert rc in {2, 3}
        preflight = json.loads((run_root / "preflight.json").read_text(encoding="utf-8"))
        assert "source_manifest_required" in preflight["profile_blockers"]


def test_f1_unsafe_zip_members_and_collisions_are_rejected(tmp_path):
    _, zip_path, _ = _build_test_bundle(tmp_path)

    for bad_name in ("../escape.txt", "/abs/path.txt", "C:\\drive\\path.txt", "sub/./dot.txt"):
        bad_zip = tmp_path / f"bad_{abs(hash(bad_name))}.zip"
        with zipfile.ZipFile(zip_path, "r") as src, zipfile.ZipFile(bad_zip, "w") as dst:
            for info in src.infolist():
                dst.writestr(info, src.read(info.filename))
            bad_info = zipfile.ZipInfo(bad_name)
            bad_info.filename = bad_name
            dst.writestr(bad_info, b"evil")
        bad_sha = hashlib.sha256(bad_zip.read_bytes()).hexdigest()
        with pytest.raises(source_integrity.SourceIntegrityError) as exc:
            bundle_builder.verify_bundle_archive(bad_zip, expected_archive_sha256=bad_sha)
        assert exc.value.code == "bundle_archive_unsafe_member"

    # Direct backslash and NUL-byte guard checks (Python zipfile normalizes '\' / truncates '\x00' on read)
    for raw_name in ("sub\\backslash.txt", "sub/\x00null.txt"):
        raw_info = zipfile.ZipInfo("sub/ok.txt")
        raw_info.filename = raw_name
        with pytest.raises(source_integrity.SourceIntegrityError) as exc:
            bundle_builder._validate_zip_members(
                type("FakeZip", (), {"infolist": lambda self, info=raw_info: [info]})()
            )
        assert exc.value.code == "bundle_archive_unsafe_member"

    # Case-insensitive collision
    dup_zip = tmp_path / "dup.zip"
    with zipfile.ZipFile(zip_path, "r") as src, zipfile.ZipFile(dup_zip, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("README.md".lower(), b"collision")
    dup_sha = hashlib.sha256(dup_zip.read_bytes()).hexdigest()
    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        bundle_builder.verify_bundle_archive(dup_zip, expected_archive_sha256=dup_sha)
    assert exc.value.code == "bundle_archive_duplicate_member"
