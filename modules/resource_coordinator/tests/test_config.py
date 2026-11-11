from pathlib import Path

import pytest

from resource_coordinator.config import CoordinatorConfig, build_system, load_config


def test_load_default_config():
    cfg = load_config(None)
    assert cfg.version == "1.0"
    assert cfg.service.listen_host == "127.0.0.1"
    assert cfg.service.listen_port == 1235
    assert cfg.service.model_load_timeout_seconds == 1800.0
    assert "krig" in cfg.processes
    assert len(cfg.policies) >= 1
    assert cfg.maintenance_verification.enabled is False


def test_load_custom_yaml(tmp_path: Path):
    yaml_content = """
version: "1.0"
service:
  listen_host: "0.0.0.0"
  listen_port: 8080
  upstream_url: "http://127.0.0.1:1234"
  model_load_timeout_seconds: 900
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
    assert cfg.service.model_load_timeout_seconds == 900.0
    assert "test_proc" in cfg.processes
    assert cfg.policies[0].name == "test_policy"
    assert cfg.policies[0].cooldown_seconds == 15.0


def test_maintenance_verification_config_is_disabled_by_default_and_validated():
    default = CoordinatorConfig.from_dict({})
    assert default.maintenance_verification.enabled is False

    configured = CoordinatorConfig.from_dict({
        "maintenance_verification": {
            "enabled": True,
            "gpu_uuid": "GPU-test",
            "allowed_dimensions": ["power_limit_mw", "graphics_clock_offset_mhz"],
            "known_miner_executables": ["krig.exe", "SRBMiner.exe"],
            "gpu_process_attribution_confirmed": True,
            "observation_timeout_seconds": 4.0,
            "max_observation_age_seconds": 20.0,
        }
    })
    assert configured.maintenance_verification.enabled is True
    assert configured.maintenance_verification.allowed_dimensions == [
        "power_limit_mw", "graphics_clock_offset_mhz"
    ]

    for invalid in (
        {"enabled": True},
        {"enabled": True, "gpu_uuid": 123, "allowed_dimensions": ["power_limit_mw"],
         "known_miner_executables": ["krig.exe"]},
        {"enabled": True, "gpu_uuid": "GPU-test", "allowed_dimensions": ["locked_clocks"],
         "known_miner_executables": ["krig.exe"]},
        {"enabled": True, "gpu_uuid": "GPU-test", "allowed_dimensions": ["power_limit_mw"],
         "known_miner_executables": ["C:\\miners\\krig.exe"]},
        {"enabled": True, "gpu_uuid": "GPU-test", "allowed_dimensions": ["power_limit_mw"],
         "known_miner_executables": ["krig.exe"], "observation_timeout_seconds": 31},
        {"enabled": True, "gpu_uuid": "GPU-test", "allowed_dimensions": ["power_limit_mw"],
         "known_miner_executables": ["krig.exe"], "gpu_process_attribution_confirmed": 1},
    ):
        with pytest.raises((TypeError, ValueError)):
            CoordinatorConfig.from_dict({"maintenance_verification": invalid})


def test_load_config_uses_managed_paths_only_when_config_omits_them(tmp_path: Path, monkeypatch):
    config_file = tmp_path / "coordinator.yaml"
    config_file.write_text(
        'version: "1.0"\nprocesses:\n  krig_miner:\n    backend: fake\n', encoding="utf-8"
    )
    monkeypatch.setenv("RESOURCE_COORDINATOR_STATE_PATH", str(tmp_path / "coordinator_state.json"))
    monkeypatch.setenv("RESOURCE_COORDINATOR_LOG_DIR", str(tmp_path / "logs"))

    config = load_config(config_file)

    assert config.service.state_persistence_path == str(tmp_path / "coordinator_state.json")
    assert config.processes["krig_miner"].stdout_log_path == str(tmp_path / "logs" / "krig_miner.log")


def test_load_config_preserves_explicit_persistent_paths_over_managed_defaults(tmp_path: Path, monkeypatch):
    config_file = tmp_path / "coordinator.yaml"
    config_file.write_text(
        'version: "1.0"\nservice:\n  state_persistence_path: explicit.json\nprocesses:\n'
        '  krig_miner:\n    backend: fake\n    stdout_log_path: explicit.log\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("RESOURCE_COORDINATOR_STATE_PATH", str(tmp_path / "default.json"))
    monkeypatch.setenv("RESOURCE_COORDINATOR_LOG_DIR", str(tmp_path / "logs"))

    config = load_config(config_file)

    assert config.service.state_persistence_path == "explicit.json"
    assert config.processes["krig_miner"].stdout_log_path == "explicit.log"


def test_build_system_from_config():
    cfg = load_config(None)
    system = build_system(cfg, use_fake_processes=True)
    assert "krig" in system.supervisors
    assert system.miner_adapter is not None
    assert system.gateway.upstream_url == "http://127.0.0.1:1234"
    assert system.gateway.model_load_timeout_seconds == 1800.0


def test_build_system_passes_configured_model_load_timeout_to_gateway():
    cfg = CoordinatorConfig.from_dict(
        {"version": "1.0", "service": {"model_load_timeout_seconds": 900}}
    )
    system = build_system(cfg, use_fake_processes=True)
    assert system.gateway.model_load_timeout_seconds == 900.0


def test_config_rejects_zero_idle_timeout_when_restart_is_enabled():
    data = {
        "version": "1.0",
        "processes": {"worker": {"backend": "fake"}},
        "policies": [
            {
                "name": "restart-worker",
                "trigger_event": "lmstudio.inference_requested",
                "target_process": "worker",
                "resource": "gpu.inference",
                "cooldown_seconds": 0,
            }
        ],
    }
    with pytest.raises(ValueError, match="positive idle timeout"):
        CoordinatorConfig.from_dict(data)


def test_config_rejects_restart_without_coordinator_stop_ownership():
    data = {
        "version": "1.0",
        "processes": {"worker": {"backend": "fake"}},
        "policies": [
            {
                "name": "restart-worker",
                "trigger_event": "lmstudio.inference_requested",
                "target_process": "worker",
                "resource": "gpu.inference",
                "only_if_stopped_by_coordinator": False,
            }
        ],
    }
    with pytest.raises(ValueError, match="coordinator-owned stop"):
        CoordinatorConfig.from_dict(data)


@pytest.mark.parametrize("timeout", [0, -1, 3600.1, float("inf"), float("nan")])
def test_config_rejects_invalid_model_load_timeout(timeout):
    with pytest.raises(ValueError, match="model_load_timeout_seconds"):
        CoordinatorConfig.from_dict({"version": "1.0", "service": {"model_load_timeout_seconds": timeout}})


def test_config_rejects_boolean_model_load_timeout():
    with pytest.raises(TypeError, match="model_load_timeout_seconds"):
        CoordinatorConfig.from_dict({"version": "1.0", "service": {"model_load_timeout_seconds": True}})
