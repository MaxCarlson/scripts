"""Read-only setup status reporting contracts using synthetic homes."""
from __future__ import annotations

import json
import io
import shutil
import subprocess
from pathlib import Path

import pytest

from local_agent_bridge import commands
from local_agent_bridge.setup import manifest, planner
from local_agent_bridge.setup.installer import apply_plan
from local_agent_bridge.setup.planner import build_plan
from local_agent_bridge.setup.status import build_status_report, format_status_report


def _copy_assets(tmp_path: Path, monkeypatch) -> Path:
    resources = tmp_path / "package" / "resources"
    shutil.copytree(manifest.assets(), resources)
    monkeypatch.setattr(planner, "assets", lambda: resources)
    monkeypatch.setattr(manifest, "assets", lambda: resources)
    return resources


def _report(plan, tmp_path: Path):
    return build_status_report(
        plan,
        package_version="3.4.0",
        module_path=tmp_path / "package" / "local_agent_bridge" / "commands.py",
        resources_path=tmp_path / "package" / "resources",
        repository={"state": "not_associated"},
    )


def test_real_four_resource_stale_scenario_is_clear_and_read_only(tmp_path, monkeypatch, capsys):
    resources = _copy_assets(tmp_path, monkeypatch)
    home = tmp_path / "synthetic-home"
    initial = build_plan(home, strategy="copy", environ={})
    apply_plan(initial)

    # Model the newer packaged guidance being released after the copied install.
    (resources / "skills/local-agent-handoff/SKILL.md").write_text(
        (resources / "skills/local-agent-handoff/SKILL.md").read_text()
        + "\nUpdated dispatch instructions.\n"
    )
    prompt = resources / "skills/local-agent-handoff/resources/local-worker.md"
    prompt.write_text(prompt.read_text() + "\nUse bounded source reads.\n")

    before_receipt = (home / ".local/share/local-agent/receipt.json").read_bytes()
    plan = build_plan(home, strategy="copy", environ={})
    report = _report(plan, tmp_path)

    assert report["summary"] == {
        "state": "out_of_sync",
        "total": 15,
        "current": 11,
        "outdated": 4,
        "missing": 0,
        "conflicts": 0,
        "retiring": 0,
    }
    outdated = {row["resource_id"]: row for row in report["resources"] if row["status"] == "outdated"}
    assert set(outdated) == {
        "codex.skill", "agy.skill", "shared.local-worker", "shared.local-reviewer"
    }
    assert all(row["method"] == "copy" for row in outdated.values())
    assert "SKILL.md" in outdated["codex.skill"]["tree_diff"]["changed"]
    assert "resources/local-worker.md" in outdated["agy.skill"]["tree_diff"]["changed"]
    assert "local-worker.md" in " ".join(report["provenance"]["resource_sources"]["shared.local-worker"])
    assert report["features"]["code_retrieval"]["status"] == "disabled"
    assert report["features"]["structural_retrieval"]["status"] == "disabled"
    assert report["features"]["checkpoint_compaction"]["status"] == "disabled"
    assert (home / ".local/share/local-agent/receipt.json").read_bytes() == before_receipt

    output = format_status_report(report, color=False)
    assert "Installation: OUT OF SYNC" in output
    assert "OUTDATED  codex.skill" in output
    assert "OUTDATED  agy.skill" in output
    assert "OUTDATED  shared.local-worker" in output
    assert "OUTDATED  shared.local-reviewer" in output
    assert "copy" in output.lower()
    assert "disabled" in output.lower()
    assert "-s copy" in output
    assert "--no-code-retrieval" in output
    assert "--no-structural-retrieval" in output
    assert "--no-checkpoint-compaction" in output

    text_code = commands.main(["setup", "status", "-H", str(home), "-s", "copy"])
    text_output = capsys.readouterr().out
    assert text_code == 3
    assert "Installation: OUT OF SYNC" in text_output
    for resource_id in ("codex.skill", "agy.skill", "shared.local-worker", "shared.local-reviewer"):
        assert f"OUTDATED  {resource_id}" in text_output

    cli_code = commands.main(["setup", "status", "-H", str(home), "-s", "copy", "-j"])
    cli_output = capsys.readouterr().out
    result = json.loads(cli_output)
    assert cli_code == 3
    assert result["code"] == 3
    assert result["summary"]["current"] == 11
    assert result["summary"]["outdated"] == 4
    assert "\u001b[" not in cli_output
    assert (home / ".local/share/local-agent/receipt.json").read_bytes() == before_receipt


