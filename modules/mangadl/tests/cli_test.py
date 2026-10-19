import argparse
import builtins
import json
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from cross_platform import StorageMedia, StorageMediaKind

from mangadl.backends import GalleryDlBackend
from mangadl.cli import build_parser, main
from mangadl.cli_core import _interactive_auth_site, _prompt_auth_target
from mangadl.gallery_auth import ProfileStore
from mangadl.gallery_auth import TargetStore
from mangadl.repair_pages import PageRepairPlan


def test_all_public_options_have_short_and_long_forms() -> None:
    parser = build_parser()
    parsers = [parser]
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    parsers.extend(subparsers.choices.values())
    for current in parsers:
        for action in current._actions:
            if not action.option_strings or action.dest == "help" or action.help == argparse.SUPPRESS:
                continue
            assert any(option.startswith("--") for option in action.option_strings), action.dest
            assert any(
                option.startswith("-") and not option.startswith("--") for option in action.option_strings
            ), action.dest


def test_run_parser_defaults_to_safe_worker_ceiling_and_stagger(tmp_path) -> None:
    args = build_parser().parse_args(
        [
            "run",
            "-u",
            "https://manga18fx.com/manga/example/",
            "-d",
            str(tmp_path / "out"),
        ]
    )

    assert args.workers == 2
    assert args.max_workers is None
    assert args.worker_start_delay == 2.0
    assert args.image_workers == 4
    assert args.run_id is None
    assert args.archive is None
    assert args.state_db is None
    assert args.log_dir is None


