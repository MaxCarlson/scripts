from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from mangadl import cli_core
from mangadl.repair_pages import PageRepairPlan, apply_page_repairs, make_page_repair_plan
from mangadl.scratch_controls import ScratchControls
from mangadl.state import StateStore


def test_repair_queue_routes_ranges_workers_ui_and_json(tmp_path: Path, monkeypatch, capsys) -> None:
    actions = [{"url": f"https://nhentai.net/g/{gallery}/", "destination": str(tmp_path)} for gallery in (1, 2)]
    plans = [PageRepairPlan(action["url"], tmp_path, 2, (gallery,),
                            {1: f"key-{gallery}-1", 2: f"key-{gallery}-2"}, (), (), None)
             for gallery, action in enumerate(actions, 1)]
    args = cli_core.build_parser().parse_args(["repair", "-r", str(tmp_path / "report.json"), "-w", "3"])
    captured = []

    def run(namespace):
        captured.append(namespace)
        assert os.environ["MANGADL_REPAIR_TOKEN"] == "guard-token"
        print('{"manager":"status"}')
        return 0

    monkeypatch.setattr(cli_core, "_run", run)
    monkeypatch.setenv("MANGADL_REPAIR_TOKEN", "previous-token")
    assert cli_core._run_repair_queue(actions, args, tmp_path / "archive.sqlite3", plans, "guard-token") == 0
    assert captured[0].workers == 3
    assert captured[0].no_ui is False
    assert captured[0].repair_file_ranges == {actions[0]["url"]: "1", actions[1]["url"]: "2"}
    assert captured[0].url == [action["url"] for action in actions]
    assert os.environ["MANGADL_REPAIR_TOKEN"] == "previous-token"
    capsys.readouterr()
    args.json = True
    assert cli_core._run_repair_queue(actions, args, tmp_path / "archive.sqlite3", plans, "guard-token") == 0
    output = capsys.readouterr()
    assert output.out == ""
    assert '"manager"' in output.err
    assert captured[-1].no_ui is True


def test_batch_page_repair_uses_one_guarded_download_and_reconciles_each_url(tmp_path: Path) -> None:
    archive = tmp_path / "archive.sqlite3"
    with sqlite3.connect(archive) as con:
        con.execute("CREATE TABLE archive(entry TEXT PRIMARY KEY)")
        con.executemany("INSERT INTO archive VALUES (?)", [(value,) for value in ("a1", "a2", "b1", "b2", "other")])
    plans = []
    for gallery, keys in ((1, {1: "a1", 2: "a2"}), (2, {1: "b1", 2: "b2"})):
        folder = tmp_path / str(gallery)
        folder.mkdir()
        plans.append(make_page_repair_plan(f"https://nhentai.net/g/{gallery}/", folder, 2, [2], [], keys, archive))
    downloads = []

    def run(prepared, token):
        downloads.append(prepared)
        assert (tmp_path / "repair.lock").read_text(encoding="utf-8") == token
        assert len(list((tmp_path / "q").glob("*/repair-manifest.json"))) == 2
        with sqlite3.connect(archive) as con:
            assert {row[0] for row in con.execute("SELECT entry FROM archive")} == {"a1", "b1", "other"}

    results = apply_page_repairs(plans, archive, tmp_path / "q", run,
                                 lambda plan: (plan.url.endswith("/1/"), set() if plan.url.endswith("/1/") else {2}))
    assert len(downloads) == 1
    assert [row["verified"] for row in results] == [True, False]
    assert len({row["archive_backup"] for row in results}) == 1
    assert len({row["quarantine"] for row in results}) == 2
    assert json.loads((Path(results[1]["quarantine"]) / "repair-manifest.json").read_text())["source_url"] == plans[1].url
    with sqlite3.connect(archive) as con:
        assert {row[0] for row in con.execute("SELECT entry FROM archive")} == {"a1", "a2", "b1", "other"}
    assert not (tmp_path / "repair.lock").exists()


def test_failed_repair_queue_keeps_pending_scratch_resumable(tmp_path: Path, monkeypatch, capsys) -> None:
    destination = tmp_path / "library"
    archive = destination / ".mangadl" / "archive.sqlite3"
    archive.parent.mkdir(parents=True)
    with sqlite3.connect(archive) as con:
        con.execute("CREATE TABLE archive(entry TEXT PRIMARY KEY)")
        con.executemany("INSERT INTO archive VALUES (?)", [(value,) for value in ("a1", "a2", "other")])
    state_path = archive.parent / "state.sqlite3"
    StateStore(state_path).close()
    scratch = tmp_path / "scratch"
    controls = ScratchControls(destination, scratch, archive, state_path, archive.parent / "logs")
    controls.prepare()
    folder = destination / "gallery"
    folder.mkdir()
    page_plan = make_page_repair_plan("https://nhentai.net/g/1/", folder, 2, [2], [], {1: "a1", 2: "a2"}, archive)
    action = {"kind": "repair_pages", "url": page_plan.url, "destination": str(destination),
              "folder": str(folder), "damaged_pages": [2]}
    plan = {"actions": [action], "unsupported": [], "action_count": 1, "unsupported_count": 0,
            "mode": "apply", "confirmation_token": "token"}
    monkeypatch.setattr(cli_core, "_build_batch_repair_plan", lambda _args: (plan, {0: (page_plan, archive)}))
    monkeypatch.setattr(cli_core, "_backfill_repaired_source", lambda *_args: {})

    def run(*_args):
        assert controls.validate_pending()
        with sqlite3.connect(controls.archive) as con:
            assert {row[0] for row in con.execute("SELECT entry FROM archive")} == {"a1", "other"}
        return 1

    class Audit:
        details = {page_plan.url: {"completeness": "incomplete", "missing_pages": [2]}}

    monkeypatch.setattr(cli_core, "_run_repair_queue", run)
    monkeypatch.setattr(cli_core, "audit_destinations", lambda *_args, **_kwargs: Audit())
    assert cli_core.main(["repair", "-r", str(tmp_path / "report.json"), "-S", str(scratch),
                          "-f", "-C", "token", "-j"]) == 1
    result = json.loads(capsys.readouterr().out)["results"][0]
    assert "remaining_pages" in result, result
    assert result["remaining_pages"] == [2]
    assert controls.validate_pending()
    assert not (archive.parent / "repair.lock").exists()
