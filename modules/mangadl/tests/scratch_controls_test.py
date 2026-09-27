from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mangadl.scratch_controls import ScratchControls
from mangadl.state import StateStore
from mangadl.cli import main
from mangadl.manager import DownloadManager
from mangadl.partial_safety import (
    PARTIAL_MANIFEST_NAME,
    PARTIAL_META_NAME,
    apply_cleanup,
    initialize_partial,
    plan_cleanup,
)


def _keys(path: Path) -> set[str]:
    with sqlite3.connect(path) as database:
        return {row[0] for row in database.execute("SELECT entry FROM archive")}


def _controls(tmp_path: Path) -> ScratchControls:
    return ScratchControls(
        tmp_path / "library",
        tmp_path / "ssd",
        tmp_path / "library" / "archive.sqlite3",
        tmp_path / "library" / "state.sqlite3",
        tmp_path / "library" / "logs",
    )


def test_control_databases_and_logs_stay_on_scratch_until_sync(tmp_path: Path) -> None:
    controls = _controls(tmp_path)
    controls.canonical_archive.parent.mkdir(parents=True)
    with sqlite3.connect(controls.canonical_archive) as archive:
        archive.execute("CREATE TABLE archive(entry TEXT PRIMARY KEY)")
        archive.execute("INSERT INTO archive VALUES ('old')")
    old_stamp = controls.canonical_archive.stat().st_mtime_ns

    controls.prepare()
    with sqlite3.connect(controls.archive) as archive:
        archive.execute("INSERT INTO archive VALUES ('new')")
    state = StateStore(controls.state_db)
    run_id = state.create_run({"scratch": True})
    state.close()
    run_log = controls.log_dir / run_id
    run_log.mkdir(parents=True)
    (run_log / "manager.log").write_text("scratch log", encoding="utf-8")
    assert _keys(controls.canonical_archive) == {"old"}
    assert controls.canonical_archive.stat().st_mtime_ns == old_stamp
    assert not controls.canonical_state_db.exists()
    assert not (controls.canonical_log_dir / run_id).exists()

    controls.sync(run_id)

    assert _keys(controls.canonical_archive) == {"old", "new"}
    with sqlite3.connect(controls.canonical_state_db) as canonical_state:
        assert canonical_state.execute("SELECT id FROM runs").fetchone()[0] == run_id
    assert (controls.canonical_log_dir / run_id / "manager.log").read_text(
        encoding="utf-8"
    ) == "scratch log"
    assert not json.loads(controls.manifest.read_text(encoding="utf-8"))["pending"]


def test_unsynced_archive_survives_next_prepare(tmp_path: Path) -> None:
    controls = _controls(tmp_path)
    controls.prepare()
    with sqlite3.connect(controls.archive) as archive:
        archive.execute("CREATE TABLE archive(entry TEXT PRIMARY KEY)")
        archive.execute("INSERT INTO archive VALUES ('unsynced')")

    restarted = _controls(tmp_path)
    restarted.prepare()
    assert _keys(restarted.archive) == {"unsynced"}


def test_failed_run_defers_canonical_archive_but_syncs_state(tmp_path: Path) -> None:
    controls = _controls(tmp_path)
    controls.prepare()
    with sqlite3.connect(controls.archive) as archive:
        archive.execute("CREATE TABLE archive(entry TEXT PRIMARY KEY)")
        archive.execute("INSERT INTO archive VALUES ('partial-only')")
    state = StateStore(controls.state_db)
    run_id = state.create_run({"scratch": True})
    state.close()

    controls.sync(run_id, archive_safe=False)

    assert not controls.canonical_archive.exists()
    assert controls.canonical_state_db.exists()
    assert json.loads(controls.manifest.read_text(encoding="utf-8"))["pending"]
    restarted = _controls(tmp_path)
    restarted.prepare()
    assert _keys(restarted.archive) == {"partial-only"}