def test_dry_run_routes_without_writing(tmp_path, capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MANGADL_MAX_OUTER_WORKERS", raising=False)
    monkeypatch.delenv("MANGADL_MANGA18FX_IMAGE_WORKERS", raising=False)
    monkeypatch.setattr(
        GalleryDlBackend,
        "score",
        lambda self, url: 100 if url == "https://nhentai.net/g/123/" else 0,
    )

    result = main(
        [
            "run",
            "config",
            "-u",
            "123",
            "-d",
            str(tmp_path / "out"),
            "-a",
            str(tmp_path / "archive.db"),
            "-n",
            "-J",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["mode"] == "normal"
    assert "gallery-dl" in payload["routes"].values()
    assert not (tmp_path / "archive.db").exists()


def test_broad_collection_requires_explicit_opt_in(tmp_path, capsys) -> None:
    url = "https://www.simply-hentai.com/series/8-original-work"

    blocked = main(["run", "-u", url, "-d", str(tmp_path / "blocked"), "-n", "-J"])
    blocked_payload = json.loads(capsys.readouterr().out)
    allowed = main(
        [
            "run", "-u", url, "-d", str(tmp_path / "allowed"),
            "--allow-collection", "-n", "-J",
        ]
    )
    allowed_payload = json.loads(capsys.readouterr().out)

    assert blocked == 1
    assert blocked_payload["accepted"] == 0
    assert "requires --allow-collection" in blocked_payload["unsupported"][0]["reason"]
    assert allowed == 0
    assert allowed_payload["accepted"] == 1


def test_broad_collection_aborts_real_run_before_other_urls_start(
    tmp_path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = False

    def fake_run(_manager):
        nonlocal started
        started = True
        return 0

    monkeypatch.setattr("mangadl.cli_core.DownloadManager.run", fake_run)
    with pytest.raises(SystemExit, match="2"):
        main(
            [
                "run",
                "-u", "https://www.simply-hentai.com/series/8-original-work",
                "-u", "https://manga18fx.com/manga/example/",
                "-d", str(tmp_path / "library"),
                "-N",
            ]
        )

    assert not started
    assert "refusing broad collection" in capsys.readouterr().err


def test_dry_run_is_human_readable_and_uses_destination_local_defaults(
    tmp_path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GalleryDlBackend, "score", lambda self, url: 100)
    destination = tmp_path / "library"

    result = main(
        [
            "run",
            "config",
            "-u",
            "https://example.invalid/gallery/1",
            "-d",
            str(destination),
            "-n",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "mangadl dry run" in output
    assert "Accepted: 1 unique URL(s)" in output
    assert f"Control directory: {destination / '.mangadl'}" in output
    assert not (destination / ".mangadl").exists()


def test_real_run_constructs_destination_local_control_paths_without_shell_variables(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GalleryDlBackend, "score", lambda self, url: 100)
    captured = {}

    def fake_run(manager):
        captured["options"] = manager.options
        return 0

    monkeypatch.setattr("mangadl.cli_core.DownloadManager.run", fake_run)
    destination = tmp_path / "library"

    result = main(
        [
            "run",
            "-u",
            "https://example.invalid/gallery/1",
            "-d",
            str(destination),
            "-N",
        ]
    )

    options = captured["options"]
    assert result == 0
    assert options.archive == destination / ".mangadl" / "archive.sqlite3"
    assert options.state_db == destination / ".mangadl" / "state.sqlite3"
    assert options.log_dir == destination / ".mangadl" / "logs"


def test_partials_clean_is_dry_run_first_and_requires_files_only_for_legacy(
    tmp_path, capsys
) -> None:
    destination = tmp_path / "library"
    legacy = destination / "_partial" / "legacy"
    legacy.mkdir(parents=True)
    (legacy / "001.jpg").write_bytes(b"image")

    preview_result = main(
        ["partials", "clean", "-d", str(destination), "-t", "legacy", "-F", "-j"]
    )
    preview = json.loads(capsys.readouterr().out)
    apply_result = main(
        [
            "partials", "clean", "-d", str(destination), "-t", "legacy",
            "-F", "-f", "-j",
        ]
    )
    applied = json.loads(capsys.readouterr().out)

    assert preview_result == 0
    assert preview["status"] == "dry-run"
    assert preview["files_only"]
    assert apply_result == 0
    assert applied["status"] == "applied"
    assert not legacy.exists()


def test_interactive_legacy_cleanup_reconstructs_and_removes_archive_keys(
    tmp_path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "library"
    owner = destination / "_partial" / "legacy-owner"
    owner.mkdir(parents=True)
    (owner / "001.jpg").write_bytes(b"image")
    archive = tmp_path / "archive.sqlite3"
    connection = sqlite3.connect(archive)
    try:
        connection.execute("CREATE TABLE archive(entry TEXT PRIMARY KEY) WITHOUT ROWID")
        connection.executemany(
            "INSERT INTO archive(entry) VALUES (?)",
            (("legacy-key",), ("unrelated",)),
        )
        connection.commit()
    finally:
        connection.close()

    url = "https://example.test/gallery/one"
    monkeypatch.setattr(
        "mangadl.cli_core.select_partial_owners", lambda *_args, **_kwargs: [owner]
    )
    monkeypatch.setattr(
        "mangadl.cli_core.resolve_owner_urls", lambda *_args, **_kwargs: {owner.resolve(): url}
    )
    monkeypatch.setattr(
        "mangadl.cli_core.reconstruct_archive_keys", lambda *_args, **_kwargs: {"legacy-key"}
    )

    result = main(
        [
            "partials", "clean", "-d", str(destination), "-a", str(archive),
            "-f", "-y", "-j",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    connection = sqlite3.connect(archive)
    try:
        keys = {row[0] for row in connection.execute("SELECT entry FROM archive")}
    finally:
        connection.close()

    assert result == 0
    assert payload["status"] == "applied"
    assert payload["removed_archive_entries"] == 1
    assert keys == {"unrelated"}
    assert not owner.exists()


def test_benchmark_dry_run_reports_explicit_bounds(
    tmp_path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MANGADL_MAX_OUTER_WORKERS", raising=False)
    monkeypatch.delenv("MANGADL_MANGA18FX_IMAGE_WORKERS", raising=False)
    result = main(
        [
            "run",
            "benchmark",
            "config",
            "-u",
            "https://manga18fx.com/manga/one/",
            "-u",
            "https://manga18fx.com/manga/two/",
            "-u",
            "https://manga18fx.com/manga/three/",
            "-u",
            "https://manga18fx.com/manga/four/",
            "-d",
            str(tmp_path / "out"),
            "-a",
            str(tmp_path / "archive.db"),
            "-p",
            "2",
            "-m",
            "4",
            "-P",
            "2",
            "-M",
            "5",
            "-U",
            "1.5",
            "-n",
            "-J",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    optimization = payload["optimization"]
    assert result == 0
    assert payload["mode"] == "benchmark"
    assert payload["max_workers"] == 4
    assert payload["worker_start_delay"] == 1.5
    assert optimization["worker_bounds"] == {"minimum": 2, "maximum": 4}
    assert optimization["image_worker_bounds"] == {"minimum": 2, "maximum": 5}
    assert optimization["state_count"] > 0


def test_benchmark_worker_target_cannot_exceed_slow_storage_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("mangadl.cli_core.storage_media_for_path", lambda path: StorageMedia(StorageMediaKind.ROTATIONAL, str(path), "mocked slow storage"))
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "run",
                "benchmark",
                "-u",
                "https://manga18fx.com/manga/example/",
                "-d",
                str(tmp_path / "out"),
                "-a",
                str(tmp_path / "archive.db"),
                "-m",
                "5",
                "-n",
            ]
        )

    assert exc_info.value.code == 2


def test_legacy_auto_tune_aliases_normalize_to_benchmark_preview(tmp_path, capsys) -> None:
    result = main(
        [
            "run",
            "-u",
            "https://manga18fx.com/manga/one/",
            "-u",
            "https://manga18fx.com/manga/two/",
            "-d",
            str(tmp_path / "out"),
            "-a",
            str(tmp_path / "archive.db"),
            "-T",
            "-W",
            "1:2",
            "-Y",
            "2:4",
            "-n",
            "-J",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["mode"] == "benchmark"
    assert payload["optimization"]["worker_bounds"] == {"minimum": 1, "maximum": 2}
    assert payload["optimization"]["image_worker_bounds"] == {"minimum": 2, "maximum": 4}


def test_explicit_max_workers_override_allows_experimental_bound(
    tmp_path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MANGADL_MAX_OUTER_WORKERS", raising=False)
    monkeypatch.delenv("MANGADL_MANGA18FX_IMAGE_WORKERS", raising=False)
    monkeypatch.setattr("mangadl.cli_core.storage_media_for_path", lambda path: StorageMedia(StorageMediaKind.SOLID_STATE, str(path), "mocked SSD"))
    monkeypatch.setattr("mangadl.cli_core.os.cpu_count", lambda: 16)
    result = main(
        [
            "run",
            "config",
            "-u",
            "https://manga18fx.com/manga/example/",
            "-d",
            str(tmp_path / "out"),
            "-a",
            str(tmp_path / "archive.db"),
            "-m",
            "5",
            "-w",
            "5",
            "-n",
            "-J",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["requested_workers"] == 5
    assert payload["max_workers"] == 5


def test_scratch_defaults_to_cpu_budget_when_scratch_is_ssd(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("mangadl.cli_core.storage_media_for_path", lambda path: StorageMedia(StorageMediaKind.SOLID_STATE, str(path), "mocked SSD"))
    monkeypatch.setattr("mangadl.cli_core.os.cpu_count", lambda: 16)
    result = main(
        [
            "run",
            "config",
            "-u",
            "https://manga18fx.com/manga/example/",
            "-d",
            str(tmp_path / "out"),
            "--scratch",
            str(tmp_path / "scratch"),
            "-n",
            "-J",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["max_workers"] == 15
    assert payload["storage_media"] == "scratch"
    assert payload["destination_storage_media"] == "solid_state"
    assert payload["scratch_storage_media"] == "solid_state"


def test_scratch_does_not_remove_ceiling_unless_either_path_is_ssd(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("mangadl.cli_core.storage_media_for_path", lambda path: StorageMedia(StorageMediaKind.ROTATIONAL, str(path), "mocked HDD"))

    result = main(
        [
            "run", "config", "-u", "https://manga18fx.com/manga/example/",
            "-d", str(tmp_path / "out"), "--scratch", str(tmp_path / "scratch"), "-n", "-J",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["max_workers"] == 4
    assert payload["destination_storage_media"] == "rotational"
    assert payload["scratch_storage_media"] == "rotational"


def test_ssd_destination_removes_ceiling_even_with_rotational_scratch(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "mangadl.cli_core.storage_media_for_path",
        lambda path: StorageMedia(
            StorageMediaKind.ROTATIONAL if "scratch" in str(path) else StorageMediaKind.SOLID_STATE,
            str(path),
            "mocked media",
        ),
    )
    monkeypatch.setattr("mangadl.cli_core.os.cpu_count", lambda: 16)

    result = main(
        [
            "run", "config", "-u", "https://manga18fx.com/manga/example/",
            "-d", str(tmp_path / "out"), "--scratch", str(tmp_path / "scratch"), "-n", "-J",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["max_workers"] == 15
    assert payload["destination_storage_media"] == "solid_state"
    assert payload["scratch_storage_media"] == "rotational"


@pytest.mark.parametrize(
    ("kind", "expected"),
    [(StorageMediaKind.SOLID_STATE, 15), (StorageMediaKind.ROTATIONAL, 4), (StorageMediaKind.UNKNOWN, 4)],
)
def test_destination_media_selects_default_worker_ceiling(
    tmp_path, capsys, monkeypatch: pytest.MonkeyPatch, kind, expected
) -> None:
    monkeypatch.setattr("mangadl.cli_core.os.cpu_count", lambda: 16)
    monkeypatch.setattr(
        "mangadl.cli_core.storage_media_for_path",
        lambda path: StorageMedia(kind, str(path), "mocked storage"),
    )

    result = main(
        [
            "run",
            "config",
            "-u",
            "https://manga18fx.com/manga/example/",
            "-d",
            str(tmp_path / "out"),
            "-n",
            "-J",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["max_workers"] == expected
    assert payload["storage_media"] == kind.value


def test_kavita_name_assignment_previews_then_applies_exact_series(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("KAVITA_API_KEY", "test-key")
    fake = _FakeKavitaClient([
        {"id": 7, "name": "The Example", "folderPath": "/library/The Example"},
        {"id": 8, "name": "Other", "folderPath": "/library/Other"},
    ])
    monkeypatch.setattr("mangadl.cli_core.KavitaClient", lambda _config: fake)

    assert main(["kavita", "assign-name", "-n", "the example", "-c", "Favorites", "-Z", "http://kavita", "-j"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["mode"] == "preview"
    assert [row["id"] for row in preview["matches"]] == [7]
    assert fake.add_calls == []

    assert main(["kavita", "assign-name", "-n", "the example", "-c", "Favorites", "-Z", "http://kavita", "-f", "-j"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["mode"] == "apply"
    assert fake.add_calls == [("Favorites", [7], True)]


def test_kavita_pattern_requires_exact_preview_token_before_apply(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("KAVITA_API_KEY", "test-key")
    fake = _FakeKavitaClient([
        {"id": 7, "name": "blahblah alpha", "folderPath": "/library/a"},
        {"id": 8, "name": "blahblah beta", "folderPath": "/library/b"},
        {"id": 9, "name": "other", "folderPath": "/library/c"},
    ])
    monkeypatch.setattr("mangadl.cli_core.KavitaClient", lambda _config: fake)
    argv = ["kavita", "assign-pattern", "-p", r"blahblah.*", "-c", "Group", "-Z", "http://kavita", "-j"]

    assert main(argv) == 0
    preview = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in preview["matches"]] == [7, 8]
    assert fake.add_calls == []

    with pytest.raises(SystemExit) as exc_info:
        main([*argv, "-f"])
    assert exc_info.value.code == 2
    assert fake.add_calls == []

    assert main([*argv, "-f", "-C", preview["match_token"]]) == 0
    assert fake.add_calls == [("Group", [7, 8], True)]


def test_kavita_file_assignment_resolves_shared_url_folder_identity(tmp_path, capsys, monkeypatch) -> None:
    from PIL import Image

    monkeypatch.setenv("KAVITA_API_KEY", "test-key")
    folder = tmp_path / "library" / "Series"
    folder.mkdir(parents=True)
    Image.new("RGB", (1, 1)).save(folder / "001.jpg")
    (folder / "info.json").write_text(json.dumps({"url": "https://example.test/series"}), encoding="utf-8")
    urls = tmp_path / "urls.txt"
    urls.write_text("https://example.test/series\n", encoding="utf-8")
    fake = _FakeKavitaClient([{"id": 11, "name": "Series", "folderPath": str(folder)}])
    monkeypatch.setattr("mangadl.cli_core.KavitaClient", lambda _config: fake)

    assert main([
        "kavita", "assign-file", "-i", str(urls), "-d", str(folder.parent),
        "-c", "Archive", "-Z", "http://kavita", "-j",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["matches"][0]["source_urls"] == ["https://example.test/series"]
    assert payload["matches"][0]["id"] == 11
    assert payload["index_backfill"]["created"] == 1
    assert (folder / ".mangadl-source.json").is_file()
    assert fake.add_calls == []


def test_kavita_pattern_rejects_unsafe_regex_constructs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KAVITA_API_KEY", "test-key")
    monkeypatch.setattr("mangadl.cli_core.KavitaClient", lambda _config: _FakeKavitaClient([]))
    with pytest.raises(SystemExit) as exc_info:
        main(["kavita", "assign-pattern", "-p", r"(a+)+$", "-c", "Group", "-Z", "http://kavita"])
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        main(["kavita", "assign-pattern", "-p", r"(a|aa)+$", "-c", "Group", "-Z", "http://kavita"])
    assert exc_info.value.code == 2


class _FakeKavitaClient:
    def __init__(self, series):
        self.series = series
        self.add_calls = []

    def list_series(self):
        return self.series

    def add_series_to_collection(self, name, ids, *, apply=False):
        self.add_calls.append((name, ids, apply))
        return {"action": "add_to_collection", "collection": name, "series_ids": ids, "applied": apply}


def test_repair_loose_defaults_to_dry_run_and_supports_explicit_mode(tmp_path, capsys) -> None:
    assert main(["repair-loose", "-d", str(tmp_path), "-N"]) == 0
    assert "DRY-RUN: 0 files across 0 galleries" in capsys.readouterr().out

    args = build_parser().parse_args(["repair-loose", "-d", str(tmp_path), "-n"])
    assert args.dry_run


def test_repair_pages_fails_closed_before_requests_for_custom_gallery_config(tmp_path, monkeypatch, capsys) -> None:
    def unexpected_audit(*_args, **_kwargs):
        raise AssertionError("custom config must be rejected before source requests")

    monkeypatch.setattr("mangadl.cli_core.audit_destinations", unexpected_audit)
    with pytest.raises(SystemExit) as exc_info:
        main([
            "repair-pages", "-u", "https://nhentai.net/g/123/", "-d", str(tmp_path),
            "-g", str(tmp_path / "gallery-dl.conf"),
        ])
    assert exc_info.value.code == 2
    assert "archive table and key overrides cannot be proven" in capsys.readouterr().err


def test_batch_repair_report_builds_and_prints_plan_without_required_plan_file(
    tmp_path, capsys, monkeypatch
) -> None:
    destination = tmp_path / "library"
    folder = destination / "nhentai-123 - Example"
    folder.mkdir(parents=True)
    corrupt = folder / "2.jpg"
    corrupt.write_bytes(b"bad")
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({
        "schema": 1,
        "kind": "mangadl-audit-report",
        "mode": "url-file",
        "destinations": [str(destination)],
        "items": [{
            "canonical_url": "https://nhentai.net/g/123/",
            "status": "matched",
            "folders": [str(folder)],
            "completeness": "incomplete",
            "image_integrity": "issues",
        }],
    }), encoding="utf-8")
    fake = PageRepairPlan(
        url="https://nhentai.net/g/123/",
        folder=folder,
        expected_count=2,
        damaged_pages=(2,),
        page_keys={1: "key1", 2: "key2"},
        corrupt_files=(corrupt,),
        archive_rows_found=("key2",),
        archive_table="archive",
    )
    monkeypatch.setattr("mangadl.cli_core._fresh_page_plan", lambda *_args, **_kwargs: (
        fake, destination / ".mangadl" / "archive.sqlite3"
    ))

    assert main(["repair", "-r", str(report)]) == 0

    output = capsys.readouterr().out
    assert "Repair plan" in output
    assert "Repair 1 page(s)" in output
    assert "Confirmation token:" in output


def test_batch_repair_missing_gallery_uses_single_report_destination(tmp_path, capsys) -> None:
    destination = tmp_path / "library"
    destination.mkdir()
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({
        "schema": 1,
        "kind": "mangadl-audit-report",
        "mode": "url-file",
        "destinations": [str(destination)],
        "items": [{
            "canonical_url": "https://nhentai.net/g/123/",
            "status": "missing",
            "folders": [],
            "completeness": "unknown",
            "image_integrity": "unverified",
        }],
    }), encoding="utf-8")

    assert main(["repair", "-r", str(report), "-j"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["action_count"] == 1
    assert payload["actions"][0]["kind"] == "download_gallery"
    assert payload["actions"][0]["destination"] == str(destination)


def test_batch_repair_rejects_stale_missing_gallery_after_folder_appears(tmp_path, capsys) -> None:
    destination = tmp_path / "library"
    (destination / "nhentai-123 - Example").mkdir(parents=True)
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({
        "schema": 1,
        "kind": "mangadl-audit-report",
        "mode": "url-file",
        "destinations": [str(destination)],
        "items": [{
            "canonical_url": "https://nhentai.net/g/123/",
            "status": "missing",
            "folders": [],
            "completeness": "unknown",
            "image_integrity": "unverified",
        }],
    }), encoding="utf-8")

    assert main(["repair", "-r", str(report), "-j"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["actions"] == []
    assert "report is stale" in payload["unsupported"][0]["reason"]


def test_batch_repair_reports_unknown_completion_as_unsupported(tmp_path, capsys) -> None:
    destination = tmp_path / "library"
    folder = destination / "Unknown Series"
    folder.mkdir(parents=True)
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({
        "schema": 1,
        "kind": "mangadl-audit-report",
        "mode": "url-file",
        "destinations": [str(destination)],
        "items": [{
            "canonical_url": "https://example.test/series",
            "status": "matched",
            "folders": [str(folder)],
            "completeness": "unknown",
            "image_integrity": "unverified",
        }],
    }), encoding="utf-8")

    assert main(["repair", "-r", str(report), "-j"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["actions"] == []
    assert "completion is unknown" in payload["unsupported"][0]["reason"]


def test_batch_repair_apply_requires_current_plan_token(tmp_path, capsys) -> None:
    destination = tmp_path / "library"
    destination.mkdir()
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({
        "schema": 1,
        "kind": "mangadl-audit-report",
        "mode": "url-file",
        "destinations": [str(destination)],
        "items": [{
            "canonical_url": "https://nhentai.net/g/123/",
            "status": "missing",
            "folders": [],
            "completeness": "unknown",
            "image_integrity": "unverified",
        }],
    }), encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main(["repair", "-r", str(report), "-f", "-C", "stale-token"])

    assert exc_info.value.code == 2
    assert "token from the current exact repair preview" in capsys.readouterr().err


def test_batch_repair_success_backfills_source_mapping(tmp_path, capsys, monkeypatch) -> None:
    destination = tmp_path / "library"
    destination.mkdir()
    report = tmp_path / "audit.json"
    report.write_text("{}", encoding="utf-8")
    action = {
        "kind": "download_gallery",
        "url": "https://nhentai.net/g/123/",
        "backend": "gallery-dl",
        "destination": str(destination),
    }
    plan = {
        "schema": 1,
        "kind": "mangadl-repair-plan",
        "mode": "apply",
        "actions": [action],
        "unsupported": [],
        "action_count": 1,
        "unsupported_count": 0,
        "confirmation_token": "current-token",
    }
    backfilled = []
    monkeypatch.setattr("mangadl.cli_core._build_batch_repair_plan", lambda _args: (plan, {}))
    monkeypatch.setattr("mangadl.cli_core._run_nested", lambda _args: 0)
    monkeypatch.setattr(
        "mangadl.cli_core._backfill_repaired_source",
        lambda url, root: backfilled.append((url, root)) or {"created": 1},
    )

    class _Audit:
        details = {"https://nhentai.net/g/123/": {"completeness": "complete"}}

    monkeypatch.setattr("mangadl.cli_core.audit_destinations", lambda *_args, **_kwargs: _Audit())

    assert main(["repair", "-r", str(report), "-f", "-C", "current-token", "-j"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert backfilled == [("https://nhentai.net/g/123/", destination)]
    assert payload["results"][0]["index_backfill"] == {"created": 1}
    assert payload["results"][0]["verified"] is True


def test_inspect_reports_hdporncomics_manhwa_classification(capsys) -> None:
    assert main(["inspect", "-u", "https://hdporncomics.com/manhwa/title/", "-j"]) == 0
    output = capsys.readouterr().out
    assert '"backend": "hdporncomics"' in output
    assert '"classification": "manhwa"' in output


def test_inspect_reports_manga18fx_manhwa_classification(capsys) -> None:
    assert main(["inspect", "-u", "https://manga18fx.com/manga/title/", "-j"]) == 0
    output = capsys.readouterr().out
    assert '"backend": "manga18fx"' in output
    assert '"classification": "manhwa"' in output


def test_auth_status_and_clear_do_not_print_cookie_values(tmp_path, capsys) -> None:
    auth_dir = tmp_path / "auth"
    secret = "never-print-this-cookie"
    ProfileStore(auth_dir).save(
        "example.com",
        "# Netscape HTTP Cookie File\n"
        f".example.com\tTRUE\t/\tTRUE\t4102444800\tsession\t{secret}\n",
        "Example UA",
        "chrome",
        source="chrome-cdp",
    )

    assert main(["auth", "status", "-d", "example.com", "-A", str(auth_dir), "-j"]) == 0
    output = capsys.readouterr().out
    assert '"profile": "present"' in output
    assert '"session"' in output
    assert secret not in output

    assert main(["auth", "clear", "-d", "example.com", "-A", str(auth_dir), "-j"]) == 0
    assert '"removed": true' in capsys.readouterr().out


def test_auth_sites_uses_installed_gallery_dl_registry(tmp_path, capsys) -> None:
    assert main(["auth", "sites", "-f", "manganelo", "-A", str(tmp_path / "auth"), "-j"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["site"] == "manganelo"
    assert payload[0]["target_url"].endswith("/manga/lets-play-hooky")


def test_auth_refresh_without_url_uses_default_saved_target(
    tmp_path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    captured: list[str] = []

    def fake_refresh(url, *, store, browser, **kwargs):
        captured.append(url)
        profile = store.save(
            url,
            "# Netscape HTTP Cookie File\n",
            "Chrome UA",
            browser,
            source="test",
            cookie_file=tmp_path / "mangakakalot.gg-cookies.txt",
        )
        from mangadl.gallery_auth import ProbeResult

        return profile, ProbeResult("success", 0, "ok")

    monkeypatch.setattr("mangadl.cli_core.refresh_profile", fake_refresh)

    assert main(["auth", "refresh", "-A", str(tmp_path / "auth"), "-j"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert captured == ["https://www.mangakakalot.gg/manga/lets-play-hooky"]
    assert payload["site"] == "manganelo"
    assert payload["cookie_file"].endswith("mangakakalot.gg-cookies.txt")


def test_missing_site_target_prompts_until_gallery_dl_accepts_same_site(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = TargetStore(tmp_path / "auth")
    answers = iter(
        [
            "https://www.mangakakalot.gg/search/story/like_no_other",
            "https://www.mangakakalot.gg/manga/like-no-other",
        ]
    )
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    url = _prompt_auth_target("manganelo", targets)

    assert url.endswith("/manga/like-no-other")
    assert targets.url_for("manganelo") == url


def test_interactive_site_selection_filters_runtime_registry(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = TargetStore(tmp_path / "auth")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(builtins, "input", lambda prompt="": "1")

    assert _interactive_auth_site(targets, "manganelo") == "manganelo"


def test_mangadl_tui_subcommand_dispatch(monkeypatch):
    called = []
    monkeypatch.setattr("mangadl.cli._launch_tui", lambda argv: called.append(argv) or 0)
    assert main(["tui"]) == 0
    assert len(called) == 1


def test_mangadl_tui_flag_dispatch(monkeypatch):
    called = []
    monkeypatch.setattr("mangadl.cli._launch_tui", lambda argv: called.append(argv) or 0)
    assert main(["--tui"]) == 0
    assert len(called) == 1

