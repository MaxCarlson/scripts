from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_scripts_llm_monitor_source_copy_is_retired():
    tracked = subprocess.run(
        ["git", "ls-files", "--", "modules/llm_monitor"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert tracked
    assert not any(Path(path).suffix == ".py" for path in tracked)
    assert not any(Path(path).name == "pyproject.toml" for path in tracked)
    assert not any(path.startswith("modules/llm_monitor/llm_monitor/") for path in tracked)
    assert not any(path.startswith("modules/llm_monitor/tests/") for path in tracked)
    assert not any(path.startswith("modules/llm_monitor/llm_monitor/web_static/") for path in tracked)

    exceptions = json.loads(
        (REPO_ROOT / ".github" / "source-ownership-exceptions.json").read_text(encoding="utf-8")
    )
    assert any(
        item.get("type") == "retirement" and item.get("path") == "modules/llm_monitor"
        for item in exceptions
    )
