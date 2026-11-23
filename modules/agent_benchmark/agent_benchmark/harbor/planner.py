"""Non-executing plan resolution and readiness verification for Harbor evaluations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ipaddress
import os
import shutil
import subprocess
from typing import Any, Sequence
from urllib.parse import urlsplit

from .datasets import DatasetDescriptor, resolve_dataset, select_tasks

PROTECTED_COORDINATOR_HOST = "host.docker.internal"
PROTECTED_COORDINATOR_PORT = 1235
PROTECTED_COORDINATOR_BASE_URL = f"http://{PROTECTED_COORDINATOR_HOST}:{PROTECTED_COORDINATOR_PORT}/v1"
DIRECT_LMSTUDIO_PORT = 1234
LLM_MONITOR_PORTS = frozenset({8788, 8789})
LOCAL_HARBOR_AGENTS = frozenset({"qwen-coder", "opencode", "opencode-v2"})

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
        "default_base_url": PROTECTED_COORDINATOR_BASE_URL,
    },
    "opencode-v2": {
        "description": "OpenCode v2 candidate agent (@opencode/cli@2.2.5)",
        "requires_model": True,
        "requires_docker": True,
        "requires_credentials": False,
        "default_model": "openai/qwen38_23GB",
        "default_base_url": PROTECTED_COORDINATOR_BASE_URL,
        "pinned_version": "2.2.5",
        "package": "@opencode/cli",
    },
    "qwen-coder": {
        "description": "Qwen Code local agent via OpenAI-compatible endpoint",
        "requires_model": True,
        "requires_docker": True,
        "requires_credentials": False,
        "default_model": "qwen38_23GB",
        "default_base_url": PROTECTED_COORDINATOR_BASE_URL,
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

SUPPORTED_MODEL_API_FORMATS: set[str] = {
    "openai_chat_completions",
    "openai_responses",
    "anthropic_messages",
    "google_generate_content",
    "bedrock_converse",
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


def _is_loopback_or_unspecified_host(host: str) -> bool:
    """Return True if host is localhost, loopback, or an unspecified bind address."""
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip_obj.is_loopback or ip_obj.is_unspecified:
        return True
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
        return ip_obj.ipv4_mapped.is_loopback or ip_obj.ipv4_mapped.is_unspecified
    return False


def validate_harbor_inference_base_url(agent_name: str, base_url: str | None) -> str | None:
    """Validate Harbor inference base_url, failing closed on bypasses, malformed URLs, and unverified routes."""
    agent_norm = agent_name.lower().strip()
    if agent_norm in ("oracle", "nop"):
        return None

    is_local_agent = agent_norm in LOCAL_HARBOR_AGENTS
    if base_url is None:
        if is_local_agent:
            return (
                f"{agent_name} requires --base-url pointing to the protected Resource Coordinator "
                f"endpoint ({PROTECTED_COORDINATOR_BASE_URL})"
            )
        return None

    if not base_url.strip() or any(ch.isspace() for ch in base_url):
        return (
            f"Malformed inference base_url {base_url!r} for {agent_name}: "
            f"empty or whitespace-containing URL is not permitted (expected {PROTECTED_COORDINATOR_BASE_URL})"
        )

    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        return f"Malformed inference base_url {base_url!r} for {agent_name}: {exc}"

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not parsed.netloc:
        return (
            f"Malformed inference base_url {base_url!r} for {agent_name}: "
            "must use http:// or https:// with a valid host"
        )
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        return (
            f"Malformed inference base_url {base_url!r} for {agent_name}: "
            "credentials, query parameters, and fragments are not permitted"
        )

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return f"Malformed inference base_url {base_url!r} for {agent_name}: missing hostname"

    if port == DIRECT_LMSTUDIO_PORT:
        return (
            f"Unsafe direct LM Studio bypass route {base_url!r} for {agent_name}: "
            f"port {DIRECT_LMSTUDIO_PORT} bypasses Resource Coordinator protection "
            f"(use {PROTECTED_COORDINATOR_BASE_URL})"
        )

    if _is_loopback_or_unspecified_host(host):
        return (
            f"Unsafe local loopback/host-only inference route {base_url!r} for {agent_name}: "
            f"container agents cannot safely route to {host!r} (use {PROTECTED_COORDINATOR_BASE_URL})"
        )

    if is_local_agent or host == PROTECTED_COORDINATOR_HOST:
        if scheme != "http":
            return (
                f"Unverified local inference route {base_url!r} for {agent_name}: "
                f"expected http:// for container-facing Resource Coordinator ({PROTECTED_COORDINATOR_BASE_URL})"
            )
        if host != PROTECTED_COORDINATOR_HOST:
            return (
                f"Unverified local inference route {base_url!r} for {agent_name}: "
                f"host {host!r} is not the container-facing Resource Coordinator host "
                f"{PROTECTED_COORDINATOR_HOST!r} (use {PROTECTED_COORDINATOR_BASE_URL})"
            )
        if port is None:
            return (
                f"Malformed or unverified local inference route {base_url!r} for {agent_name}: "
                f"explicit Resource Coordinator port {PROTECTED_COORDINATOR_PORT} is required "
                f"(use {PROTECTED_COORDINATOR_BASE_URL})"
            )
        if port in LLM_MONITOR_PORTS:
            return (
                f"Unverified LLM Monitor inference route {base_url!r} for {agent_name}: "
                f"port {port} cannot be proven offline to forward through Resource Coordinator "
                f"(:{PROTECTED_COORDINATOR_PORT}); use {PROTECTED_COORDINATOR_BASE_URL}"
            )
        if port != PROTECTED_COORDINATOR_PORT:
            return (
                f"Unverified local inference route {base_url!r} for {agent_name}: "
                f"port {port} is not the protected Resource Coordinator port "
                f"{PROTECTED_COORDINATOR_PORT} (use {PROTECTED_COORDINATOR_BASE_URL})"
            )
        if parsed.path.rstrip("/") != "/v1":
            return (
                f"Malformed local inference route {base_url!r} for {agent_name}: "
                f"OpenAI-compatible '/v1' path is required (expected {PROTECTED_COORDINATOR_BASE_URL})"
            )

    return None


def check_agent_configuration_blockers(
    agent_name: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    model_api_format: str | None = None,
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

    # 4. Validate inference base_url routing (blocks direct :1234, loopback, malformed, and unverified routes)
    url_blocker = validate_harbor_inference_base_url(agent_name, base_url)
    if url_blocker:
        blockers.append(url_blocker)

    # 5. Agents that do not accept an api-format parameter
    if agent_norm in ("oracle", "nop") and model_api_format is not None:
        blockers.append(f"Agent {agent_name!r} does not accept an api-format parameter (received {model_api_format!r})")

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
    model_api_format: str | None = None

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
            "model_api_format": self.model_api_format,
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
    model_api_format: str | None = None,
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

    canonical_format: str | None = None
    if model_api_format is not None:
        format_norm = model_api_format.strip().lower().replace("-", "_")
        if format_norm not in SUPPORTED_MODEL_API_FORMATS:
            valid_formats = sorted(SUPPORTED_MODEL_API_FORMATS)
            raise ValueError(
                f"Unsupported model API format {model_api_format!r}. Supported: {valid_formats}"
            )
        canonical_format = format_norm

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
        agent, model=model, base_url=effective_base_url, model_api_format=canonical_format
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
        model_api_format=canonical_format,
        repetitions=repetitions,
        seed=seed,
        language_filter=language,
        scoring_protocol=descriptor.default_scoring_protocol,
        projected_trials=projected_trials,
        readiness=readiness,
    )
