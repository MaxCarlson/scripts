from __future__ import annotations

import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts_setup.selective_validation import (
    assess_import_provenance,
    create_temporary_root,
    _failure_evidence,
    find_matching_evidence,
    resolve_pytest_selectors,
    run_selective_target,
    write_run_report,
)


def make_target(tmp_path: Path) -> tuple[Path, dict]:
    repo_root = tmp_path / "repo"
    target_root = repo_root / "modules" / "consumer"
    (target_root / "consumer_pkg").mkdir(parents=True)
    (target_root / "tests").mkdir()
    (target_root / "consumer_pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target_root / "tests" / "test_api.py").write_text("def test_api(): pass\n", encoding="utf-8")
    (target_root / "tests" / "test_other.py").write_text("def test_other(): pass\n", encoding="utf-8")
    (target_root / "pyproject.toml").write_text("[project]\nname='consumer-pkg'\n", encoding="utf-8")
    target_spec = {
        "working_directory": "modules/consumer",
        "bootstrap": [{"executable": "python", "arguments": ["-m", "pip", "uninstall", "-y", "consumer-pkg"]}],
        "selective_validation": {
            "test_roots": ["tests"],
            "source_roots": ["consumer_pkg"],
            "dependency_inputs": ["pyproject.toml"],
            "pytest_arguments": ["-q", "--strict-config"],
            "imports": [{"module": "consumer_pkg", "expected_root": "consumer_pkg", "distribution": "consumer-pkg"}],
        },
    }
    return repo_root, target_spec


def test_resolves_node_ids_files_and_dotted_test_modules(tmp_path: Path) -> None:
    repo_root, target_spec = make_target(tmp_path)
    target_root = repo_root / target_spec["working_directory"]

    selected = resolve_pytest_selectors(
        target_root,
        target_spec["selective_validation"]["test_roots"],
        node_ids=["tests/test_api.py::test_api"],
        files=["tests/test_other.py"],
        modules=["tests.test_api"],
    )

    assert selected == [
        "tests/test_api.py::test_api",
        "tests/test_other.py",
        "tests/test_api.py",
    ]


def test_rejects_selectors_outside_the_consumer_and_unknown_modules(tmp_path: Path) -> None:
    repo_root, target_spec = make_target(tmp_path)
    target_root = repo_root / target_spec["working_directory"]
    outside = tmp_path / "outside_test.py"
    outside.write_text("def test_x(): pass\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inside the target"):
        resolve_pytest_selectors(target_root, ["tests"], files=[str(outside)])
    with pytest.raises(ValueError, match="module was not found"):
        resolve_pytest_selectors(target_root, ["tests"], modules=["tests.missing"])


def test_import_provenance_rejects_stale_editable_and_retired_sources(tmp_path: Path) -> None:
    target_root = tmp_path / "worktree" / "modules" / "consumer"
    expected = target_root / "consumer_pkg" / "__init__.py"
    stale = tmp_path / "old-checkout" / "consumer_pkg" / "__init__.py"
    retired = tmp_path / "worktree" / "modules" / "resource_metrics" / "resource_metrics.py"
    expected.parent.mkdir(parents=True)
    stale.parent.mkdir(parents=True)
    retired.parent.mkdir(parents=True)
    expected.touch()
    stale.touch()
    retired.touch()

    result = assess_import_provenance(
        tmp_path / "worktree",
        target_root,
        [{"module": "consumer_pkg", "expected_root": "consumer_pkg"}],
        [{"module": "consumer_pkg", "origin": str(stale), "search_locations": [], "editable_source": str(stale.parent)}],
        forbidden_roots=["modules/resource_metrics"],
    )

    assert not result["ok"]
    assert any("outside expected root" in error for error in result["errors"])
    assert any("retired source" in error for error in result["errors"])


def test_import_provenance_reports_wrong_editable_checkout_when_runtime_path_is_local(tmp_path: Path) -> None:
    repo_root = tmp_path / "worktree"
    target_root = repo_root / "modules" / "consumer"
    package_init = target_root / "consumer_pkg" / "__init__.py"
    package_init.parent.mkdir(parents=True)
    package_init.touch()

    result = assess_import_provenance(
        repo_root,
        target_root,
        [{"module": "consumer_pkg", "expected_root": "consumer_pkg"}],
        [{
            "module": "consumer_pkg",
            "origin": str(package_init),
            "search_locations": [str(package_init.parent)],
            "editable_source": str(tmp_path / "old-checkout"),
        }],
    )

    assert result["ok"]
    assert any("editable distribution metadata" in warning for warning in result["warnings"])


def test_selective_run_ignores_bootstrap_and_records_exact_execution(tmp_path: Path) -> None:
    repo_root, target_spec = make_target(tmp_path)
    calls: list[list[str]] = []
    target_root = repo_root / target_spec["working_directory"]

    def probe(_imports, _target_root, _python, _environment):
        return {
            "python": sys.executable,
            "python_version": "3.test",
            "prefix": str(tmp_path / "venv"),
            "site_packages": [],
            "distributions": [{"name": "pytest", "version": "9.test"}],
            "imports": [{
                "module": "consumer_pkg",
                "origin": str(target_root / "consumer_pkg" / "__init__.py"),
                "search_locations": [str(target_root / "consumer_pkg")],
                "distribution": "consumer-pkg",
                "version": "1.0",
                "editable_source": str(target_root),
            }],
        }

    def command_runner(command, **kwargs):
        calls.append(list(command))
        return CompletedProcess(command, 0, stdout="1 passed in 0.01s\n", stderr="")

    result = run_selective_target(
        repo_root,
        "consumer",
        target_spec,
        node_ids=["tests/test_api.py::test_api"],
        files=[],
        modules=[],
        python_executable=sys.executable,
        import_probe=probe,
        command_runner=command_runner,
        reuse_evidence=False,
    )

    assert result["status"] == "passed"
    assert len(calls) == 1
    assert "pytest" in calls[0]
    assert "pip" not in calls[0]
    assert result["selected"] == ["tests/test_api.py::test_api"]
    assert result["duration_seconds"] >= 0
    assert Path(result["report_path"]).is_file()
    record = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert record["interpreter"]["path"] == sys.executable
    assert record["worktree"] == str(repo_root.resolve())
    assert record["exit_code"] == 0
    assert record["dependency_identities"] == [{"name": "pytest", "version": "9.test"}]
    assert Path(record["import_identities"][0]["origin"]).name == "__init__.py"


def test_evidence_reuse_requires_identical_inputs_and_invalidates_on_source_change(tmp_path: Path) -> None:
    repo_root, target_spec = make_target(tmp_path)
    target_root = repo_root / target_spec["working_directory"]
    calls: list[int] = []

    def probe(_imports, _target_root, _python, _environment):
        return {
            "python": sys.executable,
            "python_version": "3.test",
            "prefix": str(tmp_path / "venv"),
            "site_packages": [],
            "distributions": [{"name": "pytest", "version": "9.test"}],
            "imports": [{
                "module": "consumer_pkg",
                "origin": str(target_root / "consumer_pkg" / "__init__.py"),
                "search_locations": [str(target_root / "consumer_pkg")],
                "distribution": "consumer-pkg",
                "version": "1.0",
                "editable_source": str(target_root),
            }],
        }

    def command_runner(command, **kwargs):
        calls.append(len(calls) + 1)
        return CompletedProcess(command, 0, stdout="1 passed\n", stderr="")

    def run(node_id: str):
        return run_selective_target(
            repo_root, "consumer", target_spec, [node_id], [], [],
            python_executable=sys.executable, import_probe=probe,
            command_runner=command_runner,
        )

    first = run("tests/test_api.py::test_api")
    same = run("tests/test_api.py::test_api")
    other_selection = run("tests/test_other.py::test_other")
    (target_root / "consumer_pkg" / "__init__.py").write_text("VALUE = 2\n", encoding="utf-8")
    changed_source = run("tests/test_api.py::test_api")
    (target_root / "pyproject.toml").write_text("[project]\nname='consumer-pkg'\n# dependency change\n", encoding="utf-8")
    changed_dependency = run("tests/test_api.py::test_api")

    assert first["status"] == "passed"
    assert same["status"] == "reused"
    assert same["reused_from"] == first["execution_id"]
    assert other_selection["status"] == "passed"
    assert changed_source["status"] == "passed"
    assert changed_dependency["status"] == "passed"
    assert len(calls) == 4
    assert find_matching_evidence(Path(repo_root) / "docs/test-results/selective/runs", first["input_fingerprint"])


def test_concurrent_reports_and_temp_roots_are_isolated(tmp_path: Path) -> None:
    repo_root, target_spec = make_target(tmp_path)
    target_root = repo_root / target_spec["working_directory"]
    runs_root = repo_root / "docs" / "test-results" / "selective" / "runs"

    def write_one(_index: int):
        run_id = uuid.uuid4().hex
        temp_root = create_temporary_root(target_root, run_id)
        report_path = write_run_report(runs_root, {"execution_id": run_id, "status": "passed"})
        return run_id, temp_root, report_path

    with ThreadPoolExecutor(max_workers=8) as pool:
        runs = list(pool.map(write_one, range(24)))

    assert len({run_id for run_id, _, _ in runs}) == 24
    assert len({temp_root for _, temp_root, _ in runs}) == 24
    assert len({report_path for _, _, report_path in runs}) == 24
    for run_id, temp_root, report_path in runs:
        assert temp_root.is_dir()
        assert json.loads(report_path.read_text(encoding="utf-8"))["execution_id"] == run_id


def test_failure_evidence_is_bounded_and_redacts_credentials() -> None:
    evidence = _failure_evidence("authorization: Bearer TOPSECRET\n" + "failure detail\n" * 500)

    assert len(evidence) <= 8100
    assert "TOPSECRET" not in evidence
    assert "failure detail" in evidence
