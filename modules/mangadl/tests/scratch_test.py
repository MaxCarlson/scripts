from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from mangadl.cli import main
from mangadl.manager import DownloadManager, RunOptions
from mangadl.partial_safety import plan_cleanup
from mangadl.scratch import partial_root_for, promote_partial
from mangadl.state import StateStore
from mangadl.worker_core import _command
from mangadl import worker_core


def test_scratch_roots_are_stable_and_isolated(tmp_path: Path) -> None:
    scratch = tmp_path / "ssd"
    first = partial_root_for(tmp_path / "library-a", scratch)
    assert first == partial_root_for(tmp_path / "library-a", scratch)
    assert first != partial_root_for(tmp_path / "library-b", scratch)
    assert first.parent.parent == scratch.resolve()
    assert (
        partial_root_for(tmp_path / "library-a", None)
        == tmp_path / "library-a" / "_partial"
    )


def test_promotion_copies_then_removes_scratch_and_keeps_controls(
    tmp_path: Path,
) -> None:
    root = partial_root_for(tmp_path / "library", tmp_path / "ssd")
    owner = root / "owner"
    image = owner / "series" / "001.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    control = owner / ".mangadl-partial.json"
    control.write_text("{}", encoding="utf-8")

    promote_partial(owner, tmp_path / "library", root)

    assert (tmp_path / "library" / "series" / "001.jpg").read_bytes() == b"image"
    assert not image.exists()
    assert control.is_file()


def test_promotion_retains_conflicting_scratch_file(tmp_path: Path) -> None:
    root = tmp_path / "ssd" / "_partial"
    owner = root / "owner"
    owner.mkdir(parents=True)
    source = owner / "001.jpg"
    source.write_bytes(b"new")
    destination = tmp_path / "library"
    destination.mkdir()
    target = destination / "001.jpg"
    target.write_bytes(b"old")

    with pytest.raises(FileExistsError, match="destination conflict"):
        promote_partial(owner, destination, root)

    assert source.read_bytes() == b"new"
    assert target.read_bytes() == b"old"


def test_promotion_failure_cleans_temporary_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mangadl import scratch

    root = tmp_path / "ssd" / "_partial"
    owner = root / "owner"
    owner.mkdir(parents=True)
    source = owner / "001.jpg"
    source.write_bytes(b"image")
    destination = tmp_path / "library"
    original_copy = scratch.shutil.copyfileobj

    def fail_after_partial_copy(input_stream, output_stream, length):
        output_stream.write(input_stream.read(2))
        raise OSError("simulated disk full")

    monkeypatch.setattr(scratch.shutil, "copyfileobj", fail_after_partial_copy)
    with pytest.raises(OSError, match="simulated disk full"):
        promote_partial(owner, destination, root)
    assert source.read_bytes() == b"image"
    assert not (destination / "001.jpg").exists()
    assert list(destination.iterdir()) == []

    monkeypatch.setattr(scratch.shutil, "copyfileobj", original_copy)
    promote_partial(owner, destination, root)
    assert (destination / "001.jpg").read_bytes() == b"image"
    assert not owner.exists()


def test_dry_run_reports_scratch_without_creating_it(tmp_path: Path, capsys) -> None:
    destination = tmp_path / "library"
    scratch = tmp_path / "ssd"
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
                "-n",
                "-J",
            ]
        )
        == 0
    )
    preview = json.loads(capsys.readouterr().out)
    assert preview["partial_root"] == str(partial_root_for(destination, scratch))
    assert not destination.exists()
    assert not scratch.exists()


def test_optimizer_rejects_scratch_until_its_workload_is_staged(tmp_path: Path) -> None:
    from mangadl.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser(["run", "optimize"]).parse_args(
            [
                "run",
                "optimize",
                "-u",
                "https://manga18fx.com/manga/example/",
                "-d",
                str(tmp_path / "library"),
                "--scratch-dir",
                str(tmp_path / "ssd"),
            ]
        )


