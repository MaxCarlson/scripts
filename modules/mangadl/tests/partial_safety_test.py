import json
import sqlite3
from pathlib import Path

import pytest

from mangadl import partial_safety
from mangadl.partial_safety import (
    PARTIAL_MANIFEST_NAME,
    PARTIAL_META_NAME,
    apply_cleanup,
    cleanup_preview,
    initialize_partial,
    plan_cleanup,
)


def _archive(path: Path, entries: tuple[str, ...]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE archive (entry TEXT PRIMARY KEY) WITHOUT ROWID")
        connection.executemany("INSERT INTO archive(entry) VALUES (?)", ((entry,) for entry in entries))
        connection.commit()
    finally:
        connection.close()


def _tracked_partial(tmp_path: Path) -> tuple[Path, Path, Path]:
    destination = tmp_path / "library"
    partial_root = destination / "_partial"
    owner = partial_root / "abc123"
    archive = tmp_path / "archive.sqlite3"
    _archive(archive, ("site-one", "site-two", "unrelated"))
    initialize_partial(
        partial_root,
        owner,
        url="https://example.test/gallery/1",
        backend="gallery-dl",
        archive=archive,
        run_id="run",
        job_id=1,
        attempt_id="attempt",
        worker=1,
    )
    metadata = json.loads((owner / PARTIAL_META_NAME).read_text(encoding="utf-8"))
    metadata["worker_pid"] = -1
    (owner / PARTIAL_META_NAME).write_text(json.dumps(metadata), encoding="utf-8")
    first = owner / "site" / "one" / "001.jpg"
    second = owner / "site" / "two" / "001.jpg"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    records = [
        {"archive_key": "site-one", "path": "site/one/001.jpg"},
        {"archive_key": "site-two", "path": "site/two/001.jpg"},
    ]
    (owner / PARTIAL_MANIFEST_NAME).write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return destination, owner, archive


def _keys(archive: Path) -> set[str]:
    connection = sqlite3.connect(archive)
    try:
        return {row[0] for row in connection.execute("SELECT entry FROM archive")}
    finally:
        connection.close()


def test_selected_subfolder_removes_only_its_exact_archive_entry(tmp_path: Path) -> None:
    destination, owner, archive = _tracked_partial(tmp_path)
    partial_root, targets = plan_cleanup(destination, ["abc123/site/one"])

    preview = cleanup_preview(partial_root, targets)
    result = apply_cleanup(targets)

    assert preview["archive_matches"] == 1
    assert not (owner / "site" / "one").exists()
    assert (owner / "site" / "two" / "001.jpg").exists()
    assert _keys(archive) == {"site-two", "unrelated"}
    assert len(result["archive_backups"]) == 1
    assert Path(result["archive_backups"][0]).is_file()
    remaining = (owner / PARTIAL_MANIFEST_NAME).read_text(encoding="utf-8")
    assert "site-two" in remaining and "site-one" not in remaining


def test_archive_is_updated_before_filesystem_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination, owner, archive = _tracked_partial(tmp_path)
    _, targets = plan_cleanup(destination, ["abc123/site/one"])

    def fail_remove(_path: Path) -> None:
        raise OSError("simulated removal failure")

    monkeypatch.setattr(partial_safety, "_remove_target", fail_remove)
    with pytest.raises(OSError, match="simulated removal failure"):
        apply_cleanup(targets, backup=False)

    assert (owner / "site" / "one" / "001.jpg").exists()
    assert "site-one" not in _keys(archive)


def test_active_and_legacy_partials_require_explicit_safe_handling(tmp_path: Path) -> None:
    destination, owner, _archive_path = _tracked_partial(tmp_path)
    metadata = json.loads((owner / PARTIAL_META_NAME).read_text(encoding="utf-8"))
    metadata["worker_pid"] = partial_safety.os.getpid()
    (owner / PARTIAL_META_NAME).write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="active worker"):
        plan_cleanup(destination, ["abc123"])
    with pytest.raises(ValueError, match="active worker"):
        plan_cleanup(destination, ["abc123"], files_only=True)

    legacy = destination / "_partial" / "legacy"
    legacy.mkdir()
    (legacy / "001.jpg").write_bytes(b"image")
    with pytest.raises(ValueError, match="explicit archive and URL reconciliation"):
        plan_cleanup(destination, ["legacy"])
    _, targets = plan_cleanup(destination, ["legacy"], files_only=True)
    assert targets[0].files_only