def test_file_byte_drift_with_same_filename_is_a_conflict(tmp_path, monkeypatch):
    _copy_assets(tmp_path, monkeypatch)
    home = tmp_path / "synthetic-home"
    apply_plan(build_plan(home, strategy="copy", environ={}))
    changed = home / ".agents/skills/local-agent-handoff/SKILL.md"
    changed.write_bytes(changed.read_bytes().replace(b"handoff", b"HANDOFF", 1))

    plan = build_plan(home, strategy="copy", environ={})
    report = _report(plan, tmp_path)
    item = next(row for row in report["resources"] if row["resource_id"] == "codex.skill")

    assert item["status"] == "conflict"
    assert report["summary"]["conflicts"] >= 1
    assert report["summary"]["state"] == "conflicts"


def test_missing_required_resources_are_counted_separately(tmp_path):
    home = tmp_path / "empty-home"
    plan = build_plan(home, strategy="copy", environ={})
    report = _report(plan, tmp_path)

    assert report["summary"]["state"] == "not_installed"
    assert report["summary"]["missing"] == len(plan.operations)
    assert report["summary"]["conflicts"] == 0
    assert all(row["status"] == "missing" for row in report["resources"])
    assert "MISSING" in format_status_report(report, color=False)


def test_current_installation_is_prominently_marked(tmp_path):
    home = tmp_path / "synthetic-home"
    apply_plan(build_plan(home, strategy="copy", environ={}))
    report = _report(build_plan(home, strategy="copy", environ={}), tmp_path)

    assert report["summary"]["state"] == "in_sync"
    assert report["summary"]["current"] == 15
    output = format_status_report(report, color=False)
    assert "Installation: IN SYNC" in output
    assert "CURRENT" in output
    assert "No setup changes required" in output


def test_removed_owned_resource_is_reported_missing_and_conflicted(tmp_path):
    home = tmp_path / "synthetic-home"
    apply_plan(build_plan(home, strategy="copy", environ={}))
    (home / ".agents/skills/local-agent-handoff/SKILL.md").unlink()

    plan = build_plan(home, strategy="copy", environ={})
    report = _report(plan, tmp_path)
    item = next(row for row in report["resources"] if row["resource_id"] == "codex.skill")

    assert item["status"] == "conflict"
    assert item["installed_type"] == "directory"
    assert "SKILL.md" in item["tree_diff"]["missing"]
    assert report["summary"]["missing"] == 0
    assert report["summary"]["conflicts"] == 1


def test_removed_owned_directory_is_reported_missing_and_conflicted(tmp_path):
    home = tmp_path / "synthetic-home"
    apply_plan(build_plan(home, strategy="copy", environ={}))
    shutil.rmtree(home / ".agents/skills/local-agent-handoff")

    report = _report(build_plan(home, strategy="copy", environ={}), tmp_path)
    item = next(row for row in report["resources"] if row["resource_id"] == "codex.skill")

    assert item["status"] == "missing"
    assert item["installed_type"] == "missing"
    assert item["conflict"]
    assert report["summary"]["missing"] == 1
    assert report["summary"]["conflicts"] == 1


