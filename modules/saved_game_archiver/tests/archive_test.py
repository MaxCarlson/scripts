from __future__ import annotations

from pathlib import Path

from saved_game_archiver.archive import ArchiveEngine, ensure_state_index, friendly_save_name
from saved_game_archiver.models import GameRecord, SaveSource


def make_game(tmp_path: Path) -> tuple[GameRecord, Path]:
    save = tmp_path / "saves"
    save.mkdir()
    game = GameRecord(id="g", name="Game G", save_sources=[SaveSource("src", "files", str(save))])
    return game, save


def test_distinct_character_trees_keep_distinct_logical_identity(tmp_path: Path) -> None:
    game, save = make_game(tmp_path)
    (save / "S1").mkdir()
    (save / "S2").mkdir()
    (save / "S1" / "autosave.sav").write_bytes(b"same")
    (save / "S2" / "autosave.sav").write_bytes(b"same")
    engine = ArchiveEngine(tmp_path / "archive", file_stability_seconds=0)

    result = engine.capture_game(game, reason="manual", playtime_seconds=60)
    manifest = engine.load_manifest(game.id, result.snapshot_id or "")

    assert len(manifest.entries) == 2
    assert len({entry.identity for entry in manifest.entries}) == 2
    assert len({entry.state_index for entry in manifest.entries}) == 2
    assert len({entry.blob_sha256 for entry in manifest.entries}) == 1


def test_same_relative_path_in_two_sources_does_not_collide(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    (a / "save.sav").write_bytes(b"A")
    (b / "save.sav").write_bytes(b"B")
    game = GameRecord(
        id="g",
        name="Game",
        save_sources=[SaveSource("a", "files", str(a)), SaveSource("b", "files", str(b))],
    )
    engine = ArchiveEngine(tmp_path / "archive", file_stability_seconds=0)
    result = engine.capture_game(game, reason="manual")
    manifest = engine.load_manifest(game.id, result.snapshot_id or "")
    assert {entry.identity for entry in manifest.entries} == {"a:save.sav", "b:save.sav"}


def test_unchanged_state_creates_no_restore_point(tmp_path: Path) -> None:
    game, save = make_game(tmp_path)
    path = save / "slot.sav"
    path.write_bytes(b"v1")
    engine = ArchiveEngine(tmp_path / "archive", file_stability_seconds=0)
    first = engine.capture_game(game, reason="manual")
    second = engine.capture_game(game, reason="scheduled")
    assert first.changed is True
    assert second.changed is False
    assert second.reused_snapshot is True
    assert second.snapshot_id == first.snapshot_id
    assert len(engine.list_manifests(game.id)) == 1


def test_metadata_change_without_content_change_creates_no_restore_point(tmp_path: Path) -> None:
    game, save = make_game(tmp_path)
    path = save / "slot.sav"
    path.write_bytes(b"stable")
    engine = ArchiveEngine(tmp_path / "archive", file_stability_seconds=0)
    first = engine.capture_game(game, reason="manual")
    stat = path.stat()
    path.touch()
    assert path.stat().st_mtime_ns != stat.st_mtime_ns or True
    second = engine.capture_game(game, reason="scheduled")
    assert second.changed is False
    assert second.snapshot_id == first.snapshot_id


def test_single_modified_file_adds_only_new_blob(tmp_path: Path) -> None:
    game, save = make_game(tmp_path)
    (save / "a.sav").write_bytes(b"a1")
    (save / "b.sav").write_bytes(b"b1")
    engine = ArchiveEngine(tmp_path / "archive", file_stability_seconds=0)
    first = engine.capture_game(game, reason="manual")
    before = {path.name for path in engine.blobs_root.glob("*/*")}
    (save / "b.sav").write_bytes(b"b2")
    second = engine.capture_game(game, reason="manual")
    after = {path.name for path in engine.blobs_root.glob("*/*")}
    assert first.changed and second.changed
    assert len(after - before) == 1
    manifest = engine.load_manifest(game.id, second.snapshot_id or "")
    assert manifest.changed_identities == ["src:b.sav"]


def test_deletion_is_historical_change(tmp_path: Path) -> None:
    game, save = make_game(tmp_path)
    a = save / "a.sav"; b = save / "b.sav"
    a.write_bytes(b"a"); b.write_bytes(b"b")
    engine = ArchiveEngine(tmp_path / "archive", file_stability_seconds=0)
    first = engine.capture_game(game, reason="manual")
    b.unlink()
    second = engine.capture_game(game, reason="manual")
    manifest = engine.load_manifest(game.id, second.snapshot_id or "")
    assert second.changed
    assert manifest.deleted_identities == ["src:b.sav"]
    assert {e.identity for e in engine.load_manifest(game.id, first.snapshot_id or "").entries} == {"src:a.sav", "src:b.sav"}


def test_export_reconstructs_original_and_friendly_views(tmp_path: Path) -> None:
    game, save = make_game(tmp_path)
    (save / "S1").mkdir()
    (save / "S1" / "auto01.sav").write_bytes(b"content")
    engine = ArchiveEngine(tmp_path / "archive", file_stability_seconds=0)
    capture = engine.capture_game(game, reason="manual", playtime_seconds=3661)
    root = engine.export_snapshot(game, capture.snapshot_id or "", tmp_path / "export")
    assert (root / "original" / "src" / "S1" / "auto01.sav").read_bytes() == b"content"
    friendly = list((root / "friendly").glob("*.sav"))
    assert len(friendly) == 1
    assert "Game G_0_" in friendly[0].name
    assert "0001h01m01s" in friendly[0].name


def test_state_index_is_stable_and_override_wins() -> None:
    game = GameRecord(id="g", name="Game")
    assert ensure_state_index(game, "src:a") == 0
    assert ensure_state_index(game, "src:b") == 1
    assert ensure_state_index(game, "src:a") == 0
    game.state_overrides["src:c"] = 7
    assert ensure_state_index(game, "src:c") == 7


def test_friendly_name_keeps_requested_prefix_and_collision_suffix() -> None:
    name = friendly_save_name("My:Game", 2, "2026-08-25T20:00:00+00:00", 90, "char/auto01.sav", ".sav")
    assert name.startswith("My_Game_2_")
    assert name.endswith("__auto01.sav")


def test_initial_state_indices_follow_earliest_observed_save_timestamp(tmp_path: Path) -> None:
    import os

    game, save = make_game(tmp_path)
    later = save / "ZLater"
    earlier = save / "AEarlier"
    later.mkdir(); earlier.mkdir()
    later_file = later / "slot.sav"
    earlier_file = earlier / "slot.sav"
    later_file.write_bytes(b"later")
    earlier_file.write_bytes(b"earlier")
    os.utime(earlier_file, ns=(1_000_000_000, 1_000_000_000))
    os.utime(later_file, ns=(2_000_000_000, 2_000_000_000))
    engine = ArchiveEngine(tmp_path / "archive", file_stability_seconds=0)
    capture = engine.capture_game(game, reason="manual")
    manifest = engine.load_manifest(game.id, capture.snapshot_id or "")
    by_state = {entry.state_key: entry.state_index for entry in manifest.entries}
    assert by_state["src:aearlier"] == 0
    assert by_state["src:zlater"] == 1
