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
    assert ws.root == tmp_path / "state" / "book-mangadl"
    assert ws.inventory_file.name == "book-mangadl-inventory.sqlite3"
    assert ws.trial_cache_file.name == "book-mangadl-trials.sqlite3"
    assert not ws.root.exists()


def test_default_is_external_sibling(tmp_path):
    target = tmp_path / "book"
    target.mkdir()
    assert resolve(target).root == tmp_path / "book-mangadl"


def test_standalone_file_target_uses_stem(tmp_path):
    from compresser.workspace import resolve_workspace

    target = tmp_path / "page.jpg"
    target.touch()
    assert resolve_workspace(target, None, owner="compresser").root.name == "page-compresser"


def test_legacy_sqlite_path_preserved_and_warned(tmp_path, capsys):
    from compresser.workspace import configure_workspace
    from compresser.cli import build_parser

    target = tmp_path / "book"
    target.mkdir()
    legacy = tmp_path / "old.sqlite3"
    args = build_parser().parse_args(["-i", str(target), "-I", str(legacy)])
    ws = configure_workspace(args, target, owner="compresser")
    assert ws.inventory_file == legacy
    assert ws.trial_cache_file == tmp_path / "old.trials.sqlite3"
    assert "deprecated" in capsys.readouterr().err


def test_nonempty_unowned_or_foreign_manifest_rejected(tmp_path):
    from compresser.workspace import initialize_workspace

    target = tmp_path / "book"
    target.mkdir()
    ws = resolve(target)
    ws.root.mkdir()
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
    # A legacy filename cannot alias the source.
    with pytest.raises(ValueError):
        resolve(target, tmp_path, legacy_inventory=target)


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
            SimpleNamespace(inventory_file=None, cache_file=hardlink_cache, preview_dir=None),
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