def test_external_canonical_change_refuses_sync_and_keeps_scratch(
    tmp_path: Path,
) -> None:
    controls = _controls(tmp_path)
    controls.canonical_archive.parent.mkdir(parents=True)
    with sqlite3.connect(controls.canonical_archive) as archive:
        archive.execute("CREATE TABLE archive(entry TEXT PRIMARY KEY)")
    controls.prepare()
    with sqlite3.connect(controls.archive) as archive:
        archive.execute("INSERT INTO archive VALUES ('staged')")
    with sqlite3.connect(controls.canonical_archive) as archive:
        archive.execute("INSERT INTO archive VALUES ('external')")

    with pytest.raises(RuntimeError, match="changed during"):
        controls.sync("run")

    assert _keys(controls.archive) == {"staged"}
    assert _keys(controls.canonical_archive) == {"external"}


def test_cli_uses_scratch_controls_and_syncs_after_manager_returns(
    tmp_path: Path, monkeypatch
) -> None:
    destination = tmp_path / "library"
    scratch = tmp_path / "ssd"
    observed = {}

    def fake_run(manager: DownloadManager) -> int:
        observed["archive"] = manager.options.archive
        observed["state_db"] = manager.options.state_db
        observed["log_dir"] = manager.options.log_dir
        assert not (destination / ".mangadl" / "state.sqlite3").exists()
        with sqlite3.connect(manager.options.archive) as archive:
            archive.execute("CREATE TABLE archive(entry TEXT PRIMARY KEY)")
            archive.execute("INSERT INTO archive VALUES ('new')")
        return 0

    monkeypatch.setattr(DownloadManager, "run", fake_run)
    assert (
        main(
            [
                "run",
                "-u",
                "https://manga18fx.com/manga/example/",
                "-d",
                str(destination),
                "-S",
                str(scratch),
                "-X",
            ]
        )
        == 0
    )
    assert str(observed["archive"]).startswith(str(scratch))
    assert str(observed["state_db"]).startswith(str(scratch))
    assert str(observed["log_dir"]).startswith(str(scratch))
    assert _keys(destination / ".mangadl" / "archive.sqlite3") == {"new"}
    with sqlite3.connect(destination / ".mangadl" / "state.sqlite3") as state:
        assert state.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_archive_aware_cleanup_keeps_pending_scratch_resumable(tmp_path: Path) -> None:
    controls = _controls(tmp_path)
    controls.canonical_archive.parent.mkdir(parents=True)
    with sqlite3.connect(controls.canonical_archive) as archive:
        archive.execute("CREATE TABLE archive(entry TEXT PRIMARY KEY)")
        archive.execute("INSERT INTO archive VALUES ('partial-key')")
    controls.prepare()
    root = controls.root.parent / "_partial"
    owner = root / "owner"
    initialize_partial(
        root,
        owner,
        url="https://example.test/gallery/1",
        backend="gallery-dl",
        archive=controls.archive,
        archive_mirror=controls.canonical_archive,
        run_id="run",
        job_id=1,
        attempt_id="attempt",
        worker=1,
    )
    metadata = json.loads((owner / PARTIAL_META_NAME).read_text(encoding="utf-8"))
    metadata["worker_pid"] = -1
    (owner / PARTIAL_META_NAME).write_text(json.dumps(metadata), encoding="utf-8")
    image = owner / "Series" / "001.jpg"
    image.parent.mkdir()
    image.write_bytes(b"image")
    (owner / PARTIAL_MANIFEST_NAME).write_text(
        json.dumps({"archive_key": "partial-key", "path": "Series/001.jpg"}) + "\n",
        encoding="utf-8",
    )
    _, targets = plan_cleanup(
        tmp_path / "library",
        ["owner"],
        partial_root_override=root,
    )
    apply_cleanup(targets, backup=False)

    controls.prepare()
    assert not _keys(controls.archive)
    assert not _keys(controls.canonical_archive)
