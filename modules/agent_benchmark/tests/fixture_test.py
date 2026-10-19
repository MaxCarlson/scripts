"""Tests for the original py-grep-smoke task fixture and coordinator verifier."""

import json
from pathlib import Path
import subprocess
import sys
import pytest

MODULE_ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = MODULE_ROOT / "agent_benchmark" / "tasks" / "py-grep-smoke"
MANIFEST_PATH = TASK_DIR / "task.json"
INSTRUCTION_PATH = TASK_DIR / "instruction.md"
SEED_PATH = TASK_DIR / "seed" / "grep.py"
VERIFIER_PATH = TASK_DIR / "verifier" / "check.py"


def _run_verifier(verifier_path: Path, workspace_path: Path | str, timeout: float = 5.0) -> subprocess.CompletedProcess:
    """Run the verifier as a separate process with bounded timeout."""
    return subprocess.run(
        [sys.executable, str(verifier_path), str(workspace_path)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_manifest_structure_and_relative_paths():
    """Verify task.json exists, has required fields, and contains only valid relative paths."""
    assert MANIFEST_PATH.is_file(), f"Manifest missing at {MANIFEST_PATH}"

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Required fields per plan specification
    required_fields = {
        "task_id",
        "suite_version",
        "category",
        "allowed_paths",
        "forbidden_paths",
        "time_budget_seconds",
        "verifier",
    }
    assert required_fields.issubset(data.keys()), f"Missing fields: {required_fields - set(data.keys())}"

    assert data["task_id"] == "py-grep-smoke"
    assert data["suite_version"] == "0.1.0"
    assert data["category"] == "smoke"
    assert data["time_budget_seconds"] == 60
    assert data["allowed_paths"] == ["grep.py"]
    assert isinstance(data["forbidden_paths"], list)
    assert len(data["forbidden_paths"]) > 0

    # Verify paths are relative, without ".." or leading separators
    all_paths = data["allowed_paths"] + data["forbidden_paths"] + [data["verifier"]]
    for path_str in all_paths:
        p = Path(path_str)
        assert not p.is_absolute(), f"Path must not be absolute: {path_str}"
        assert ".." not in p.parts, f"Path must not contain '..': {path_str}"

    # Verify referenced verifier and seed files exist on disk
    assert (TASK_DIR / data["verifier"]).is_file()
    assert INSTRUCTION_PATH.is_file()
    assert SEED_PATH.is_file()


def test_seed_implementation_fails_verifier(tmp_path):
    """Seed deliberately raises NotImplementedError; verifier must exit 1 (incorrect implementation)."""
    workspace = tmp_path / "seed_workspace"
    workspace.mkdir()
    (workspace / "grep.py").write_text(SEED_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    result = _run_verifier(VERIFIER_PATH, workspace)
    assert result.returncode == 1, f"Seed must exit 1, got {result.returncode}. Stderr: {result.stderr}"


def test_known_good_solution_passes_verifier(tmp_path):
    """A known-good substring grep implementation must exit 0."""
    workspace = tmp_path / "good_workspace"
    workspace.mkdir()

    code = (
        "def grep(pattern: str, lines: list[str], ignore_case: bool = False) -> list[str]:\n"
        "    if ignore_case:\n"
        "        p = pattern.lower()\n"
        "        return [line for line in lines if p in line.lower()]\n"
        "    return [line for line in lines if pattern in line]\n"
    )
    (workspace / "grep.py").write_text(code, encoding="utf-8")

    result = _run_verifier(VERIFIER_PATH, workspace)
    assert result.returncode == 0, f"Known-good solution must exit 0. Stderr: {result.stderr}"


def test_verifier_infrastructure_failures(tmp_path):
    """Verifier must exit 2 when given invalid arguments or non-existent workspace."""
    # Missing argument
    res_no_arg = subprocess.run(
        [sys.executable, str(VERIFIER_PATH)],
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    assert res_no_arg.returncode == 2

    # Non-existent workspace
    res_non_existent = _run_verifier(VERIFIER_PATH, tmp_path / "does_not_exist")
    assert res_non_existent.returncode == 2

    # Workspace path is a file, not a directory
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("hello", encoding="utf-8")
    res_file = _run_verifier(VERIFIER_PATH, file_path)
    assert res_file.returncode == 2


@pytest.mark.parametrize(
    "bad_code, expected_reason",
    [
        (
            "# Missing grep function\ndef other(): pass\n",
            "missing function",
        ),
        (
            "# Regex instead of literal substring\nimport re\n"
            "def grep(pattern: str, lines: list[str], ignore_case: bool = False) -> list[str]:\n"
            "    flags = re.IGNORECASE if ignore_case else 0\n"
            "    return [l for l in lines if re.search(pattern, l, flags)]\n",
            "regex interpretation",
        ),
        (
            "# Sets dropping duplicates and order\n"
            "def grep(pattern: str, lines: list[str], ignore_case: bool = False) -> list[str]:\n"
            "    return list({l for l in lines if pattern in l})\n",
            "dropped duplicates or order",
        ),
        (
            "# Mutating line casing\n"
            "def grep(pattern: str, lines: list[str], ignore_case: bool = False) -> list[str]:\n"
            "    p = pattern.lower() if ignore_case else pattern\n"
            "    return [l.lower() for l in lines if p in (l.lower() if ignore_case else l)]\n",
            "mutated casing",
        ),
        (
            "# Syntax error\ndef grep(: pass\n",
            "syntax error",
        ),
    ],
)
def test_bad_implementations_fail_with_exit_1(tmp_path, bad_code, expected_reason):
    """Incorrect implementations must fail with exit code 1."""
    workspace = tmp_path / "bad_workspace"
    workspace.mkdir()
    (workspace / "grep.py").write_text(bad_code, encoding="utf-8")

    result = _run_verifier(VERIFIER_PATH, workspace)
    assert result.returncode == 1, (
        f"Failed to reject implementation with {expected_reason}: "
        f"exit code {result.returncode}, stdout: {result.stdout}, stderr: {result.stderr}"
    )


def test_missing_grep_file_fails_with_exit_1(tmp_path):
    """An empty workspace missing grep.py represents an incomplete/incorrect implementation (exit 1)."""
    workspace = tmp_path / "empty_workspace"
    workspace.mkdir()

    result = _run_verifier(VERIFIER_PATH, workspace)
    assert result.returncode == 1


def test_verifier_timeout_distinguished_from_exit_codes(tmp_path):
    """An infinite loop in worker code triggers a subprocess timeout, distinguished from exit 0/1/2."""
    workspace = tmp_path / "hang_workspace"
    workspace.mkdir()

    code = (
        "import time\n"
        "def grep(pattern: str, lines: list[str], ignore_case: bool = False) -> list[str]:\n"
        "    while True:\n"
        "        time.sleep(0.1)\n"
    )
    (workspace / "grep.py").write_text(code, encoding="utf-8")

    with pytest.raises(subprocess.TimeoutExpired):
        _run_verifier(VERIFIER_PATH, workspace, timeout=0.5)
