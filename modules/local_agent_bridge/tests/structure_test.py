from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_agent_bridge.retrieval import repository_map, symbols


def test_symbols_returns_compact_ast_outline_and_source_provenance(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "sample.py"
    source.write_text(
        "import pathlib as pl\n\nclass Worker:\n    def run(self, value: int = 1) -> int:\n        return value\n\ndef helper():\n    return Worker()\n",
        encoding="utf-8",
    )
    result = symbols(root, "sample.py")
    assert result["operation"] == "symbols"
    assert result["engine"] == "python-ast"
    assert result["results"][0]["sha256"]
    outline = result["results"][0]["symbols"]
    assert [(item["kind"], item["qualified_name"], item["start_line"], item["end_line"])
            for item in outline] == [
        ("import", "pathlib", 1, 1),
        ("class", "Worker", 3, 5),
        ("method", "Worker.run", 4, 5),
        ("function", "helper", 7, 8),
    ]
    assert outline[2]["signature"] == "def run(self, value: int = 1) -> int:"


def test_repository_map_ranks_relevant_symbols_and_respects_output_budget(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "auth.py").write_text(
        "def create_session(token):\n    return token\n\ndef unrelated():\n    pass\n",
        encoding="utf-8",
    )
    (root / "billing.py").write_text("def charge_card(number):\n    return number\n", encoding="utf-8")
    result = repository_map(root, "create session authentication", max_files=20, max_results=20,
                            max_output_bytes=1800)
    assert result["status"] == "ok"
    assert result["results"][0]["qualified_name"] == "create_session"
    assert result["results"][0]["path"] == "auth.py"
    assert all(item["sha256"] for item in result["results"])
    assert len(json.dumps(result, separators=(",", ":")).encode()) <= 1800


def test_structure_reports_syntax_and_binary_errors_explicitly(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (root / "binary.py").write_bytes(b"value = 1\x00\xff")
    result = symbols(root, "broken.py")
    assert result["status"] == "partial"
    assert result["errors"][0]["code"] == "syntax_error"
    binary = symbols(root, "binary.py")
    assert binary["errors"][0]["code"] == "binary_file"


def test_repository_map_is_fresh_bounded_and_git_aware(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (root / "tracked.py").write_text("def old_name():\n    pass\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", ".gitignore", "tracked.py"], cwd=root, check=True)
    (root / "ignored.py").write_text("def hidden():\n    pass\n", encoding="utf-8")
    first = repository_map(root, "old name")
    assert first["discovery"] == "git"
    assert [item["path"] for item in first["results"]] == ["tracked.py"]
    (root / "tracked.py").write_text("def new_name():\n    pass\n", encoding="utf-8")
    second = repository_map(root, "new name")
    assert second["results"][0]["qualified_name"] == "new_name"
    assert second["results"][0]["sha256"] != first["results"][0]["sha256"]


@pytest.mark.parametrize("path", ["../outside.py", "C:\\outside.py", "/outside.py"])
def test_symbols_rejects_unsafe_paths(tmp_path: Path, path: str):
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(ValueError):
        symbols(root, path)


def test_code_cli_exposes_symbols_and_ranked_map_as_json(tmp_path: Path, capsys):
    from local_agent_bridge.commands import main

    root = tmp_path / "repo"
    root.mkdir()
    (root / "worker.py").write_text("def resume_session(session_id):\n    return session_id\n", encoding="utf-8")
    assert main(["code", "symbols", "worker.py", "-C", str(root), "-j"]) == 0
    symbols_result = json.loads(capsys.readouterr().out)
    assert symbols_result["results"][0]["symbols"][0]["qualified_name"] == "resume_session"
    assert main(["code", "map", "resume session", "-C", str(root), "-t", "1800", "-j"]) == 0
    map_result = json.loads(capsys.readouterr().out)
    assert map_result["results"][0]["qualified_name"] == "resume_session"
    assert map_result["token_upper_bound"] <= 1800


def test_map_filters_git_paths_before_resolving_non_python_entries(tmp_path: Path, monkeypatch):
    from local_agent_bridge.retrieval import core

    root = tmp_path / "repo"
    root.mkdir()
    (root / "namespace.py").mkdir()
    (root / "worker.py").write_text("def run_task():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(core, "_git_paths", lambda *_args, **_kwargs: (["namespace.py", "worker.py"], False, True))
    result = repository_map(root, "run task")
    assert [item["path"] for item in result["results"]] == ["worker.py"]



def test_symbols_truncate_inside_large_outline_without_dropping_provenance(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "many.py").write_text("\n".join(f"def function_{index}():\n    return {index}" for index in range(100)), encoding="utf-8")
    result = symbols(root, "many.py", max_output_bytes=1024)
    assert len(json.dumps(result, separators=(",", ":")).encode()) <= 1024
    assert result["results"]
    assert result["results"][0]["path"] == "many.py"
    assert result["results"][0]["symbols_truncated"] is True


def test_symbols_report_per_file_symbol_cap_truncation(tmp_path: Path):
    from local_agent_bridge.retrieval.structure import MAX_SYMBOLS_PER_FILE

    root = tmp_path / "repo"
    root.mkdir()
    source = root / "many.py"
    source.write_text(
        "\n".join(f"def function_{index}():\n    return {index}" for index in range(MAX_SYMBOLS_PER_FILE + 1)),
        encoding="utf-8",
    )

    result = symbols(root, "many.py", max_output_bytes=1024 * 1024)

    assert result["results"][0]["symbol_count"] == MAX_SYMBOLS_PER_FILE
    assert result["results"][0]["symbols_truncated"] is True
    assert result["truncated"] is True


def test_repository_map_propagates_per_file_symbol_cap_truncation(tmp_path: Path):
    from local_agent_bridge.retrieval.structure import MAX_SYMBOLS_PER_FILE

    root = tmp_path / "repo"
    root.mkdir()
    source = root / "many.py"
    source.write_text(
        "\n".join(f"def unrelated_{index}():\n    pass" for index in range(MAX_SYMBOLS_PER_FILE))
        + "\ndef target_checkpoint():\n    pass\n",
        encoding="utf-8",
    )

    result = repository_map(root, "target checkpoint", max_results=80)

    assert result["results"] == []
    assert result["truncated"] is True
    assert result["status"] == "partial"


def test_map_prioritizes_task_relevant_paths_within_file_limit(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a_unrelated.py").write_text("def generic_handler():\n    pass\n", encoding="utf-8")
    (root / "z_checkpoint.py").write_text("def recover_checkpoint():\n    pass\n", encoding="utf-8")
    result = repository_map(root, "checkpoint recovery", max_files=1, max_results=10)
    assert result["truncated"] is True
    assert result["results"]
    assert result["results"][0]["path"] == "z_checkpoint.py"
