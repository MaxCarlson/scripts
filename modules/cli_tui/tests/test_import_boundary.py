from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_schema_import_does_not_load_terminal_or_image_modules():
    code = """
import sys
import importlib
from cli_tui.schema import CliCommand
from cli_tui import CliArgument
NestedCliCommand = importlib.import_module('cli_tui.cli_tui.schema').CliCommand
assert CliCommand.__name__ == 'CliCommand'
assert NestedCliCommand is CliCommand
assert CliArgument.__name__ == 'CliArgument'
assert 'cli_tui.app' not in sys.modules
assert 'cli_tui.image_viewer' not in sys.modules
assert 'curses' not in sys.modules
assert 'PIL' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [str(Path(__file__).resolve().parents[2]), os.environ.get("PYTHONPATH", "")]
            ),
        },
    )

    assert result.returncode == 0, result.stderr
