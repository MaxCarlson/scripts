
import os
import tempfile

import pytest
import yaml

from syncmux.config import load_config, CONFIG_PATH
from syncmux.models import Host


@pytest.fixture
def temp_config_file():
    config_data = {
        "hosts": [
            {
                "alias": "test1",
                "hostname": "localhost",
                "user": "testuser1",
                "auth_method": "agent",
            },
            {
                "alias": "test2",
                "hostname": "192.168.1.1",
                "user": "testuser2",
                "auth_method": "password",
                "password": "testpassword",
            },
        ]
    }
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        yaml.dump(config_data, f)
        yield f.name
    os.unlink(f.name)


def test_load_config(monkeypatch, temp_config_file):
    from pathlib import Path
    monkeypatch.setattr("syncmux.config.CONFIG_PATH", Path(temp_config_file))
    hosts = load_config()
    assert len(hosts) == 2
    assert isinstance(hosts[0], Host)
    assert hosts[0].alias == "test1"
    assert hosts[1].password == "testpassword"


def test_load_config_not_found(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr("syncmux.config.CONFIG_PATH", Path("/tmp/nonexistentfile"))
    with pytest.raises(FileNotFoundError):
        load_config()
