import json

from mangadl.cli import build_parser
from mangadl.cli_core import _record_kavita_assignments
from mangadl.worker_core import _single_series_path


def test_run_cli_preserves_config_short_option_and_adds_collections(tmp_path):
    parser = build_parser(["run"])
    args = parser.parse_args(
        [
            "run",
            "-d",
            str(tmp_path),
            "-u",
            "https://site.test/series",
            "-c",
            str(tmp_path / "settings.toml"),
            "-M",
            "Shelf",
            "--kavita-url",
            "http://kavita:5000",
        ]
    )
    assert args.config == tmp_path / "settings.toml"
    assert args.collections == ["Shelf"]
    assert args.apply_kavita is False


def test_reconcile_cli_defaults_to_preview_and_apply_is_explicit(tmp_path):
    parser = build_parser(["kavita", "reconcile"])
    base = ["kavita", "reconcile", "-d", str(tmp_path), "-Z", "http://kavita:5000"]
    assert parser.parse_args(base).apply is False
    assert parser.parse_args(base + ["-f"]).apply is True


def test_worker_reports_only_single_output_series_folder(tmp_path):
    partial = tmp_path / "partial"
    destination = tmp_path / "library"
    (partial / "Series" / "chapter").mkdir(parents=True)
    (partial / "Series" / "chapter" / "001.jpg").write_bytes(b"x")
    assert _single_series_path(partial, destination, "https://site.test/series", "manga18fx") == str(
        destination / "Series"
    )
    (partial / "Other").mkdir()
    (partial / "Other" / "002.jpg").write_bytes(b"x")
    assert _single_series_path(partial, destination, "https://site.test/series", "manga18fx") == ""


def test_record_assignments_persists_canonical_url_and_expected_folder(tmp_path):
    destination = tmp_path / "library"
    log_dir = tmp_path / "logs"
    run_id = "run-1"
    event_path = log_dir / run_id / "events.jsonl"
    event_path.parent.mkdir(parents=True)
    event_path.write_text(
        json.dumps(
            {
                "event": "job_complete",
                "url": "https://site.test/series/",
                "data": {"state": "succeeded", "series_path": str(destination / "Series")},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    args = type("Args", (), {"destination": destination, "log_dir": log_dir})()
    _record_kavita_assignments(args, run_id, ["Shelf"], "http://kavita:5000", [], log_dir=log_dir, apply=False)
    saved = json.loads((destination / ".mangadl" / "kavita-assignments.json").read_text(encoding="utf-8"))
    assignment = saved["assignments"][0]
    assert assignment["source_url"] == "https://site.test/series/"
    assert assignment["expected_path"] == str(destination / "Series")
    assert assignment["collections"] == ["Shelf"]
    assert assignment["status"] == "pending"
