"""Tests for deterministic H4 source-tree hashing, manifest enforcement, and bundle building."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from tools.h4_qualification import bundle_builder, source_integrity, windows_acceptance


def _make_minimal_source(root: Path, *, version: str = "1.0.0", reverse_create: bool = False) -> Path:
    mod = root / "modules" / "resource_coordinator"
    pkg = mod / "resource_coordinator"
    files = [
        ("pyproject.toml", f'[project]\nname = "resource-coordinator"\nversion = "{version}"\n'),
        ("config.production-template.yaml", "service:\n  listen_port: 1235\n"),
        ("resource_coordinator/__init__.py", f'__version__ = "{version}"\n'),
        ("resource_coordinator/installation.py", "# installer\n"),
        ("resource_coordinator/extra.py", "# extra\n"),
    ]
    if reverse_create:
        files = list(reversed(files))
    pkg.mkdir(parents=True, exist_ok=True)
    for rel, content in files:
        target = mod / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return mod


def test_hash_source_tree_is_order_and_location_independent(tmp_path):
    mod_a = _make_minimal_source(tmp_path / "root_a", reverse_create=False)
    mod_b = _make_minimal_source(tmp_path / "space path café" / "root_b", reverse_create=True)
    # Ephemeral artifacts must be ignored
    (mod_b / "__pycache__").mkdir()
    (mod_b / "__pycache__" / "installation.cpython-312.pyc").write_bytes(b"pyc")
    (mod_b / ".pytest_tmp_run").mkdir()
    (mod_b / ".pytest_tmp_run" / "junk.txt").write_text("junk", encoding="utf-8")

    assert source_integrity.hash_source_tree(mod_a) == source_integrity.hash_source_tree(mod_b)


def test_hash_source_tree_detects_empty_dirs_and_content_changes(tmp_path):
    mod = _make_minimal_source(tmp_path / "src")
    baseline = source_integrity.hash_source_tree(mod)

    empty_dir = mod / "empty_subdir"
    empty_dir.mkdir()
    with_empty = source_integrity.hash_source_tree(mod)
    assert with_empty != baseline

    empty_dir.rmdir()
    assert source_integrity.hash_source_tree(mod) == baseline

    (mod / "resource_coordinator" / "installation.py").write_text("# tampered\n", encoding="utf-8")
    assert source_integrity.hash_source_tree(mod) != baseline


def test_verify_source_tree_rejects_tampering_and_manifest_mismatches(tmp_path):
    src = tmp_path / "src"
    mod = _make_minimal_source(src, version="1.0.0")
    digest = source_integrity.hash_source_tree(mod)
    valid_entry = {
        "source_role": "new_1_0_0",
        "repository": "https://github.com/MaxCarlson/scripts",
        "commit_sha": "a" * 40,
        "package_version": "1.0.0",
        "hash_algorithm": source_integrity.HASH_ALGORITHM,
        "source_tree_sha256": digest,
    }
    verified = source_integrity.verify_source_tree(
        src, expected_version="1.0.0", expected_role="new_1_0_0", manifest_entry=valid_entry,
    )
    assert verified["source_tree_sha256"] == digest

    # Stale pinned SHA
    stale = {**valid_entry, "source_tree_sha256": "b" * 64}
    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        source_integrity.verify_source_tree(src, expected_version="1.0.0", expected_role="new_1_0_0", manifest_entry=stale)
    assert exc.value.code == "source_digest_mismatch"

    # Wrong role
    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        source_integrity.verify_source_tree(src, expected_version="1.0.0", expected_role="old_0_14_0", manifest_entry=valid_entry)
    assert exc.value.code == "source_role_mismatch"

    # Wrong version
    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        source_integrity.verify_source_tree(src, expected_version="0.14.0", expected_role="new_1_0_0", manifest_entry=valid_entry)
    assert exc.value.code == "source_version_mismatch"

    # Removed required file
    (mod / "resource_coordinator" / "installation.py").unlink()
    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        source_integrity.verify_source_tree(src, expected_version="1.0.0")
    assert exc.value.code == "source_structure_invalid"


def test_hash_source_tree_rejects_symlinks_and_unicode_collisions(tmp_path):
    mod = _make_minimal_source(tmp_path / "src")
    link = mod / "link.txt"
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symlinks require elevated or Developer Mode privileges on this Windows host")
    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        source_integrity.hash_source_tree(mod)
    assert exc.value.code == "source_reparse_point"


def test_load_source_manifest_rejects_invalid_json_and_schema(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        source_integrity.load_source_manifest(bad)
    assert exc.value.code == "source_manifest_invalid"

    bad.write_text(json.dumps({"schema_version": 99, "sources": []}), encoding="utf-8")
    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        source_integrity.load_source_manifest(bad)
    assert exc.value.code == "source_manifest_invalid"


def test_windows_acceptance_enforces_source_manifest_before_execution(tmp_path):
    src = tmp_path / "src"
    mod = _make_minimal_source(src, version="1.0.0")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "sources": [{
            "source_role": "new_1_0_0",
            "repository": "https://github.com/MaxCarlson/scripts",
            "commit_sha": "c" * 40,
            "package_version": "1.0.0",
            "hash_algorithm": source_integrity.HASH_ALGORITHM,
            "source_tree_sha256": "d" * 64,
        }],
    }), encoding="utf-8")
    run_root = tmp_path / "h4-rc-manifest-fail"
    run_root.mkdir()
    host = {
        "os": {"caption": "Windows 11"},
        "computer": {"manufacturer": "Gigabyte", "model": "X870E", "hypervisor_present": True},
        "queries": {"tasks": "ok", "services": "ok", "processes": "ok"},
        "rc_tasks": [], "rc_services": [], "rc_processes": [],
    }
    rc = windows_acceptance.main([
        "--test-root", str(run_root),
        "--source-root", str(src),
        "--source-manifest", str(manifest_path),
        "--json",
    ], evidence_override=host, is_windows=True)
    assert rc == 3
    preflight = json.loads((run_root / "preflight.json").read_text(encoding="utf-8"))
    assert preflight["source_integrity"]["verified"] is False
    assert preflight["source_integrity"]["reason_code"] == "source_digest_mismatch"
    assert mod.exists()


def test_bundle_builder_dry_run_build_verify_and_corrupt_archive(tmp_path):
    out_dir = tmp_path / "bundle out café"

    # Dry-run defaults to planned without creating output
    assert bundle_builder.main(["-o", str(out_dir), "-n", "83849e3e5b55d1bb7851dd9daaa6ef53bc02a47b", "-j"]) == 0
    assert not out_dir.exists()

    # Actual build and fresh-extraction verification
    assert bundle_builder.main(["-o", str(out_dir), "-n", "83849e3e5b55d1bb7851dd9daaa6ef53bc02a47b", "-a", "-j"]) == 0
    zip_path = out_dir / bundle_builder.ARCHIVE_FILENAME
    assert zip_path.is_file()
    verified = bundle_builder.verify_bundle_archive(zip_path)
    assert verified["verified"] is True

    # Non-empty destination refused
    assert bundle_builder.main(["-o", str(out_dir), "-n", "83849e3e5b55d1bb7851dd9daaa6ef53bc02a47b", "-a", "-j"]) == 2

    # Corrupted archive refused
    corrupt_zip = tmp_path / "corrupt.zip"
    corrupt_zip.write_bytes(b"not-a-zip")
    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        bundle_builder.verify_bundle_archive(corrupt_zip)
    assert exc.value.code == "bundle_archive_corrupt"

    # Tampered source inside archive refused
    tampered_zip = tmp_path / "tampered.zip"
    with zipfile.ZipFile(zip_path, "r") as src_zf, zipfile.ZipFile(tampered_zip, "w") as dst_zf:
        for item in src_zf.infolist():
            data = src_zf.read(item.filename)
            if item.filename.endswith("sources/rc-1.0.0/modules/resource_coordinator/resource_coordinator/installation.py"):
                data += b"\n# tampered\n"
            dst_zf.writestr(item, data)
    with pytest.raises(source_integrity.SourceIntegrityError) as exc:
        bundle_builder.verify_bundle_archive(tampered_zip)
    assert exc.value.code == "source_digest_mismatch"
