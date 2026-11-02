"""Non-executing plan resolution and readiness verification for Harbor evaluations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import shutil
import subprocess
from typing import Any, Sequence

from .datasets import DatasetDescriptor, resolve_dataset, select_tasks

# Officially supported Harbor agent adapters recognized for coding evaluation
SUPPORTED_HARBOR_AGENTS: dict[str, dict[str, Any]] = {
    "oracle": {
        "description": "Authoritative task reference solution runner (ground truth verifier test)",
        "requires_model": False,
        "requires_docker": True,
        "requires_credentials": False,
        "default_model": "none",
        "default_base_url": None,
    },
    "nop": {
        "description": "No-op baseline agent (produces empty/unmodified submission)",
        "requires_model": False,
        "requires_docker": True,
        "requires_credentials": False,
        "default_model": "none",
        "default_base_url": None,
    },
    "codex": {
        "description": "OpenAI Codex CLI adapter",
        "requires_model": True,
        "requires_docker": True,
        "requires_credentials": True,
        "env_var": "OPENAI_API_KEY",
        "default_model": "default",
        "default_base_url": None,
    },
    "antigravity-cli": {
        "description": "Google Antigravity CLI coding agent",
        "requires_model": True,
        "requires_docker": True,
        "requires_credentials": True,
        "env_var": "GEMINI_API_KEY",
        "default_model": "default",
        "default_base_url": None,
    },
    "antigravity-sdk": {
        "description": "Google Antigravity Python SDK agent",
        "requires_model": True,
        "requires_docker": True,
        "requires_credentials": True,
        "env_var": "GEMINI_API_KEY",
        "default_model": "default",
        "default_base_url": None,
    },
    "opencode": {
        "description": "OpenCode local bridge worker",
        "requires_model": True,
        "requires_docker": True,
        "requires_credentials": False,
        "default_model": "openai/qwen38_23GB",
        "default_base_url": "http://host.docker.internal:1234/v1",
    },
    "qwen-coder": {
        "description": "Qwen Code local agent via OpenAI-compatible endpoint",
        "requires_model": True,
        "requires_docker": True,
        "requires_credentials": False,
        "default_model": "qwen38_23GB",
        "default_base_url": "http://host.docker.internal:1234/v1",
    },
    "aider": {
        "description": "Aider coding assistant CLI adapter",
        "requires_model": True,
        "requires_docker": True,
        "requires_credentials": True,
        "default_model": "default",
        "default_base_url": None,
    },
    "claude-code": {
        "description": "Anthropic Claude Code CLI adapter",
        "requires_model": True,
        "requires_docker": True,
        "requires_credentials": True,
        "env_var": "ANTHROPIC_API_KEY",
        "default_model": "default",
        "default_base_url": None,
    },
}


@dataclass(frozen=True)
class ReadinessCheck:
    harbor_installed: bool
    harbor_version: str | None
    docker_available: bool
    docker_message: str
    agent_supported: bool
    agent_message: str
    blockers: tuple[str, ...]

    @property
    def is_runnable(self) -> bool:
        return len(self.blockers) == 0


def check_docker_readiness() -> tuple[bool, str]:
    """Check whether Docker daemon is active and responsive."""
    docker_exe = shutil.which("docker")
    if not docker_exe:
        return False, "Docker CLI binary not found on PATH"

    try:
        res = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return True, "Docker daemon is active and responsive"
        return False, f"Docker daemon unreachable: {res.stderr.strip() or 'daemon not running'}"
    except subprocess.TimeoutExpired:
        return False, "Docker info probe timed out after 5 seconds"
    except Exception as exc:
        return False, f"Docker probe failed: {exc}"


def check_harbor_readiness() -> tuple[bool, str | None]:
    """Check whether Harbor CLI is available locally or via uv tool run."""
    # 1. Native harbor on PATH
    harbor_exe = shutil.which("harbor")
    if harbor_exe:
        try:
            res = subprocess.run(
                ["harbor", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                ver_line = res.stdout.strip() or res.stderr.strip()
                return True, ver_line
        except Exception:
            pass

    # 2. uv tool run --from harbor==0.25.0
    uv_exe = shutil.which("uv")
    if uv_exe:
        return True, "harbor==0.25.0 (managed via uv tool run)"

    return False, None


def verify_agent_readiness(agent_name: str) -> tuple[bool, str]:
    """Check if agent is supported by Harbor and describe its configuration requirements."""
    agent_norm = agent_name.lower().strip()
    if agent_norm not in SUPPORTED_HARBOR_AGENTS:
        valid_agents = sorted(SUPPORTED_HARBOR_AGENTS.keys())
        return False, f"Unsupported Harbor agent {agent_name!r}. Supported: {valid_agents}"

    meta = SUPPORTED_HARBOR_AGENTS[agent_norm]
    env_var = meta.get("env_var")
    if env_var and not os.environ.get(env_var):
        return True, f"Agent supported; credentials in ${env_var} not set in host environment (required for cloud inference)"

    return True, f"Agent supported: {meta['description']}"


def check_agent_configuration_blockers(
    agent_name: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> list[str]:
    """Identify invalid or missing configuration parameters for a given agent."""
    agent_norm = agent_name.lower().strip()
    if agent_norm not in SUPPORTED_HARBOR_AGENTS:
        return [f"Unsupported Harbor agent {agent_name!r}"]

    meta = SUPPORTED_HARBOR_AGENTS[agent_norm]
    blockers: list[str] = []

    # 1. Agents that do not accept a model
    if not meta.get("requires_model") and model is not None and model not in ("none", "default"):
        blockers.append(f"Agent {agent_name!r} does not accept a model parameter (received {model!r})")

    # 2. Agents that do not accept a base URL
    if agent_norm in ("oracle", "nop") and base_url is not None:
        blockers.append(f"Agent {agent_name!r} does not accept an inference base-url parameter (received {base_url!r})")

    # 3. Agents requiring credentials when not routing to a custom base_url
    if meta.get("requires_credentials") and not base_url:
        env_var = meta.get("env_var")
        if env_var and not os.environ.get(env_var):
            blockers.append(f"Credentials in ${env_var} must be set in environment for {agent_name} cloud execution")

    # 4. Local agents (qwen-coder, opencode) require a base URL
    if agent_norm in ("qwen-coder", "opencode") and not base_url:
        blockers.append(f"{agent_name} requires --base-url pointing to an OpenAI-compatible endpoint")

    return blockers


@dataclass(frozen=True)
class BenchmarkPlan:
    dataset: DatasetDescriptor
    selected_tasks: tuple[str, ...]
    agent: str
    model: str
    repetitions: int
    seed: int | None
    language_filter: str | None
    scoring_protocol: str
    projected_trials: int
    readiness: ReadinessCheck
    base_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": {
                "id": self.dataset.id,
                "name": self.dataset.name,
                "version": self.dataset.version,
                "harbor_dataset": self.dataset.harbor_dataset,
                "source_repo": self.dataset.source_repo,
                "source_revision": self.dataset.source_revision,
                "supported_languages": list(self.dataset.supported_languages),
                "total_available_tasks": len(self.dataset.all_tasks),
                "default_tasks": list(self.dataset.default_tasks),
            },
            "selected_tasks_count": len(self.selected_tasks),
            "selected_tasks": list(self.selected_tasks),
            "agent": self.agent,
            "model": self.model,
            "base_url": self.base_url,
            "repetitions": self.repetitions,
            "seed": self.seed,
            "language_filter": self.language_filter,
            "scoring_protocol": self.scoring_protocol,
            "projected_trials": self.projected_trials,
            "readiness": asdict(self.readiness),
        }


def plan_benchmark(
    dataset_name: str = "aider-polyglot",
    *,
    agent: str = "qwen-coder",
    model: str | None = None,
    base_url: str | None = None,
    task_ids: Sequence[str] | None = None,
    language: str | None = None,
    count: int | None = None,
    repetitions: int = 1,
    seed: int | None = 42,
) -> BenchmarkPlan:
    """Resolve tasks, check readiness, and produce an immutable non-executing BenchmarkPlan."""
    descriptor = resolve_dataset(dataset_name)

    agent_norm = agent.lower().strip()
    if agent_norm not in SUPPORTED_HARBOR_AGENTS:
        valid_agents = sorted(SUPPORTED_HARBOR_AGENTS.keys())
        raise ValueError(f"Unsupported Harbor agent {agent!r}. Supported: {valid_agents}")

    meta = SUPPORTED_HARBOR_AGENTS[agent_norm]

    # Resolve agent-appropriate defaults when not explicitly provided
    effective_model = model if model is not None else meta.get("default_model", "default")
    effective_base_url = base_url if base_url is not None else meta.get("default_base_url")

    if not meta.get("requires_model") and model is None:
        effective_model = "none"
    if agent_norm in ("oracle", "nop") and base_url is None:
        effective_base_url = None

    selected = select_tasks(
        descriptor,
        task_ids=task_ids,
        language=language,
        count=count,
        seed=seed,
    )

    if not selected:
        raise ValueError(f"No tasks selected for dataset {descriptor.id}")

    if repetitions < 1:
        raise ValueError(f"Repetitions must be a positive integer, got {repetitions}")

    # Check readiness
    harbor_ok, harbor_ver = check_harbor_readiness()
    docker_ok, docker_msg = check_docker_readiness()
    agent_ok, agent_msg = verify_agent_readiness(agent)
    agent_blockers = check_agent_configuration_blockers(
        agent, model=model, base_url=effective_base_url
    )

    blockers: list[str] = []
    if not harbor_ok:
        blockers.append("Harbor CLI or uv is not available")
    if not docker_ok:
        blockers.append(f"Docker is required for external benchmark isolation: {docker_msg}")
    if not agent_ok:
        blockers.append(agent_msg)
    blockers.extend(agent_blockers)

    readiness = ReadinessCheck(
        harbor_installed=harbor_ok,
        harbor_version=harbor_ver,
        docker_available=docker_ok,
        docker_message=docker_msg,
        agent_supported=agent_ok,
        agent_message=agent_msg,
        blockers=tuple(blockers),
    )

    projected_trials = len(selected) * repetitions

    return BenchmarkPlan(
        dataset=descriptor,
        selected_tasks=tuple(selected),
        agent=agent,
        model=effective_model,
        base_url=effective_base_url,
        repetitions=repetitions,
        seed=seed,
        language_filter=language,
        scoring_protocol=descriptor.default_scoring_protocol,
        projected_trials=projected_trials,
        readiness=readiness,
    )
