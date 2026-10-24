import argparse
import sys
from pathlib import Path

import pytest

from runmux.cli import build_parser, handle_web, port_number


def test_web_subcommand_keeps_short_and_long_option_forms(tmp_path: Path) -> None:
    args = build_parser().parse_args(["web", "-H", "127.0.0.1", "-p", "8765", "-s", str(tmp_path)])
    assert args.command == "web"
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.state_dir == tmp_path

    long_args = build_parser().parse_args(["web", "--host", "::1", "--port", "8766", "--state-dir", str(tmp_path)])
    assert long_args.host == "::1"
    assert long_args.port == 8766


def test_port_number_rejects_invalid_ranges() -> None:
    assert port_number("1") == 1
    with pytest.raises(argparse.ArgumentTypeError, match="between 1 and 65535"):
        port_number("0")
    with pytest.raises(argparse.ArgumentTypeError, match="integer"):
        port_number("web")


def test_web_dependency_is_loaded_only_when_web_is_requested(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setitem(sys.modules, "web_ui_tools", None)
    args = build_parser().parse_args(["web", "--state-dir", str(tmp_path)])
    assert not (tmp_path / "registry.sqlite3").exists()
    assert handle_web(args) == 2
    assert "optional runmux web extra" in capsys.readouterr().err
    assert not (tmp_path / "registry.sqlite3").exists()
