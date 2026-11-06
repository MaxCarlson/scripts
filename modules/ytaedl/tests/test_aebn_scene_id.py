"""Regression tests for strict AEBN scene URL dispatch."""

from pathlib import Path

import pytest

from ytaedl import downloader, manager
from ytaedl.domain_index import DomainIndex


SCENE_URL = "https://straight.aebn.com/straight/movies/276944/natural-beauties-16#scene-1171754"


def test_scene_fragment_is_parsed_strictly():
    assert downloader._extract_aebn_scene_id(SCENE_URL) == "1171754"


@pytest.mark.parametrize("fragment", ["#scene-", "#scene-abc", "#foo", "#scene-12-extra"])
def test_malformed_scene_selection_fragment_is_rejected(fragment):
    with pytest.raises(ValueError, match="scene fragment"):
        downloader._extract_aebn_scene_id(f"https://straight.aebn.com/straight/movies/1/test{fragment}")


def test_url_without_fragment_has_no_scene_id():
    assert downloader._extract_aebn_scene_id("https://straight.aebn.com/straight/movies/1/test") is None


def test_aebndl_command_passes_id_and_preserves_original_url():
    command = downloader._build_aebndl_cmd(SCENE_URL, Path("out"), Path("work"), scene_id="1171754")

    assert command[command.index("-I") + 1] == "1171754"
    assert command[-1] == SCENE_URL
    assert "-s" not in command


def test_aebndl_command_keeps_legacy_scene_ordinal_argument():
    command = downloader._build_aebndl_cmd(SCENE_URL, Path("out"), Path("work"), scene=2)

    assert command[command.index("-s") + 1] == "2"
    assert "-I" not in command


def test_full_movie_command_has_no_scene_selector():
    url = "https://straight.aebn.com/straight/movies/276944/natural-beauties-16"

    command = downloader._build_aebndl_cmd(url, Path("out"), Path("work"))

    assert "-I" not in command
    assert "-s" not in command
    assert command[-1] == url


def test_manager_worker_and_domain_index_preserve_url_fragment(tmp_path):
    url_file = tmp_path / "scenes.txt"
    url_file.write_text(SCENE_URL + "\n", encoding="utf-8")

    assert manager._read_urls(url_file) == [SCENE_URL]
    assert downloader._read_urls(url_file) == [SCENE_URL]
    index = DomainIndex.build([url_file])
    entry = index.pick_url({}, max_per_domain=1, file_priority={0: 0})
    assert entry is not None
    assert entry.url == SCENE_URL


class NoopProgLogger:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def run_one(url, *, dry_run, monkeypatch, quiet=True):
    emitted = []
    monkeypatch.setattr(downloader, "_emit_json", emitted.append)
    result = downloader._run_one(
        tool="aebndl",
        urls=[url],
        out_dir=Path("out"),
        canonical_out_dir=Path("out"),
        partial_root=Path("partial"),
        raw_dir=Path("raw"),
        url_index=1,
        proglog=NoopProgLogger(),
        timeout=None,
        retries=0,
        quiet=quiet,
        dry_run=dry_run,
        progress_freq_s=None,
        max_ndjson_rate=-1,
        stall_seconds=4,
        program_deadline=None,
        max_dl_speed=None,
        max_height=None,
        extdl_fallback=False,
        skip_simulate_check=True,
    )
    return result, emitted


def test_dry_run_command_contains_scene_id_and_original_fragment(monkeypatch, capsys):
    (rc, _info), _emitted = run_one(SCENE_URL, dry_run=True, monkeypatch=monkeypatch, quiet=False)

    assert rc == 0
    output = capsys.readouterr().out
    assert "-I 1171754" in output
    assert SCENE_URL in output


def test_worker_dry_run_resolves_original_scene_url_from_url_file(tmp_path, capsys):
    url_file = tmp_path / "scene.txt"
    url_file.write_text(SCENE_URL + "\n", encoding="utf-8")

    rc = downloader.main([
        "-f", str(url_file),
        "-m", "aebn",
        "-o", str(tmp_path / "out"),
        "-w", str(tmp_path / "work"),
        "-g", str(tmp_path / "worker.log"),
        "-r", str(tmp_path / "raw"),
        "-n",
    ])

    assert rc == 0
    output = capsys.readouterr().out
    assert "-I 1171754" in output
    assert SCENE_URL in output


def test_invalid_scene_fragment_fails_before_subprocess_launch(monkeypatch):
    launches = []
    monkeypatch.setattr(downloader.subprocess, "Popen", lambda *args, **kwargs: launches.append(args))

    (rc, info), emitted = run_one(SCENE_URL.replace("scene-1171754", "scene-nope"), dry_run=False, monkeypatch=monkeypatch)

    assert rc != 0
    assert info["reason"].startswith("invalid AEBN scene fragment")
    assert launches == []
    assert any(event.get("event") == "finish" and event.get("rc") != 0 for event in emitted)


def test_aebndl_command_rejects_non_numeric_scene_id():
    with pytest.raises(ValueError, match="scene ID"):
        downloader._build_aebndl_cmd(SCENE_URL, Path("out"), Path("work"), scene_id="abc")