def test_cleanup_rejects_escape_and_archive_mismatch(tmp_path: Path) -> None:
    destination, _owner, _archive_path = _tracked_partial(tmp_path)
    with pytest.raises(ValueError, match="escapes partial root"):
        plan_cleanup(destination, [str(tmp_path / "elsewhere")])
    with pytest.raises(ValueError, match="does not match requested archive"):
        plan_cleanup(destination, ["abc123"], archive_override=tmp_path / "wrong.sqlite3")


def test_partial_cannot_switch_archives_after_manifest_has_entries(tmp_path: Path) -> None:
    destination, owner, _archive_path = _tracked_partial(tmp_path)
    with pytest.raises(RuntimeError, match="different archive"):
        initialize_partial(
            destination / "_partial",
            owner,
            url="https://example.test/gallery/1",
            backend="gallery-dl",
            archive=tmp_path / "other.sqlite3",
            run_id="run-two",
            job_id=1,
            attempt_id="attempt-two",
            worker=1,
        )


def test_legacy_owner_can_remove_reconstructed_archive_keys(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    owner = destination / "_partial" / "legacy-owner"
    owner.mkdir(parents=True)
    (owner / "001.jpg").write_bytes(b"image")
    archive = tmp_path / "archive.sqlite3"
    _archive(archive, ("legacy-key", "unrelated"))
    _root, targets = plan_cleanup(destination, [str(owner)], archive_override=archive, legacy_archive_keys={owner.resolve(): {"legacy-key"}})
    result = apply_cleanup(targets, backup=False)
    assert result["removed_archive_entries"] == 1 and _keys(archive) == {"unrelated"} and not owner.exists()


def test_legacy_reconciliation_refuses_nested_target(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    owner = destination / "_partial" / "legacy-owner"
    nested = owner / "nested"
    nested.mkdir(parents=True)
    archive = tmp_path / "archive.sqlite3"
    _archive(archive, ("legacy-key",))
    with pytest.raises(ValueError, match="whole partial owner"):
        plan_cleanup(destination, [str(nested)], archive_override=archive, legacy_archive_keys={owner.resolve(): {"legacy-key"}})


def test_cleanup_refuses_gallery_process_writing_selected_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "library"
    owner = destination / "_partial" / "legacy-owner"
    owner.mkdir(parents=True)
    (owner / "001.jpg").write_bytes(b"image")
    monkeypatch.setattr(partial_safety, "_process_commands", lambda: ((1234, f"python -m gallery_dl --destination {owner}"),))
    with pytest.raises(ValueError, match=r"gallery-dl PID\(s\) 1234"):
        plan_cleanup(destination, [str(owner)], files_only=True)


def test_cleanup_refuses_recent_activity_in_legacy_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "library"
    owner = destination / "_partial" / "legacy-owner"
    owner.mkdir(parents=True)
    for number in range(100):
        (owner / f"{number:03}.jpg").write_bytes(b"image")
    monkeypatch.setattr(partial_safety, "_process_commands", lambda: None)
    with pytest.raises(ValueError, match="activity within the last two minutes"):
        plan_cleanup(destination, [str(owner)], files_only=True)


def test_apply_refuses_target_changed_after_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination, owner, archive = _tracked_partial(tmp_path)
    monkeypatch.setattr(partial_safety, "_process_commands", lambda: ())
    _root, targets = plan_cleanup(destination, ["abc123/site/one"])
    (owner / "site" / "one" / "002.jpg").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="changed after preview"):
        apply_cleanup(targets, backup=False)
    assert _keys(archive) == {"site-one", "site-two", "unrelated"}
