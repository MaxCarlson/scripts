from concurrent.futures import ThreadPoolExecutor
import json

import pytest


def resolve(target, parent=None, **kwargs):
    from compresser import workspace

    return workspace.resolve_workspace(target, parent, owner="mangadl-pages", **kwargs)


def test_directory_I_names_target_workspace(tmp_path):
    target = tmp_path / "book"
    target.mkdir()
    ws = resolve(target, tmp_path / "state")
    assert ws.root == tmp_path / "state" / ".mangadl" / "book"
    assert ws.inventory_file.name == "inventory.sqlite3"
    assert ws.trial_cache_file.name == "trials.sqlite3"
    assert ws.plans_dir == ws.root / "plans"
    assert not ws.root.exists()


def test_default_is_external_sibling(tmp_path):
    target = tmp_path / "book"
    target.mkdir()
    assert resolve(target).root == tmp_path / ".mangadl" / "book"


def test_requested_windows_layout_without_accessing_production_drive(tmp_path):
    from pathlib import PureWindowsPath

    target = tmp_path / "hent1imageperpage"
    target.mkdir()
    ws = resolve(target, tmp_path)
    actual = PureWindowsPath("B:/Hent") / ws.root.relative_to(tmp_path)
    assert actual == PureWindowsPath("B:/Hent/.mangadl/hent1imageperpage")
    assert not ws.root.exists()


def test_standalone_file_target_uses_full_filename(tmp_path):
    from compresser.workspace import resolve_workspace

    target = tmp_path / "page.jpg"
    target.touch()
    assert (
        resolve_workspace(target, None, owner="compresser").root
        == tmp_path / ".compresser" / "page.jpg"
    )


@pytest.mark.parametrize("existing", [False, True])
def test_file_valued_workspace_rejected_without_artifacts(tmp_path, existing):
    from compresser.workspace import configure_workspace
    from types import SimpleNamespace

    target = tmp_path / "book"
    target.mkdir()
    legacy = tmp_path / "old.sqlite3"
    if existing:
        legacy.write_bytes(b"preserved")
    args = SimpleNamespace(inventory_file=legacy, cache_file=None)
    with pytest.raises(ValueError, match="parent directory"):
        configure_workspace(args, target, owner="compresser")
    assert not (tmp_path / ".compresser").exists()
    if existing:
        assert legacy.read_bytes() == b"preserved"


def test_nonempty_unowned_or_foreign_manifest_rejected(tmp_path):
    from compresser.workspace import initialize_workspace

    target = tmp_path / "book"
    target.mkdir()
    ws = resolve(target)
    ws.root.mkdir(parents=True)
    (ws.root / "unrelated").touch()
    with pytest.raises(ValueError, match="unowned"):
        initialize_workspace(ws)
    (ws.root / "unrelated").unlink()
    initialize_workspace(ws)
    other = tmp_path / "other" / "book"
    other.mkdir(parents=True)
    with pytest.raises(ValueError, match="different"):
        initialize_workspace(resolve(other, tmp_path))


def test_linked_inside_source_and_database_alias_rejected(tmp_path):
    target = tmp_path / "book"
    target.mkdir()
    with pytest.raises(ValueError, match="outside"):
        resolve(target, target)


def test_shared_container_and_old_sibling_untouched(tmp_path):
    from compresser.workspace import initialize_workspace

    target = tmp_path / "book"
    target.mkdir()
    shared = tmp_path / ".mangadl"
    shared.mkdir()
    control = shared / "downloader.json"
    control.write_bytes(b"unrelated downloader controls")
    old = tmp_path / "book-mangadl"
    old.mkdir()
    (old / "workspace.json").write_bytes(b"not read or migrated")
    ws = resolve(target)
    initialize_workspace(ws)
    assert control.read_bytes() == b"unrelated downloader controls"
    assert (old / "workspace.json").read_bytes() == b"not read or migrated"
    assert not (shared / "workspace.json").exists()


def test_source_inside_shared_container_rejected(tmp_path):
    target = tmp_path / ".mangadl" / "book"
    target.mkdir(parents=True)
    with pytest.raises(ValueError, match="artifact container"):
        resolve(target, tmp_path)


def test_hardlinked_workspace_databases_rejected(tmp_path):
    from compresser.workspace import initialize_workspace

    target = tmp_path / "book"
    target.mkdir()
    ws = resolve(target)
    initialize_workspace(ws)
    ws.inventory_file.touch()
    ws.trial_cache_file.hardlink_to(ws.inventory_file)
    with pytest.raises(ValueError, match="hardlink|different files"):
        initialize_workspace(ws)


