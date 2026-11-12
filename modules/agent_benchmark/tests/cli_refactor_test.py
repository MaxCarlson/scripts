"""Tests for Phase 02 CLI refactoring, setup command group, and backwards compatibility."""

from __future__ import annotations

import json

from agent_benchmark.cli import main, parser


def test_setup_all_flag_and_plan_equivalence(capsys):
    """Ensure 'setup -A' and 'setup plan -A' produce equivalent read-only plans."""
    rc1 = main(["setup", "-A", "-f", "json"])
    assert rc1 == 0
    out1 = json.loads(capsys.readouterr().out)

    rc2 = main(["setup", "plan", "-A", "-f", "json"])
    assert rc2 == 0
    out2 = json.loads(capsys.readouterr().out)

    assert out1["mode"] == "plan"
    assert out2["mode"] == "plan"
    assert out1["benchmarks"] == out2["benchmarks"]
    assert any(b["benchmark_id"] == "ifeval" for b in out1["benchmarks"])
    assert any(b["benchmark_id"] == "livecodebench" for b in out1["benchmarks"])


def test_setup_install_preview_without_execute(capsys):
    """Ensure 'setup install -A' without -x is a preview (dry run) and does not mutate anything."""
    rc = main(["setup", "install", "-A", "-f", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "install_preview"
    assert data["authorized"] is False
    assert len(data["actions"]) > 0


def test_setup_install_with_execute_dispatches_installer(capsys, monkeypatch):
    """Ensure 'setup install -A -x' triggers authorized installation via SourceManager."""
    from unittest.mock import MagicMock
    from agent_benchmark.external_sources import InstallReceipt

    mock_receipt = InstallReceipt(
        benchmark_id="ifeval",
        resource_name="mock",
        resource_type="git_sparse",
        install_path="C:/mock/path",
        revision="1234",
        spec_digest="abcd",
        installed_at="2026-11-11T00:00:00Z",
        platform="windows-x86_64",
        status="installed",
    )
    monkeypatch.setattr(
        "agent_benchmark.cli_commands.setup.SourceManager.install_resource",
        MagicMock(return_value=mock_receipt),
    )
    rc = main(["setup", "install", "-A", "-x", "-f", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "install_executed"
    assert len(data["installed"]) > 0


def test_setup_conflicting_all_and_dataset_rejected(capsys):
    """Ensure -A and -d cannot be used together in setup."""
    rc = main(["setup", "-A", "-d", "ifeval"])
    assert rc != 0
    assert "cannot specify both" in capsys.readouterr().err


def test_setup_flag_collision_scoping():
    """Ensure -A is scoped: in setup it is --all, in suite plan it is --api-format."""
    p = parser()

    # In setup, -A parses as all
    setup_args = p.parse_args(["setup", "plan", "-A"])
    assert setup_args.all is True

    # In suite plan, -A parses as api_format
    suite_args = p.parse_args(["suite", "plan", "-c", "aider-python-10", "-A", "openai_chat_completions"])
    assert suite_args.api_format == "openai_chat_completions"


def test_root_task_and_task_namespace_equivalence(tmp_path, capsys):
    """Ensure 'plan' and 'task plan' produce identical JSON output."""
    state = tmp_path / "state"

    rc1 = main(["plan", "-s", str(state)])
    assert rc1 == 0
    out1 = json.loads(capsys.readouterr().out)

    rc2 = main(["task", "plan", "-s", str(state)])
    assert rc2 == 0
    out2 = json.loads(capsys.readouterr().out)

    assert out1["task_id"] == out2["task_id"]
    assert out1["budget_profile"] == out2["budget_profile"]
    assert not state.exists()


def test_task_run_requires_execute(capsys):
    """Ensure 'task run' requires -x/--execute just like root 'run'."""
    rc = main(["task", "run", "-m", "test-model"])
    assert rc == 2
    assert "requires explicit -x/--execute authorization" in capsys.readouterr().err


def test_setup_status_and_verify(capsys):
    """Ensure setup status -A and setup verify -A run read-only."""
    rc1 = main(["setup", "status", "-A", "-f", "json"])
    assert rc1 == 0
    data1 = json.loads(capsys.readouterr().out)
    assert data1["mode"] == "status"
    assert len(data1["benchmarks"]) >= 4

    rc2 = main(["setup", "verify", "-A", "-f", "json"])
    assert rc2 == 0
    data2 = json.loads(capsys.readouterr().out)
    assert data2["mode"] == "verify"
