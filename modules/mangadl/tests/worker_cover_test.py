from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from mangadl import worker
from mangadl.covers import CoverResult


def test_worker_runs_cover_postprocessor_after_success(tmp_path: Path, monkeypatch) -> None:
    raw_log = tmp_path / "worker.log"
    args = Namespace(
        destination=str(tmp_path),
        url="https://manga18fx.com/manga/example/",
        cookies=None,
        raw_log=str(raw_log),
    )
    monkeypatch.setattr(worker._core, "run", lambda _: 0)
    monkeypatch.setattr(worker, "snapshot_top_level", lambda _: {})
    monkeypatch.setattr(
        worker,
        "install_download_cover",
        lambda *args, **kwargs: CoverResult(url=args[0], status="downloaded"),
    )
    monkeypatch.delenv("MANGADL_APPLY_KAVITA_COVERS", raising=False)

    assert worker.run(args) == 0
    payload = json.loads(raw_log.read_text(encoding="utf-8"))
    assert payload["event"] == "cover"
    assert payload["status"] == "downloaded"


def test_worker_cover_failure_does_not_fail_completed_download(tmp_path: Path, monkeypatch) -> None:
    raw_log = tmp_path / "worker.log"
    args = Namespace(
        destination=str(tmp_path),
        url="https://simply-hentai.com/example/",
        cookies=None,
        raw_log=str(raw_log),
    )
    monkeypatch.setattr(worker._core, "run", lambda _: 0)
    monkeypatch.setattr(worker, "snapshot_top_level", lambda _: {})
    monkeypatch.setattr(
        worker,
        "install_download_cover",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cover failed")),
    )

    assert worker.run(args) == 0
    payload = json.loads(raw_log.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "cover failed" in payload["message"]


def test_scratch_cover_uses_only_promoted_folders_not_library_scan(tmp_path: Path, monkeypatch) -> None:
    raw_log = tmp_path / "worker.log"
    folder = tmp_path / "library" / "Example Series"
    args = Namespace(
        destination=str(tmp_path / "library"),
        url="https://manga18fx.com/manga/example/",
        cookies=None,
        raw_log=str(raw_log),
        scratch_mode=True,
        promoted_folders=(folder,),
    )
    monkeypatch.setattr(worker._core, "run", lambda _: 0)
    monkeypatch.setattr(
        worker, "snapshot_top_level",
        lambda _: (_ for _ in ()).throw(AssertionError("library-wide scan")),
    )
    monkeypatch.setattr(
        worker, "install_download_cover_candidates",
        lambda _url, folders, **_kwargs: CoverResult(
            url=args.url, status="downloaded", folder=str(folders[0])
        ),
    )
    monkeypatch.delenv("MANGADL_APPLY_KAVITA_COVERS", raising=False)

    assert worker.run(args) == 0
    payload = json.loads(raw_log.read_text(encoding="utf-8"))
    assert payload["status"] == "downloaded"
    assert payload["folder"] == str(folder)
