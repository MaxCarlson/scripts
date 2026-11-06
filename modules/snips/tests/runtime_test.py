import os
import subprocess

import pytest

from snips.backend import find_autohotkey
from snips.config import default_config
from snips.runtime import generate_script, runtime_status


@pytest.mark.skipif(os.name != "nt", reason="AutoHotkey runtime validation requires Windows")
def test_generated_script_parses_and_registers_hotkeys_with_ahk_v2(tmp_path):
    executable, version = find_autohotkey()
    if executable is None:
        pytest.skip("AutoHotkey v2 is not installed")
    runtime = tmp_path / "snips-runtime"
    data = runtime / "data"
    script_text, build_id, _ = generate_script(default_config(), data, runtime / "status.txt")
    data.mkdir(parents=True)
    script = runtime / "test-dispatcher.ahk"
    script.write_text(script_text, encoding="utf-8", newline="")
    try:
        result = subprocess.run(
            [str(executable), "/ErrorStdOut=UTF-8", str(script), "/validate"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError as exc:
        if getattr(exc, "winerror", None) == 623:
            pytest.skip("Windows process sandbox denied GUI runtime launch (WinError 623)")
        raise
    assert result.returncode == 0, f"AutoHotkey v{version} rejected generated source: {result.stdout}\n{result.stderr}"
    status = (runtime / "status.txt").read_text(encoding="utf-8")
    assert status.startswith("running|")
    assert build_id in status


def test_runtime_status_parses_startup_error_detail(tmp_path):
    tmp_path.joinpath("status.txt").write_text("error|4321|build-id|hotkey registration failed", encoding="utf-8")
    status = runtime_status(tmp_path)
    assert status == {
        "running": False,
        "state": "error",
        "pid": 4321,
        "build_id": "build-id",
        "detail": "hotkey registration failed",
    }
