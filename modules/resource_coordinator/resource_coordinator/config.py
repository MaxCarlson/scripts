"""
Configuration parser, validation, and system factory.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml  # type: ignore[import-untyped]

from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway
from resource_coordinator.adapters.miners.adapter import MinerAdapter
from resource_coordinator.core.actions import Action, StartProcessAction, StopProcessAction
from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.policies import Policy, PolicyEngine
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessBackend,
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
    bounded_drain_seconds: Optional[float] = None


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
    allow_external_stop: bool = False
    allow_external_restart: bool = False
    adopt_external: bool = False
    allow_force_termination: bool = False


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
        if not isinstance(data, dict):
            raise TypeError("Configuration must be a mapping")
        if str(data.get("version", "1.0")) != "1.0":
            raise ValueError("Unsupported configuration version")
        svc_raw = data.get("service", {})
        for section in [*data.get("processes", {}).values(), *data.get("policies", [])]:
            for key, value in section.items():
                if key in {
                    "new_console",
                    "allow_external_stop",
                    "allow_external_restart",
                    "adopt_external",
                    "allow_force_termination",
                    "stop_process",
                    "restart_process",
                    "only_if_stopped_by_coordinator",
                }:
                    if not isinstance(value, bool):
                        raise TypeError(f"{key} must be a boolean")
        svc = ServiceConfig(
            listen_host=svc_raw.get("listen_host", "127.0.0.1"),
            listen_port=int(svc_raw.get("listen_port", 1235)),
            upstream_url=svc_raw.get("upstream_url", "http://127.0.0.1:1234"),
            state_persistence_path=svc_raw.get("state_persistence_path", ""),
            bounded_drain_seconds=(
                float(svc_raw["bounded_drain_seconds"]) if svc_raw.get("bounded_drain_seconds") is not None else None
            ),
        )

        processes = {}
        for p_name, p_data in data.get("processes", {}).items():
            adopt = bool(p_data.get("adopt_external", False))
            processes[p_name] = ProcessConfig(
                name=p_name,
                backend=p_data.get("backend", "windows"),
                executable=p_data.get("executable", ""),
                arguments=list(p_data.get("arguments", [])),
                working_directory=p_data.get("working_directory"),
                stop_timeout_seconds=float(p_data.get("stop_timeout_seconds", 10.0)),
                restart_cooldown_seconds=float(p_data.get("restart_cooldown_seconds", 60.0)),
                new_console=bool(p_data.get("new_console", False)),
                allow_external_stop=bool(p_data.get("allow_external_stop", adopt)),
                allow_external_restart=bool(p_data.get("allow_external_restart", adopt)),
                adopt_external=adopt,
                allow_force_termination=p_data.get("allow_force_termination", False),
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
                        pol_data.get("cooldown_seconds", pol_data.get("release", {}).get("cooldown_seconds", 60.0))
                    ),
                    restart_process=bool(pol_data.get("restart_process", True)),
                    only_if_stopped_by_coordinator=bool(pol_data.get("only_if_stopped_by_coordinator", True)),
                )
            )

        for process in processes.values():
            if process.backend not in {"windows", "fake"}:
                raise ValueError(f"Unknown backend: {process.backend}")
            if process.backend == "windows" and not Path(process.executable).is_absolute():
                raise ValueError("Windows process executable must be an absolute path")
        for policy in policies:
            if policy.target_process and policy.target_process not in processes:
                raise ValueError(f"Unknown target process: {policy.target_process}")
            LeaseType(policy.lease_type)
            if policy.restart_process and not policy.only_if_stopped_by_coordinator:
                raise ValueError("Automatic restart requires a coordinator-owned stop")
        load_policies = [p for p in policies if p.trigger_event == "lmstudio.model_load_requested"]
        for load_policy in load_policies:
            if (
                not load_policy.target_process
                or not load_policy.stop_process
                or not load_policy.restart_process
                or load_policy.resource != "gpu.inference"
                or LeaseType(load_policy.lease_type) != LeaseType.EXCLUSIVE
            ):
                raise ValueError(
                    "Model-load policy must stop a configured process on gpu.inference with an exclusive lease"
                )
            inference_policies = [
                p
                for p in policies
                if p.trigger_event == "lmstudio.inference_requested"
                and p.target_process == load_policy.target_process
                and p.stop_process
                and p.restart_process
                and p.resource == "gpu.inference"
            ]
            if not inference_policies:
                raise ValueError("Model-load policy must target the same process as an inference stop policy")
            if any(p.cooldown_seconds != load_policy.cooldown_seconds for p in inference_policies):
                raise ValueError("Model-load and inference policies for one process must use the same idle timeout")
        durations = [p.cooldown_seconds for p in policies] + [p.stop_timeout_seconds for p in policies]
        durations += [p.stop_timeout_seconds for p in processes.values()]
        durations += [float(r.get("cooldown_seconds", 60)) for r in data.get("resources", {}).values()]
        if any(not math.isfinite(value) or value < 0 for value in durations):
            raise ValueError("Durations must be finite and nonnegative")
        if any(policy.restart_process and policy.cooldown_seconds <= 0 for policy in policies):
            raise ValueError("Restarting process policies require a positive idle timeout")
        if not 0 < svc.listen_port < 65536:
            raise ValueError("Listen port is out of range")
        if svc.state_persistence_path:
            raise ValueError("State persistence is not implemented")
        if svc.bounded_drain_seconds:
            raise ValueError("Bounded drain is disabled pending cancellation-safe implementation")
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
        # Default configuration with sanitized paths and pool addresses
        return CoordinatorConfig(
            service=ServiceConfig(),
            processes={
                "krig": ProcessConfig(
                    name="krig",
                    backend="windows",
                    executable=r"C:\Mining\krig-miner.exe",
                    arguments=[
                        "--coin",
                        "pearl",
                        "--url",
                        "stratum+ssl://prl-us.example-pool.network:8048",
                        "--user",
                        "0x0000000000000000000000000000000000000000/Worker1",
                    ],
                    working_directory=r"C:\Mining",
                    new_console=True,
                    allow_external_stop=False,
                    allow_external_restart=False,
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
        backend: ProcessBackend
        if use_fake_processes or p_cfg.backend == "fake":
            backend = FakeProcessBackend(
                name=name,
                running=False,
                executable=p_cfg.executable,
                allow_external_stop=p_cfg.allow_external_stop,
                allow_external_restart=p_cfg.allow_external_restart,
            )
        else:
            backend = WindowsProcessBackend(
                name=name,
                executable=p_cfg.executable,
                arguments=p_cfg.arguments,
                working_directory=p_cfg.working_directory,
                new_console=p_cfg.new_console,
                allow_external_stop=p_cfg.allow_external_stop,
                allow_external_restart=p_cfg.allow_external_restart,
                adopt_external=p_cfg.adopt_external,
                allow_force_termination=p_cfg.allow_force_termination,
            )
        supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)
        supervisors[name] = supervisor

        # By default create miner adapter for miner-like processes
        if "miner" in name.lower() or "krig" in name.lower():
            miner_adapter = MinerAdapter(supervisor=supervisor, event_dispatcher=dispatcher)

    for pol_cfg in config.policies:
        actions: List[Action] = []
        after_release_actions: List[Action] = []
        condition = None

        if pol_cfg.target_process and pol_cfg.target_process in supervisors:
            target_sup = supervisors[pol_cfg.target_process]
            condition = None
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
        bounded_drain_seconds=config.service.bounded_drain_seconds,
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
