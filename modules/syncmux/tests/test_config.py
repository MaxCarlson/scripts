"""Tests for the config module."""

import pathlib
import tempfile

import pytest
import yaml

from syncmux.config import default_config_path, load_config
from syncmux.models import Host


def test_load_config_missing_file():
    """Test that loading a non-existent config file raises an error."""
    # Use a path that definitely doesn't exist
    non_existent = pathlib.Path("/tmp/definitely_does_not_exist_syncmux_test.yml")
    with pytest.raises(FileNotFoundError):
        load_config(non_existent)


def test_load_config_valid():
    """Test loading a valid config file."""
    config_data = {
        "hosts": [
            {
                "alias": "test-host",
                "hostname": "localhost",
                "user": "testuser",
                "auth_method": "agent",
            }
        ]
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.safe_dump(config_data, f)
        config_path = pathlib.Path(f.name)

    try:
        hosts = load_config(config_path)
        assert len(hosts) == 1
        assert hosts[0].alias == "test-host"
        assert hosts[0].hostname == "localhost"
        assert hosts[0].user == "testuser"
        assert hosts[0].auth_method == "agent"
    finally:
        config_path.unlink()


def test_default_config_path():
    """Test that default_config_path returns a valid Path object."""
    path = default_config_path()
    assert isinstance(path, pathlib.Path)
    assert path.name == "config.yml"
    assert "syncmux" in str(path)