def test_manager_passes_scratch_root_to_worker(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    scratch = tmp_path / "ssd"
    store = StateStore(tmp_path / "state.sqlite3")
    try:
        options = RunOptions(
            run_id="test",
            destination=destination,
            archive=tmp_path / "archive.sqlite3",
            state_db=tmp_path / "state.sqlite3",
            log_dir=tmp_path / "logs",
            workers=1,
            retries=0,
            retry_wait=1,
            scratch_dir=scratch,
        )
        manager = DownloadManager(options, store)
        command = manager._worker_command(
            1,
            {
                "id": 1,
                "attempt_id": "attempt",
                "canonical_url": "https://nhentai.net/g/123/",
                "backend": "gallery-dl",
            },
        )
        assert command[command.index("--partial-dir") + 1] == str(
            partial_root_for(destination, scratch)
        )
        assert "--scratch-mode" in command
    finally:
        store.close()


def test_manga18fx_checks_existing_library_before_scratch_download(
    tmp_path: Path,
) -> None:
    partial = tmp_path / "partial"
    args = Namespace(
        backend="manga18fx",
        cookies=None,
        destination=str(tmp_path / "library"),
        url="https://manga18fx.com/manga/example/",
        scratch_mode=True,
    )
    command = _command(args, partial)
    assert command[command.index("--existing-root") + 1] == str(tmp_path / "library")


def test_scratch_rejects_backend_without_destination_aware_resume(
    tmp_path: Path, capsys
) -> None:
    destination = tmp_path / "library"
    scratch = tmp_path / "ssd"
    assert (
        main(
            [
                "run",
                "-u",
                "https://hdporncomics.com/manhwa/example/",
                "-d",
                str(destination),
                "-S",
                str(scratch),
                "-n",
                "-J",
            ]
        )
        == 1
    )
    preview = json.loads(capsys.readouterr().out)
    assert "cannot safely check" in preview["unsupported"][0]["reason"]
    assert not destination.exists()
    assert not scratch.exists()


def test_existing_destination_partials_block_scratch_run(
    tmp_path: Path, capsys
) -> None:
    destination = tmp_path / "library"
    (destination / "_partial" / "old-owner").mkdir(parents=True)
    scratch = tmp_path / "ssd"
    args = [
        "run",
        "-u",
        "https://manga18fx.com/manga/example/",
        "-d",
        str(destination),
        "-S",
        str(scratch),
    ]
    assert main([*args, "-n", "-J"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["destination_partial_owners"] == 1
    with pytest.raises(SystemExit):
        main(args)
    assert not scratch.exists()


def test_cleanup_plans_from_scratch_root(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    root = partial_root_for(destination, tmp_path / "ssd")
    owner = root / "owner"
    owner.mkdir(parents=True)
    (owner / "001.jpg").write_bytes(b"image")
    planned_root, targets = plan_cleanup(
        destination, ["owner"], files_only=True, partial_root_override=root
    )
    assert planned_root == root
    assert targets[0].path == owner


def test_cli_previews_scratch_partial_cleanup(tmp_path: Path, capsys) -> None:
    destination = tmp_path / "library"
    scratch = tmp_path / "ssd"
    root = partial_root_for(destination, scratch)
    owner = root / "owner"
    owner.mkdir(parents=True)
    (owner / "001.jpg").write_bytes(b"image")

    assert (
        main(
            [
                "partials",
                "clean",
                "-d",
                str(destination),
                "-S",
                str(scratch),
                "-t",
                "owner",
                "-F",
                "-j",
            ]
        )
        == 0
    )
    preview = json.loads(capsys.readouterr().out)
    assert preview["partial_root"] == str(root)
    assert preview["status"] == "dry-run"
    assert (owner / "001.jpg").exists()


@pytest.mark.parametrize("conflict", [False, True])
def test_worker_promotes_or_retains_scratch_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, conflict: bool
) -> None:
    url = "https://nhentai.net/g/123/"
    destination = tmp_path / "library"
    root = partial_root_for(destination, tmp_path / "ssd")
    partial = root / worker_core._partial_key(url)
    image = partial / "nhentai" / "123 title" / "001.jpg"
    target = destination / "nhentai" / "123 title" / "001.jpg"
    if conflict:
        target.parent.mkdir(parents=True)
        target.write_bytes(b"other")
    script = (
        "from pathlib import Path; "
        f"p=Path({str(image)!r}); p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_bytes(b'image')"
    )
    args = worker_core.build_parser().parse_args(
        [
            "-R",
            "scratch-test",
            "-J",
            "1",
            "-A",
            "attempt",
            "-W",
            "1",
            "-u",
            url,
            "-b",
            "gallery-dl",
            "-d",
            str(destination),
            "-a",
            str(tmp_path / "archive.sqlite3"),
            "-P",
            str(root),
            "-L",
            str(tmp_path / "raw.log"),
            "--scratch-mode",
        ]
    )
    monkeypatch.setattr(
        worker_core, "_command", lambda _args, _partial: [sys.executable, "-c", script]
    )

    result = worker_core.run(args)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    if conflict:
        assert result == 2
        assert events[-1]["data"]["state"] == "failed_filesystem"
        assert image.read_bytes() == b"image"
        assert target.read_bytes() == b"other"
    else:
        assert result == 0
        assert events[-1]["data"]["state"] == "succeeded"
        assert target.read_bytes() == b"image"
        assert not partial.exists()
