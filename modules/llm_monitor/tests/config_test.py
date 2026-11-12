"""Tests for llm_monitor.config persistent configuration loading and resolution."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from llm_monitor.config import (
    default_config_dir,
    find_config_file,
    get_web_config,
    load_user_config,
    resolve_web_options,
)


def test_default_config_dir_windows(monkeypatch):
    environ = {"LOCALAPPDATA": r"C:\Users\test\AppData\Local"}
    cfg_dir = default_config_dir(platform="win32", environ=environ)
    assert cfg_dir == Path(r"C:\Users\test\AppData\Local\llm-monitor")


def test_default_config_dir_posix(monkeypatch):
    environ = {"HOME": "/home/test", "XDG_CONFIG_HOME": "/home/test/.custom_config"}
    cfg_dir = default_config_dir(platform="linux", environ=environ)
    assert cfg_dir == Path("/home/test/.custom_config/llm-monitor")


def test_default_config_dir_darwin(monkeypatch):
    environ = {"HOME": "/Users/test"}
    cfg_dir = default_config_dir(platform="darwin", environ=environ)
    assert cfg_dir == Path("/Users/test/Library/Application Support/llm-monitor")


def test_find_config_file_prefers_toml_over_json(tmp_path):
    config_dir = tmp_path / "llm-monitor"
    config_dir.mkdir(parents=True)
    toml_file = config_dir / "config.toml"
    json_file = config_dir / "config.json"
    toml_file.write_text("[web]\nport = 8788\n", encoding="utf-8")
    json_file.write_text('{"web": {"port": 8789}}', encoding="utf-8")

    found = find_config_file(platform="win32", environ={"LOCALAPPDATA": str(tmp_path)})
    assert found == toml_file


def test_find_config_file_json_when_toml_missing(tmp_path):
    config_dir = tmp_path / "llm-monitor"
    config_dir.mkdir(parents=True)
    json_file = config_dir / "config.json"
    json_file.write_text('{"web": {"port": 8789}}', encoding="utf-8")

    found = find_config_file(platform="win32", environ={"LOCALAPPDATA": str(tmp_path)})
    assert found == json_file


def test_find_config_file_env_override(tmp_path):
    custom_file = tmp_path / "custom.toml"
    custom_file.write_text("[web]\nport = 9000\n", encoding="utf-8")

    found = find_config_file(environ={"LLM_MONITOR_CONFIG": str(custom_file)})
    assert found == custom_file


def test_find_config_file_missing_returns_none(tmp_path):
    found = find_config_file(platform="win32", environ={"LOCALAPPDATA": str(tmp_path)})
    assert found is None


def test_load_user_config_toml(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[web]
port = 8788
endpoint = "http://127.0.0.1:1234"
gateway = true
gateway_upstream = "http://127.0.0.1:1235"
record_inferences = "metadata"
no_browser = true
""",
        encoding="utf-8",
    )
    data = load_user_config(config_file)
    assert data["web"]["port"] == 8788
    assert data["web"]["gateway"] is True
    assert data["web"]["gateway_upstream"] == "http://127.0.0.1:1235"
    assert data["web"]["record_inferences"] == "metadata"
    assert data["web"]["no_browser"] is True


def test_load_user_config_json(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({
            "web": {
                "port": 8788,
                "gateway": True,
                "gateway_upstream": "http://127.0.0.1:1235",
                "record_inferences": "metadata",
                "browser": False,
            }
        }),
        encoding="utf-8",
    )
    data = load_user_config(config_file)
    web_cfg = get_web_config(data)
    assert web_cfg["port"] == 8788
    assert web_cfg["gateway"] is True
    assert web_cfg["no_browser"] is True


def test_get_web_config_validation():
    invalid_port = {"web": {"port": 70000}}
    with pytest.raises(ValueError, match="port"):
        get_web_config(invalid_port)

    invalid_mode = {"web": {"record_inferences": "everything"}}
    with pytest.raises(ValueError, match="record_inferences"):
        get_web_config(invalid_mode)


def test_resolve_web_options_cli_precedence():
    user_config = {
        "port": 8788,
        "endpoint": "http://127.0.0.1:1234",
        "gateway": True,
        "gateway_upstream": "http://127.0.0.1:1235",
        "record_inferences": "metadata",
        "no_browser": True,
    }

    # 1. User overrides via explicit CLI flags
    cli_args = Namespace(
        port=9999,
        endpoint=None,
        gateway=False,  # explicit --no-gateway
        gateway_upstream=None,
        record_inferences=None,
        no_browser=False,  # explicit --browser
        database=None,
        refresh_interval=None,
        gateway_timing=None,
    )
    resolved = resolve_web_options(cli_args, user_config)
    assert resolved["port"] == 9999
    assert resolved["gateway"] is False
    assert resolved["no_browser"] is False
    # If gateway is explicitly disabled, config record_inferences is suppressed
    assert resolved["record_inferences"] is None

    # 2. User explicitly disables recording via CLI
    cli_args_rec = Namespace(
        port=None,
        endpoint=None,
        gateway=True,
        gateway_upstream=None,
        record_inferences="none",  # explicit --no-record-inferences
        no_browser=None,
        database=None,
        refresh_interval=None,
        gateway_timing=None,
    )
    resolved_rec = resolve_web_options(cli_args_rec, user_config)
    assert resolved_rec["port"] == 8788
    assert resolved_rec["gateway"] is True
    assert resolved_rec["gateway_upstream"] == "http://127.0.0.1:1235"
    assert resolved_rec["record_inferences"] is None


def test_resolve_web_options_without_config_uses_builtin_defaults():
    # No user config, empty CLI args
    cli_args = Namespace(
        port=None,
        endpoint=None,
        gateway=None,
        gateway_upstream=None,
        record_inferences=None,
        no_browser=None,
        database=None,
        refresh_interval=None,
        gateway_timing=None,
    )
    resolved = resolve_web_options(cli_args, {})
    assert resolved["port"] == 8788
    assert resolved["endpoint"] == "http://127.0.0.1:1234"
    assert resolved["gateway"] is False
    assert resolved["gateway_upstream"] == "http://127.0.0.1:1234"
    assert resolved["record_inferences"] is None
    assert resolved["no_browser"] is False
    assert resolved["database"] is None
    assert resolved["refresh_interval"] == 2.0
    assert resolved["gateway_timing"] is False