def test_directory_link_target_drift_is_visible(tmp_path):
    home = tmp_path / "synthetic-home"
    plan = build_plan(home, strategy="copy", environ={})
    apply_plan(plan)
    link = home / ".agents/skills/local-agent-handoff"
    backup = tmp_path / "replacement-skill"
    shutil.copytree(link, backup)
    shutil.rmtree(link)
    try:
        link.symlink_to(backup, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks require platform privileges")

    fresh = build_plan(home, strategy="copy", environ={})
    report = _report(fresh, tmp_path)
    item = next(row for row in report["resources"] if row["resource_id"] == "codex.skill")

    assert item["status"] == "conflict"
    assert item["installed_type"] == "link"
    assert item["installed_target"] == str(backup.resolve())
    assert item["method"] == "copy"


def test_unexpected_link_target_is_conflict_without_traversing_target(tmp_path, monkeypatch):
    from local_agent_bridge.setup import files

    home = tmp_path / "synthetic-home"
    apply_plan(build_plan(home, strategy="copy", environ={}))
    path = home / ".agents/skills/local-agent-handoff"
    expected_inspect = files.inspect
    unexpected = tmp_path / "untrusted-link-target"
    unexpected.mkdir()

    def inspect_with_link(candidate):
        actual = expected_inspect(candidate)
        if Path(candidate) == path:
            return {"kind": "link", "target": str(unexpected), "hash": actual["hash"]}
        return actual

    monkeypatch.setattr(planner, "inspect", inspect_with_link)
    plan = build_plan(home, strategy="copy", environ={})
    report = _report(plan, tmp_path)
    item = next(row for row in report["resources"] if row["resource_id"] == "codex.skill")

    assert item["status"] == "conflict"
    assert item["installed_target"] == str(unexpected)
    assert item["tree_diff"]["missing"] == []


@pytest.mark.parametrize(
    ("mode", "relative_path", "resource_id"),
    [
        ("generic", ".gemini/settings.json", "agy.defaults"),
        ("generic", ".codex/config.toml", "codex.config"),
    ],
)
def test_semantic_configuration_equivalence_is_not_claimed_byte_exact(
    tmp_path, mode, relative_path, resource_id
):
    home = tmp_path / "synthetic-home"
    apply_plan(build_plan(home, strategy="copy", mode=mode, environ={}))
    path = home / relative_path
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    plan = build_plan(home, strategy="copy", mode=mode, environ={})
    report = _report(plan, tmp_path)
    item = next(row for row in report["resources"] if row["resource_id"] == resource_id)

    assert item["status"] == "current"
    assert item["verification"] == "semantic"
    assert item["byte_hash_matches"] is False
    assert "semantic" in format_status_report(report, color=False).lower()


@pytest.mark.parametrize(
    ("relative_path", "resource_id", "edit"),
    [
        (
            ".codex/config.toml", "codex.config",
            lambda text: text.replace('args = ["-y", "opencode-mcp@3.0.0"]', 'args = ["-y", "changed"]'),
        ),
        (
            ".gemini/antigravity-cli/mcp_config.json", "agy.mcp",
            lambda text: text.replace('"-y"', '"other"', 1),
        ),
    ],
)
def test_managed_json_and_toml_drift_is_reported_semantically(
    tmp_path, relative_path, resource_id, edit
):
    home = tmp_path / "synthetic-home"
    apply_plan(build_plan(home, strategy="copy", environ={}))
    path = home / relative_path
    path.write_text(edit(path.read_text()))

    plan = build_plan(home, strategy="copy", environ={})
    report = _report(plan, tmp_path)
    item = next(row for row in report["resources"] if row["resource_id"] == resource_id)

    assert item["status"] == "conflict"
    assert item["verification"] == "semantic"
    assert report["summary"]["conflicts"] >= 1


def test_optional_feature_install_failure_differs_from_intentionally_disabled(tmp_path):
    disabled = build_status_report(
        build_plan(tmp_path / "disabled", strategy="copy", mode="generic", environ={}),
        package_version="3.4.0", module_path=tmp_path / "commands.py", resources_path=tmp_path,
        repository={"state": "not_associated"},
    )
    assert disabled["features"]["code_retrieval"]["status"] == "disabled"
    assert disabled["features"]["code_retrieval"]["installation_state"] == "not_applicable"

    home = tmp_path / "enabled"
    apply_plan(build_plan(home, strategy="copy", mode="generic", environ={}, code_retrieval=True))
    tool = home / ".config/opencode/tools/code_locate.js"
    tool.unlink()
    report = _report(build_plan(home, strategy="copy", mode="generic", environ={}), tmp_path)

    feature = report["features"]["code_retrieval"]
    assert feature["enabled"] is True
    assert feature["status"] == "enabled"
    assert feature["installation_state"] == "conflict"
    assert report["summary"]["conflicts"] >= 1


def test_json_status_adds_summary_without_changing_operations_or_exit_code(tmp_path, capsys):
    home = tmp_path / "synthetic-home"
    code = commands.main(["setup", "status", "-H", str(home), "-s", "copy", "-j"])
    output = capsys.readouterr().out
    result = json.loads(output)

    assert code == 3
    assert result["code"] == 3
    assert len(result["operations"]) == 15
    assert {"resource_id", "path", "kind", "before", "desired_hash", "source", "method", "action", "conflict", "retire"} <= set(result["operations"][0])
    assert result["summary"]["missing"] == 15
    assert result["provenance"]["package"]["version"] == "3.5.0"
    assert result["features"]["checkpoint_compaction"]["status"] == "disabled"
    assert "\u001b[" not in output


def test_auto_color_can_be_enabled_without_changing_plain_output(tmp_path):
    report = _report(build_plan(tmp_path / "empty", strategy="copy", environ={}), tmp_path)

    plain = format_status_report(report, color=False)
    colored = format_status_report(report, color=True)

    assert "\u001b[" not in plain
    assert "\u001b[" in colored
    assert "NOT INSTALLED" in colored


def test_default_status_colors_only_for_tty_and_respects_no_color(tmp_path, monkeypatch):
    report = _report(build_plan(tmp_path / "empty", strategy="copy", environ={}), tmp_path)

    class TTY(io.StringIO):
        def isatty(self):
            return True

    terminal = TTY()
    monkeypatch.setattr(commands.sys, "stdout", terminal)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    commands._output(report, as_json=False)
    assert "\u001b[" in terminal.getvalue()

    terminal = TTY()
    monkeypatch.setattr(commands.sys, "stdout", terminal)
    monkeypatch.setenv("NO_COLOR", "1")
    commands._output(report, as_json=False)
    assert "\u001b[" not in terminal.getvalue()


def test_active_package_provenance_does_not_assume_cwd_is_source(tmp_path, monkeypatch):
    from local_agent_bridge.setup import status

    module_path = tmp_path / "venv/site-packages/local_agent_bridge/commands.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# installed package")
    source_repo = tmp_path / "unrelated-source-checkout"
    source_repo.mkdir()
    monkeypatch.chdir(source_repo)
    info = status.package_provenance(
        "3.4.0", module_path=module_path, resources_path=module_path.parent / "resources"
    )

    assert info["package"]["module_path"] == str(module_path.resolve())
    assert info["source_repository"]["state"] == "not_associated"
    assert str(source_repo.resolve()) not in json.dumps(info)


def test_active_tracked_package_reports_source_repo_version_comparison(tmp_path):
    from local_agent_bridge.setup import status

    root = tmp_path / "tracked-source"
    package = root / "modules/local_agent_bridge/local_agent_bridge"
    package.mkdir(parents=True)
    module_path = package / "commands.py"
    module_path.write_text("# source checkout")
    project = root / "modules/local_agent_bridge/pyproject.toml"
    project.write_text('[project]\nname="local-agent-bridge"\nversion="3.5.0"\n')
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "add", "--", "modules"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
         "commit", "-m", "synthetic package"],
        check=True, capture_output=True,
    )

    info = status.package_provenance("3.4.0", module_path=module_path, resources_path=package / "resources")

    assert info["source_repository"]["state"] == "associated"
    assert info["source_repository"]["package_version"] == "3.5.0"
    assert info["source_repository"]["newer_than_active_package"] is True
