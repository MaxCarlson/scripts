import json
from pathlib import Path

import pytest
from PIL import Image


def make_target(tmp_path):
    target = tmp_path / "book"
    target.mkdir()
    Image.new("RGB", (64, 64), "blue").save(target / "01.png", compress_level=0)
    return target


def run_plan(main, manga, target, workspace, *extra):
    args = ["compress", "plan"] if manga else ["plan"]
    target_flag = "-d" if manga else "-i"
    return main(
        args + [target_flag, str(target), "-I", str(workspace), "-f", "all", "-m", "both", "-q", "85", "70", *extra]
    )


@pytest.mark.parametrize("manga", [False, True])
@pytest.mark.parametrize("depth", ["headers", "files"])
def test_inventory_creation_and_refresh_save_detailed_report(
    tmp_path, capsys, manga, depth
):
    target = make_target(tmp_path)
    from cli_test_support import main as standalone
    from mangadl.cli import main as mangadl

    main = mangadl if manga else standalone
    flags = (
        ["compress", "inventory", "-d", str(target)]
        if manga
        else ["inventory", "-i", str(target)]
    ) + ["-I", str(tmp_path / "state"), "-D", depth, "-J"]
    for _ in range(2):
        assert main(flags) == 0
        payload = json.loads(capsys.readouterr().out)
        report = payload["report_artifacts"]
        text = __import__("pathlib").Path(report["archive"]).read_text(encoding="utf-8")
        assert (
            "INVENTORY" in text
            and (".png" if depth == "files" else "PNG") in text
            and "book" in text
        )
        assert ("unverified" in text.lower()) == (depth == "files")
    suffix = "mangadl" if manga else "compresser"
    ws = tmp_path / "state" / f".{suffix}" / "book"
    assert (ws / "inventory.sqlite3").exists()
    assert not (ws / "trials.sqlite3").exists()
    assert len(list((ws / "reports").glob("*-inventory.md"))) == 2


@pytest.mark.parametrize("manga", [False, True])
def test_plan_compact_verbose_and_json_keep_full_artifacts(tmp_path, capsys, monkeypatch, manga):
    from cli_test_support import main as standalone
    from mangadl.cli import main as mangadl

    main = mangadl if manga else standalone
    monkeypatch.setenv("NO_COLOR", "")
    target = make_target(tmp_path)
    workspace = tmp_path / "state"
    inventory_args = ["compress", "inventory"] if manga else ["inventory"]
    inventory_args += ["-d" if manga else "-i", str(target), "-I", str(workspace), "-N"]
    assert main(inventory_args) == 0
    capsys.readouterr()

    assert run_plan(main, manga, target, workspace, "-N") == 0
    compact = capsys.readouterr()
    assert "12 recipes" in compact.out
    assert all(value in compact.out for value in ("AUTO", "WebP", "JPEG", "AVIF", "PNG"))
    owner = ".mangadl" if manga else ".compresser"
    latest = str(workspace / owner / target.name / "reports" / "latest.md")
    assert compact.out.replace("\n", "").count(latest) == 1
    assert "Report saved:" not in compact.out + compact.err
    assert "Latest report:" not in compact.out + compact.err
    assert "COMPLETED — plan" not in compact.out
    assert "Immutable design identity" not in compact.out
    assert "\x1b[" not in compact.out
    assert "[VERIFYING SNAPSHOT]" in compact.err
    assert "Report saved:" not in compact.err and "Latest report:" not in compact.err

    assert run_plan(main, manga, target, workspace, "-v", "-N") == 0
    verbose = capsys.readouterr()
    assert "Immutable design identity" in verbose.out
    assert "POPULATION STRATA" in verbose.out
    assert "PER-RECIPE PILOT QUOTAS" in verbose.out

    assert run_plan(main, manga, target, workspace, "-J", "-N") == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert set(payload) == {"operation", "plan", "report_artifacts", "report"}
    assert payload["operation"] == "plan"
    artifacts = payload["report_artifacts"]
    assert Path(artifacts["archive"]).is_file() and Path(artifacts["latest"]).is_file()
    archived = Path(artifacts["archive"]).read_text(encoding="utf-8")
    assert payload["plan"]["design_identity"] in archived
    assert "PER-RECIPE PILOT QUOTAS" in archived
    quota_group = payload["plan"]["recipe_quotas"][0]["per_stratum"][0][0].replace("|", r"\|")
    assert quota_group in archived
    assert "encoder" in archived and "auto" in archived
    assert len(payload["plan"]["recipes"]) == 12


