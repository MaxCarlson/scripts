from pathlib import Path

from resource_coordinator.config import build_system, load_config


def test_load_default_config():
    cfg = load_config(None)
    assert cfg.version == "1.0"
    assert cfg.service.listen_host == "127.0.0.1"
    assert cfg.service.listen_port == 1235
    assert "krig" in cfg.processes
    assert len(cfg.policies) >= 1


def test_load_custom_yaml(tmp_path: Path):
    yaml_content = """
version: "1.0"
service:
  listen_host: "0.0.0.0"
  listen_port: 8080
  upstream_url: "http://127.0.0.1:1234"
processes:
  test_proc:
    backend: "fake"
    executable: "/bin/test"
    stop_timeout_seconds: 5.0
policies:
  - name: test_policy
    trigger_event: "test.trigger"
    target_process: "test_proc"
    resource: "test.resource"
    cooldown_seconds: 15.0
"""
    cfg_file = tmp_path / "coordinator.yaml"
    cfg_file.write_text(yaml_content, encoding="utf-8")

    cfg = load_config(cfg_file)
    assert cfg.service.listen_host == "0.0.0.0"
    assert cfg.service.listen_port == 8080
    assert "test_proc" in cfg.processes
    assert cfg.policies[0].name == "test_policy"
    assert cfg.policies[0].cooldown_seconds == 15.0


def test_build_system_from_config():
    cfg = load_config(None)
    system = build_system(cfg, use_fake_processes=True)
    assert "krig" in system.supervisors
    assert system.miner_adapter is not None
    assert system.gateway.upstream_url == "http://127.0.0.1:1234"
