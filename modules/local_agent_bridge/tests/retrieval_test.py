"""Offline contracts for bounded source retrieval and the additive CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from local_agent_bridge.commands import build_parser, main
from local_agent_bridge.retrieval import core
from local_agent_bridge.retrieval import context, locate, search


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "sample repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "café module.py").write_text(
        "def greeting():\n    return 'hello needle'\n\nTOKEN = 'second'\n", encoding="utf-8"
    )
    (root / "tracked.md").write_text("needle in tracked file\n", encoding="utf-8")
    (root / "ignored.txt").write_text("needle must stay ignored\n", encoding="utf-8")
    (root / "untracked.py").write_text("needle in untracked file\n", encoding="utf-8")
    _git(root, "add", ".gitignore", "src/café module.py", "tracked.md")
    return root


def test_locate_is_git_aware_deterministic_and_supports_explicit_untracked(repo):
    found = locate(repo)
    assert found["discovery"] == "git"
    paths = [item["path"] for item in found["results"]]
    assert paths == [".gitignore", "src/café module.py", "tracked.md", "untracked.py"]
    assert "ignored.txt" not in paths

    explicit = locate(repo, paths=["ignored.txt"])
    assert explicit["results"] == [{"path": "ignored.txt"}]


def test_search_returns_exact_unicode_path_line_and_literal_or_regex_results(repo):
    literal = search(repo, "needle", paths=["src/café module.py"])
    assert literal["results"] == [
        {"path": "src/café module.py", "line": 2, "text": "    return 'hello needle'", "line_truncated": False}
    ]
    regex = search(repo, r"TOKEN\s*=", regex=True, paths=["src/café module.py"])
    assert [(item["path"], item["line"]) for item in regex["results"]] == [
        ("src/café module.py", 4)
    ]


def test_search_empty_results_are_explicit(repo):
    result = search(repo, "does-not-exist")
    assert result["results"] == []
    assert result["truncated"] is False
    assert result["errors"] == []


def test_search_bounds_result_count_and_serialized_output(repo):
    (repo / "many.txt").write_text("needle\n" * 80, encoding="utf-8")
    result = search(repo, "needle", paths=["many.txt"], limit=2, max_output_bytes=800)
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(result["results"]) == 2
    assert len(encoded) <= 800
    assert result["truncated"] is True


def test_context_returns_exact_line_provenance_and_continuation(repo):
    result = context(repo, "src/café module.py", 2, 3)
    assert result["results"] == [
        {"line": 2, "text": "    return 'hello needle'", "line_truncated": False},
        {"line": 3, "text": "", "line_truncated": False},
    ]
    assert result["path"] == "src/café module.py"
    assert result["next_line"] == 4
    assert result["truncated"] is False


@pytest.mark.parametrize(("start", "end"), [(0, 1), (3, 2), (1, 201)])
def test_context_rejects_invalid_or_over_limit_ranges(repo, start, end):
    with pytest.raises(ValueError):
        context(repo, "tracked.md", start, end, max_lines=200)


def test_binary_files_are_not_returned_as_search_matches(repo):
    (repo / "binary.dat").write_bytes(b"needle\x00binary\n")
    result = search(repo, "needle", paths=["binary.dat"])
    assert result["results"] == []
    assert result["errors"]
    assert result["errors"][0]["code"] == "binary_file"


def test_path_traversal_is_rejected(repo):
    with pytest.raises(ValueError, match="relative|workspace|unsafe"):
        context(repo, "../outside.txt", 1, 1)


def test_resolved_symlink_escape_is_rejected(repo, tmp_path, monkeypatch):

    link = repo / "escape.txt"
    link.write_text("inside placeholder\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == link:
            return outside
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="escapes the workspace"):
        context(repo, "escape.txt", 1, 1)


def test_missing_ripgrep_uses_bounded_standard_library_fallback(repo, monkeypatch):

    monkeypatch.setattr(core.shutil, "which", lambda _: None)
    result = core.search(repo, "needle", paths=["tracked.md"])
    assert result["engine"] == "python"
    assert result["results"][0]["line"] == 1


def test_json_payload_order_and_read_only_behavior_are_stable(repo):
    def snapshot() -> dict[str, bytes]:
        return {
            path.relative_to(repo).as_posix(): path.read_bytes()
            for path in repo.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(repo).parts
        }

    before = snapshot()
    first = search(repo, "needle")
    second = search(repo, "needle")
    assert first == second
    assert snapshot() == before


def test_code_cli_is_additive_and_keeps_existing_commands(repo, capsys):
    parser = build_parser()
    assert parser.parse_args(["setup", "status", "-j"]).group == "setup"
    assert parser.parse_args(["code", "search", "needle", "-C", str(repo), "-j"]).group == "code"

    assert main(["code", "search", "needle", "-C", str(repo), "-j"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["operation"] == "search"
    assert result["results"]


def test_nested_repositories_are_not_opened_as_source_files(repo):
    nested = repo / "nested"
    nested.mkdir()
    _git(nested, "init", "-q")
    (nested / "private.py").write_text("nested value\n", encoding="utf-8")
    result = locate(repo)
    assert all(not item["path"].startswith("nested/") for item in result["results"])


def test_match_lines_are_byte_bounded_and_marked_truncated(repo):
    long_line = "start " + ("x" * 200) + " needle end"
    (repo / "long.txt").write_text(long_line + "\n", encoding="utf-8")
    result = search(repo, "needle", paths=["long.txt"], max_line_bytes=32)
    match = result["results"][0]
    assert len(match["text"].encode("utf-8")) <= 32
    assert match["line_truncated"] is True


def test_cli_invalid_path_returns_structured_json_error(repo, capsys):
    assert main(["code", "context", "../outside.txt", "1", "2", "-C", str(repo), "-j"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_request"


def test_literal_pattern_is_not_treated_as_an_option(repo):
    (repo / "flags.txt").write_text("--hidden is ordinary source text\n", encoding="utf-8")
    result = search(repo, "--hidden", paths=["flags.txt"])
    assert result["results"][0]["text"] == "--hidden is ordinary source text"


def test_context_keeps_physical_line_numbers_after_clipping_long_lines(repo):
    (repo / "long-lines.txt").write_text(("x" * 200) + "\nsecond\n", encoding="utf-8")
    result = context(repo, "long-lines.txt", 1, 2, max_line_bytes=32)
    assert result["results"] == [
        {"line": 1, "text": "x" * 29 + "…", "line_truncated": True},
        {"line": 2, "text": "second", "line_truncated": False},
    ]
    assert result["next_line"] == 3


def test_missing_git_uses_explicit_filesystem_discovery(repo, monkeypatch):

    original_which = core.shutil.which
    monkeypatch.setattr(core.shutil, "which", lambda name: None if name == "git" else original_which(name))
    result = core.locate(repo)
    assert result["discovery"] == "filesystem"
    assert "ignored.txt" in [item["path"] for item in result["results"]]


def test_oversized_files_are_skipped_with_truncation_state(repo):
    from local_agent_bridge.retrieval.core import MAX_FILE_BYTES

    large = repo / "large.txt"
    large.write_bytes((b"x" * MAX_FILE_BYTES) + b"needle\n")
    result = search(repo, "needle", paths=["large.txt"])
    assert result["results"] == []
    assert result["truncated"] is True
    assert result["errors"][0]["code"] == "file_too_large"


def test_context_obeys_serialized_output_byte_budget(repo):
    path = repo / "many-lines.txt"
    path.write_text("x" * 60 + "\n", encoding="utf-8")
    path.write_text(path.read_text(encoding="utf-8") * 30, encoding="utf-8")
    result = context(repo, "many-lines.txt", 1, 30, max_output_bytes=700)
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) <= 700
    assert result["truncated"] is True
    assert result["next_line"] < 31
