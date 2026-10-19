"""
Configuration parser, validation, and system factory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway
from resource_coordinator.adapters.miners.adapter import MinerAdapter
from resource_coordinator.core.actions import StartProcessAction, StopProcessAction
from resource_coordinator.core.conditions import ProcessRunningCondition
from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.policies import Policy, PolicyEngine
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessSupervisor,
    WindowsProcessBackend,
)

logger = logging.getLogger(__name__)


@dataclass
class ServiceConfig:
    listen_host: str = "127.0.0.1"
    listen_port: int = 1235
    upstream_url: str = "http://127.0.0.1:1234"
    state_persistence_path: str = ""


@dataclass
class ProcessConfig:
    name: str
    backend: str = "windows"
    executable: str = ""
    arguments: List[str] = field(default_factory=list)
    working_directory: Optional[str] = None
    stop_timeout_seconds: float = 10.0
    restart_cooldown_seconds: float = 60.0
    new_console: bool = False
    adopt_external: bool = False


@dataclass
class PolicyConfig:
    name: str
    trigger_event: str
    target_process: Optional[str] = None
    stop_process: bool = True
    stop_timeout_seconds: float = 10.0
    resource: Optional[str] = None
    lease_type: str = "shared"
    cooldown_seconds: float = 60.0
    restart_process: bool = True
    only_if_stopped_by_coordinator: bool = True


@dataclass
class CoordinatorConfig:
    version: str = "1.0"
    service: ServiceConfig = field(default_factory=ServiceConfig)
    resources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    processes: Dict[str, ProcessConfig] = field(default_factory=dict)
    policies: List[PolicyConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoordinatorConfig":
        svc_raw = data.get("service", {})
        svc = ServiceConfig(
            listen_host=svc_raw.get("listen_host", "127.0.0.1"),
            listen_port=int(svc_raw.get("listen_port", 1235)),
            upstream_url=svc_raw.get("upstream_url", "http://127.0.0.1:1234"),
            state_persistence_path=svc_raw.get("state_persistence_path", ""),
        )

        processes = {}
        for p_name, p_data in data.get("processes", {}).items():
            processes[p_name] = ProcessConfig(
                name=p_name,
                backend=p_data.get("backend", "windows"),
                executable=p_data.get("executable", ""),
                arguments=list(p_data.get("arguments", [])),
                working_directory=p_data.get("working_directory"),
                stop_timeout_seconds=float(p_data.get("stop_timeout_seconds", 10.0)),
                restart_cooldown_seconds=float(p_data.get("restart_cooldown_seconds", 60.0)),
                new_console=bool(p_data.get("new_console", False)),
                adopt_external=bool(p_data.get("adopt_external", False)),
            )

        policies = []
        for pol_data in data.get("policies", []):
            policies.append(
                PolicyConfig(
                    name=pol_data.get("name", "unnamed_policy"),
                    trigger_event=pol_data.get("trigger_event")
                    or pol_data.get("trigger", {}).get("event", "lmstudio.inference_requested"),
                    target_process=pol_data.get("target_process") or pol_data.get("condition", {}).get("process"),
                    stop_process=bool(pol_data.get("stop_process", True)),
                    stop_timeout_seconds=float(pol_data.get("stop_timeout_seconds", 10.0)),
                    resource=pol_data.get("resource") or pol_data.get("lease", {}).get("resource", "gpu.inference"),
                    lease_type=pol_data.get("lease_type", "shared"),
                    cooldown_seconds=float(
                        pol_data.get("cooldown_seconds") or pol_data.get("release", {}).get("cooldown_seconds", 60.0)
                    ),
                    restart_process=bool(pol_data.get("restart_process", True)),
                    only_if_stopped_by_coordinator=bool(pol_data.get("only_if_stopped_by_coordinator", True)),
                )
            )

        return cls(
            version=str(data.get("version", "1.0")),
            service=svc,
            resources=dict(data.get("resources", {})),
            processes=processes,
            policies=policies,
        )


def load_config(path: Optional[Union[str, Path]] = None) -> CoordinatorConfig:
    """Load and parse coordinator configuration from YAML/JSON file or defaults."""
    if path is None:
        # Default configuration
        return CoordinatorConfig(
            service=ServiceConfig(),
            processes={
                "krig": ProcessConfig(
                    name="krig",
                    backend="windows",
                    executable=r"C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6\krig-miner.exe",
                    arguments=[
                        "--coin",
                        "pearl",
                        "--url",
                        "stratum+ssl://prl-us.kryptex.network:8048",
                        "--user",
                        "krxXPVG8JN/Xeres",
                    ],
                    working_directory=r"C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6",
                    new_console=True,
                )
            },
            policies=[
                PolicyConfig(
                    name="prioritize-local-inference",
                    trigger_event="lmstudio.inference_requested",
                    target_process="krig",
                    resource="gpu.inference",
                    cooldown_seconds=60.0,
                )
            ],
        )

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return CoordinatorConfig.from_dict(data)


@dataclass
class CoordinatorSystem:
    config: CoordinatorConfig
    dispatcher: EventDispatcher
    lease_mgr: LeaseManager
    supervisors: Dict[str, ProcessSupervisor]
    miner_adapter: Optional[MinerAdapter]
    policy_engine: PolicyEngine
    gateway: LMStudioGateway


def build_system(config: CoordinatorConfig, use_fake_processes: bool = False) -> CoordinatorSystem:
    """Factory creating fully wired coordinator system from configuration."""
    dispatcher = EventDispatcher()
    lease_mgr = LeaseManager(default_cooldown_seconds=60.0, event_dispatcher=dispatcher)
    policy_engine = PolicyEngine(event_dispatcher=dispatcher, lease_manager=lease_mgr)

    supervisors: Dict[str, ProcessSupervisor] = {}
    miner_adapter: Optional[MinerAdapter] = None

    for name, p_cfg in config.processes.items():
        if use_fake_processes or p_cfg.backend == "fake":
            backend = FakeProcessBackend(name=name, running=False, executable=p_cfg.executable)
        else:
            backend = WindowsProcessBackend(
                name=name,
                executable=p_cfg.executable,
                arguments=p_cfg.arguments,
                working_directory=p_cfg.working_directory,
                new_console=p_cfg.new_console,
                adopt_external=p_cfg.adopt_external,
            )
        supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)
        supervisors[name] = supervisor

        # By default create miner adapter for miner-like processes
        if "miner" in name.lower() or "krig" in name.lower():
            miner_adapter = MinerAdapter(supervisor=supervisor, event_dispatcher=dispatcher)

    for pol_cfg in config.policies:
        actions = []
        after_release_actions = []
        condition = None

        if pol_cfg.target_process and pol_cfg.target_process in supervisors:
            target_sup = supervisors[pol_cfg.target_process]
            condition = ProcessRunningCondition(target_sup)
            if pol_cfg.stop_process:
                actions.append(
                    StopProcessAction(
                        supervisor=target_sup,
                        wait_until_stopped=True,
                        timeout_seconds=pol_cfg.stop_timeout_seconds,
                    )
                )
            if pol_cfg.restart_process:
                after_release_actions.append(
                    StartProcessAction(
                        supervisor=target_sup,
                        only_if_stopped_by_coordinator=pol_cfg.only_if_stopped_by_coordinator,
                    )
                )

        policy = Policy(
            name=pol_cfg.name,
            trigger_event=pol_cfg.trigger_event,
            condition=condition,
            actions=actions,
            resource=pol_cfg.resource,
            lease_type=LeaseType(pol_cfg.lease_type),
            cooldown_seconds=pol_cfg.cooldown_seconds,
            after_release_actions=after_release_actions,
        )
        policy_engine.register_policy(policy)

    gateway = LMStudioGateway(
        upstream_url=config.service.upstream_url,
        event_dispatcher=dispatcher,
        lease_manager=lease_mgr,
    )

    return CoordinatorSystem(
        config=config,
        dispatcher=dispatcher,
        lease_mgr=lease_mgr,
        supervisors=supervisors,
        miner_adapter=miner_adapter,
        policy_engine=policy_engine,
        gateway=gateway,
    )