def test_external_artifact_container_does_not_claim_source_library(tmp_path):
    from compresser.transactions import managed_library_root
    from compresser.workspace import initialize_workspace

    target = tmp_path / "book"
    target.mkdir()
    initialize_workspace(resolve(target))
    assert managed_library_root(target) is None
    # Actual downloader controls still establish shared library ownership.
    (tmp_path / ".mangadl" / "state.sqlite3").touch()
    assert managed_library_root(target) == tmp_path


def test_empty_or_unrecognized_controls_retain_library_ownership(tmp_path):
    from compresser.transactions import managed_library_root

    target = tmp_path / "book"
    target.mkdir()
    controls = tmp_path / ".mangadl"
    controls.mkdir()
    assert managed_library_root(target) == tmp_path
    (controls / "unknown").mkdir()
    assert managed_library_root(target) == tmp_path


@pytest.mark.parametrize("linked_part", ["container", "workspace", "manifest"])
def test_reparse_artifacts_cannot_relax_library_ownership(
    tmp_path, monkeypatch, linked_part
):
    import stat
    from pathlib import Path
    from types import SimpleNamespace

    from compresser.transactions import managed_library_root
    from compresser.workspace import initialize_workspace

    target = tmp_path / "book"
    target.mkdir()
    ws = resolve(target)
    initialize_workspace(ws)
    linked_path = {
        "container": ws.root.parent,
        "workspace": ws.root,
        "manifest": ws.root / "workspace.json",
    }[linked_part]
    real_lstat = Path.lstat

    def reparse(path, *args, **kwargs):
        if path == linked_path:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=1024)
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", reparse)
    assert managed_library_root(target) == tmp_path


@pytest.mark.parametrize(
    "damage", ["wrong-inventory", "hardlinked-manifest", "changed-container"]
)
def test_unproven_artifacts_retain_conservative_library_ownership(
    tmp_path, monkeypatch, damage
):
    from pathlib import Path

    from compresser.transactions import managed_library_root
    from compresser.workspace import initialize_workspace

    target = tmp_path / "book"
    target.mkdir()
    ws = resolve(target)
    initialize_workspace(ws)
    manifest = ws.root / "workspace.json"
    if damage == "wrong-inventory":
        value = json.loads(manifest.read_text())
        value["inventory"] = str(tmp_path / "unrelated.sqlite3")
        manifest.write_text(json.dumps(value))
    elif damage == "hardlinked-manifest":
        (tmp_path / "manifest-alias.json").hardlink_to(manifest)
    else:
        read_text = Path.read_text

        def concurrent_downloader_control(path, *args, **kwargs):
            result = read_text(path, *args, **kwargs)
            if path == manifest:
                (ws.root.parent / "state.sqlite3").touch()
            return result

        monkeypatch.setattr(Path, "read_text", concurrent_downloader_control)
    assert managed_library_root(target) == tmp_path


def test_two_concurrent_initializers_revalidate_owner(tmp_path):
    from compresser.workspace import initialize_workspace

    target = tmp_path / "book"
    target.mkdir()
    ws = resolve(target)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(initialize_workspace, ws) for _ in range(2)]
        for future in futures:
            future.result()
    assert json.loads((ws.root / "workspace.json").read_text())["target"] == str(target)


def test_cache_override_cannot_alias_inventory_or_reserved_report(tmp_path):
    from types import SimpleNamespace

    from compresser.workspace import configure_workspace, initialize_workspace

    target = tmp_path / "book"
    target.mkdir()
    ws = resolve(target)
    initialize_workspace(ws)
    ws.inventory_file.touch()
    hardlink_cache = tmp_path / "cache-alias.sqlite3"
    hardlink_cache.hardlink_to(ws.inventory_file)
    with pytest.raises(ValueError, match="different files"):
        configure_workspace(
            SimpleNamespace(
                inventory_file=None, cache_file=hardlink_cache, preview_dir=None
            ),
            target,
            owner="mangadl-pages",
        )

    latest = ws.reports_dir / "latest.md"
    latest.parent.mkdir(exist_ok=True)
    latest.write_text("existing report", encoding="utf-8")
    with pytest.raises(ValueError, match="reserved workspace artifact"):
        configure_workspace(
            SimpleNamespace(inventory_file=None, cache_file=latest, preview_dir=None),
            target,
            owner="mangadl-pages",
        )
