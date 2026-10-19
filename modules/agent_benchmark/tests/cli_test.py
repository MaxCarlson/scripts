"""CLI authorization, preview and independent process behavior."""

import subprocess
import sys

from agent_benchmark.cli import main


def test_run_requires_execute_before_writing_any_files(tmp_path, capsys):
    assert main(["run", "-m", "test", "-o", str(tmp_path / "reports"), "-s", str(tmp_path / "state")]) != 0
    assert not (tmp_path / "reports").exists()
    assert not (tmp_path / "state").exists()
    assert "execute" in capsys.readouterr().err.lower()


def test_plan_and_status_are_read_only(tmp_path, capsys):
    state = tmp_path / "state"
    assert main(["plan", "-s", str(state)]) == 0
    assert "py-grep-smoke" in capsys.readouterr().out
    assert main(["status", "-s", str(state)]) == 0
    assert not state.exists()


def test_module_cli_from_another_directory_and_bundled_fixture(tmp_path):
    result = subprocess.run([sys.executable, "-m", "agent_benchmark", "plan", "-s", str(tmp_path / "state")],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "py-grep-smoke" in result.stdout
    assert not (tmp_path / "state").exists()


def test_cleanup_is_preview_without_execute(tmp_path, capsys):
    assert main(["cleanup", "-s", str(tmp_path / "state")]) == 0
    assert not (tmp_path / "state").exists()


def test_modules_first_keeps_cli_and_version_importable():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    script = "import sys; sys.path.insert(0, 'modules'); from agent_benchmark.cli import main; from agent_benchmark import __version__; assert isinstance(__version__, str) and __version__; main(['plan'])"
    result = subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