def test_plan_report_publication_failure_does_not_claim_a_report(tmp_path, capsys, monkeypatch):
    import compresser.markdown_report as publication
    from cli_test_support import main

    target = make_target(tmp_path)
    workspace = tmp_path / "state"
    assert main(["inventory", "-i", str(target), "-I", str(workspace), "-N"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(
        publication, "publish_markdown_report", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )

    assert run_plan(main, False, target, workspace, "-N") == 2
    captured = capsys.readouterr()
    assert "Report could not be saved" in captured.err and "disk full" in captured.err
    assert "reports" not in captured.out
    assert "Report" not in captured.out
    assert "\x1b[" not in captured.out


def test_detailed_plan_labels_pilot_ceiling_and_perceptual_quality():
    from compresser.estimation_models import EstimationBudget, PopulationMember, PopulationView, RecipeSpec
    from compresser.report_models import ReportContext
    from compresser.reporting import build_plan_report
    from compresser.sampling_plan import build_plan

    now = "2026-10-17T20:00:00+00:00"
    member = PopulationMember("one", "one.png", 12, "PNG", (12, 1, "PNG"))
    population = PopulationView("population", Path("one"), "compresser", "headers", (), now, (member,))
    perceptual = RecipeSpec("webp", "perceptual", None, 0.99, "auto", 6)
    plan = build_plan(population, (perceptual,), EstimationBudget(pilot_images=64), seed=1)
    report = build_plan_report(plan, population_count=1, context=ReportContext(Path("one"), None))
    sections = {section.title: section for section in report.sections}
    budget_rows = dict(sections["PLAN BUDGET AND SNAPSHOT"].rows)
    assert budget_rows["Pilot image ceiling per recipe"] == "64"
    assert budget_rows["Actual shared pilot images"] == "1"
    assert sections["REQUESTED RECIPES"].rows[0][3] == "—"


@pytest.mark.parametrize("operation", ["analysis", "comparison", "preview"])
def test_json_operations_save_reports_and_implicit_inventory(
    tmp_path, capsys, operation
):
    from cli_test_support import main

    target = make_target(tmp_path)
    flags = [
        {"analysis": "analyze", "comparison": "compare", "preview": "preview"}[operation],
        "-i", str(target), "-J", "-e", "0",
    ]
    flags += {
        "analysis": ["-f", "png"],
        "comparison": ["-f", "png", "webp", "jpeg", "auto", "-m", "both", "-q", "85", "70"],
        "preview": ["-O", "-n", "1", "-f", "webp"],
    }[operation]
    assert main(flags) == 0
    payload = json.loads(capsys.readouterr().out)
    artifact = (payload[0] if isinstance(payload, list) else payload)[
        "report_artifacts"
    ]
    text = __import__("pathlib").Path(artifact["latest"]).read_text(encoding="utf-8")
    assert operation in text.lower() and "\x1b[" not in text
    assert list((tmp_path / ".compresser" / "book" / "reports").glob("*-inventory.md"))


def test_report_failure_returns_error_without_breaking_json(
    tmp_path, capsys, monkeypatch
):
    import compresser.markdown_report as publication
    from cli_test_support import main

    target = make_target(tmp_path)
    monkeypatch.setattr(
        publication,
        "publish_markdown_report",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    assert main(["inventory", "-i", str(target), "-J"]) == 2
    captured = capsys.readouterr()
    assert "disk full" in json.loads(captured.out)["report_artifacts"]["error"]
    assert "Report could not be saved" in captured.err


def test_cancelled_operation_saves_partial_report(tmp_path, capsys, monkeypatch):
    from cli_test_support import main
    from compresser.engine import CompressionEngine

    target = make_target(tmp_path)
    monkeypatch.setattr(
        CompressionEngine,
        "compress_batch",
        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    assert main(["analyze", "-i", str(target), "-f", "png", "-N"]) == 130
    text = (tmp_path / ".compresser" / "book" / "reports" / "latest.md").read_text(
        encoding="utf-8"
    )
    assert "cancelled" in text.lower()


def test_invalid_arguments_create_no_workspace(tmp_path):
    from cli_test_support import main

    target = make_target(tmp_path)
    with pytest.raises(SystemExit):
        main(["apply", "-i", str(target), "-w", "-s", "1"])
    assert not (tmp_path / ".compresser" / "book").exists()


def test_applied_write_report_failure_warns_without_undoing_source(
    tmp_path, capsys, monkeypatch
):
    from cli_test_support import main
    import compresser.markdown_report as publication

    target = make_target(tmp_path)
    before = (target / "01.png").read_bytes()
    monkeypatch.setattr(
        publication,
        "publish_markdown_report",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    assert main(["apply", "-i", str(target), "-f", "png", "-w", "-J"]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["applied_count"] == 1
    assert "may already have been modified" in captured.err
    assert (target / "01.png").read_bytes() != before


def test_manga_small_sample_trust_cache_scratch_and_report_scope(tmp_path, capsys):
    from mangadl.cli import main
    from pathlib import Path

    target = tmp_path / "library"
    for name in ("one", "two", "three"):
        directory = target / name
        directory.mkdir(parents=True)
        Image.new("RGB", (48, 48), "red").save(directory / "01.png", compress_level=0)
    before = {p: p.read_bytes() for p in target.rglob("*.png")}
    common = ["compress", "inventory", "-d", str(target), "-I", str(tmp_path / "state"), "-J"]
    assert main(common) == 0
    capsys.readouterr()
    flags = ["compress", "compare", "-d", str(target), "-I", str(tmp_path / "state"), "-J",
        "-U", "snapshot", "-f", "png", "webp", "jpeg", "auto", "-m", "both",
        "-q",
        "85",
        "70",
        "-s",
        "1",
        "-t",
        "2",
        "-B",
        "128",
        "-e",
        "0",
        "-X",
        str(tmp_path / "ssd"),
    ]
    for _ in range(2):
        assert main(flags) == 0
        rows = json.loads(capsys.readouterr().out)
        assert all(row["extrapolation"]["saved_bytes"] is not None for row in rows)
        assert rows[0]["sampling"]["sampled_galleries"] == 1
    assert sum(row["cache_hits"] for row in rows) > 0
    saved = Path(rows[0]["report_artifacts"]["archive"]).read_text(encoding="utf-8")
    assert "Membership refreshed" in saved and "False" in saved
    assert "PHASE WORKER-SECONDS" in saved and "scratch_dir" in saved
    assert {p: p.read_bytes() for p in before} == before
