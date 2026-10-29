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


def test_web_stop_and_status_options_parsed() -> None:
    # Short and long stop
    args_stop_short = build_parser().parse_args(["web", "-x"])
    assert args_stop_short.stop is True
    assert args_stop_short.status is False

    args_stop_long = build_parser().parse_args(["web", "--stop"])
    assert args_stop_long.stop is True
    assert args_stop_long.status is False

    # Short and long status
    args_status_short = build_parser().parse_args(["web", "-S"])
    assert args_status_short.status is True
    assert args_status_short.stop is False

    args_status_long = build_parser().parse_args(["web", "--status"])
    assert args_status_long.status is True
    assert args_status_long.stop is False


def test_web_stop_and_status_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["web", "--stop", "--status"])

    with pytest.raises(SystemExit):
        build_parser().parse_args(["web", "-x", "-S"])


def test_web_cli_dispatches_to_stop_server(tmp_path: Path, monkeypatch) -> None:
    import runmux.server_lifecycle as lifecycle_module

    stop_called = []

    def fake_stop(state_dir, port=None, host="127.0.0.1", timeout=5.0):
        stop_called.append((state_dir, port, host))
        return 0

    monkeypatch.setattr(lifecycle_module, "stop_server", fake_stop)

    args = build_parser().parse_args(["web", "--state-dir", str(tmp_path), "-p", "8888", "--stop"])
    assert handle_web(args) == 0
    assert stop_called == [(tmp_path, 8888, "127.0.0.1")]


def test_web_cli_dispatches_to_status_server(tmp_path: Path, monkeypatch) -> None:
    import runmux.server_lifecycle as lifecycle_module

    status_called = []

    def fake_status(state_dir, port=None, host="127.0.0.1"):
        status_called.append((state_dir, port, host))
        return 0

    monkeypatch.setattr(lifecycle_module, "status_server", fake_status)

    args = build_parser().parse_args(["web", "--state-dir", str(tmp_path), "--status"])
    assert handle_web(args) == 0
    assert status_called == [(tmp_path, None, "127.0.0.1")]


def test_web_cli_dispatches_to_run_web_server(tmp_path: Path, monkeypatch) -> None:
    import runmux.server_lifecycle as lifecycle_module

    run_called = []

    def fake_run(state_dir, host="127.0.0.1", port=8787, no_telemetry_history=False):
        run_called.append((state_dir, host, port, no_telemetry_history))
        return 0

    monkeypatch.setattr(lifecycle_module, "run_web_server", fake_run)

    args = build_parser().parse_args(["web", "--state-dir", str(tmp_path), "-p", "8900", "--no-telemetry-history"])
    assert handle_web(args) == 0
    assert run_called == [(tmp_path, "127.0.0.1", 8900, True)]


def test_web_json_flag_parsed() -> None:
    args_json = build_parser().parse_args(["web", "--status", "-j"])
    assert args_json.status is True
    assert args_json.json is True

    args_json_long = build_parser().parse_args(["web", "--stop", "--json"])
    assert args_json_long.stop is True
    assert args_json_long.json is True


def test_web_cli_dispatches_status_with_json(tmp_path: Path, monkeypatch) -> None:
    import runmux.server_lifecycle as lifecycle_module

    status_called = []

    def fake_status(state_dir, port=None, host="127.0.0.1", as_json=False):
        status_called.append((state_dir, port, host, as_json))
        return 0

    monkeypatch.setattr(lifecycle_module, "status_server", fake_status)

    args = build_parser().parse_args(["web", "--state-dir", str(tmp_path), "--status", "--json"])
    assert handle_web(args) == 0
    assert status_called == [(tmp_path, None, "127.0.0.1", True)]


def test_web_cli_dispatches_stop_with_json(tmp_path: Path, monkeypatch) -> None:
    import runmux.server_lifecycle as lifecycle_module

    stop_called = []

    def fake_stop(state_dir, port=None, host="127.0.0.1", as_json=False):
        stop_called.append((state_dir, port, host, as_json))
        return 0

    monkeypatch.setattr(lifecycle_module, "stop_server", fake_stop)

    args = build_parser().parse_args(["web", "--state-dir", str(tmp_path), "--stop", "-j"])
    assert handle_web(args) == 0
    assert stop_called == [(tmp_path, None, "127.0.0.1", True)]
