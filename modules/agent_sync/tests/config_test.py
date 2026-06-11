from pathlib import Path

from agent_sync.config import default_config, load_config, save_config


def test_default_config_contains_local_worker() -> None:
    config = default_config()
    names = config.worker_names()
    assert "local-lmstudio" in names
    assert config.get_worker("local-lmstudio").kind == "local"


def test_config_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "workers.json"
    config = default_config()
    save_config(config, path)
    loaded = load_config(path)
    assert loaded.default_worker == config.default_worker
    assert loaded.worker_names() == config.worker_names()
