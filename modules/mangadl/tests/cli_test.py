import argparse
import builtins
import json
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from mangadl.backends import GalleryDlBackend
from mangadl.cli import build_parser, main
from mangadl.cli_core import _interactive_auth_site, _prompt_auth_target
from mangadl.gallery_auth import ProfileStore
from mangadl.gallery_auth import TargetStore


def test_all_public_options_have_short_and_long_forms() -> None:
    parser = build_parser()
    parsers = [parser]
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    parsers.extend(subparsers.choices.values())
    for current in parsers:
        for action in current._actions:
            if not action.option_strings or action.dest == "help":
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
    assert args.max_workers == 4
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


def test_benchmark_bounds_cannot_exceed_hard_worker_limit(tmp_path) -> None:
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
                "9",
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


def test_repair_loose_defaults_to_dry_run_and_supports_explicit_mode(tmp_path, capsys) -> None:
    assert main(["repair-loose", "-d", str(tmp_path), "-N"]) == 0
    assert "DRY-RUN: 0 files across 0 galleries" in capsys.readouterr().out

    args = build_parser().parse_args(["repair-loose", "-d", str(tmp_path), "-n"])
    assert args.dry_run


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
