"""Model registry and assignment helpers for coding-focused quantized models."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

try:
    from huggingface_hub import snapshot_download
except ImportError:  # pragma: no cover - import guard
    snapshot_download = None

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSpec:
    """Metadata describing a quantized model release."""

    name: str
    repo_id: str
    filename: str
    quantization: str
    parameter_count_b: float
    context_length: int
    recommended_vram_gb: int
    download_size_gb: float
    preferred_tasks: Sequence[str]
    description: str
    capability_score: float
    extra_files: Sequence[str] = field(
        default_factory=lambda: ("tokenizer.model", "tokenizer.json", "config.json")
    )


class ModelRegistry:
    """Stores ModelSpec entries and exposes lookup utilities."""

    def __init__(self, models: Optional[Dict[str, ModelSpec]] = None) -> None:
        self._models: Dict[str, ModelSpec] = models or {}

    def add(self, spec: ModelSpec) -> None:
        LOGGER.debug("Registering model spec %s", spec.name)
        self._models[spec.name] = spec

    def get(self, model_name: str) -> ModelSpec:
        if model_name not in self._models:
            raise KeyError(f"Unknown model '{model_name}'. Available: {', '.join(self._models)}")
        return self._models[model_name]

    def list_models(self) -> List[ModelSpec]:
        return list(self._models.values())

    def list_for_task(self, task: str) -> List[ModelSpec]:
        task_lower = task.lower()
        return [spec for spec in self._models.values() if task_lower in (t.lower() for t in spec.preferred_tasks)]

    @classmethod
    def default(cls) -> "ModelRegistry":
        registry = cls()
        for spec in DEFAULT_MODEL_SPECS:
            registry.add(spec)
        return registry


class ModelAssignmentManager:
    """Selects models for tasks based on VRAM and downloads them on demand."""

    def __init__(
        self,
        registry: Optional[ModelRegistry] = None,
        cache_dir: Optional[Path] = None,
        hf_token_env: str = "HF_TOKEN",
    ) -> None:
        self.registry = registry or ModelRegistry.default()
        self.cache_dir = Path(cache_dir or os.environ.get("LLM_MODELS_CACHE", Path.home() / ".cache" / "llm_models"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.hf_token_env = hf_token_env

    def select_model(
        self,
        task: str = "coding",
        max_vram_gb: Optional[int] = None,
        min_score: float = 0.0,
    ) -> ModelSpec:
        """Return the highest scoring model that fits within the VRAM budget."""

        budget = max_vram_gb or self._detect_available_vram()
        if budget is None:
            raise RuntimeError("Unable to determine VRAM budget. Provide max_vram_gb or set LLM_MAX_VRAM_GB.")

        LOGGER.debug("Selecting model for task=%s budget=%sgb min_score=%s", task, budget, min_score)
        task_lower = task.lower()
        eligible: List[ModelSpec] = [
            spec for spec in self.registry.list_models() if spec.recommended_vram_gb <= budget and spec.capability_score >= min_score
        ]

        if not eligible:
            raise RuntimeError(
                f"No registered models fit within {budget}GB VRAM and score >= {min_score}. "
                "Adjust the constraints or register additional models."
            )

        def score(spec: ModelSpec) -> float:
            bonus = 0.3 if task_lower in (t.lower() for t in spec.preferred_tasks) else 0.0
            return spec.capability_score + bonus

        selected = max(eligible, key=score)
        LOGGER.info("Selected model %s (needs %sGB)", selected.name, selected.recommended_vram_gb)
        return selected

    def download_model(
        self,
        model_name: str,
        *,
        cache_dir: Optional[Path] = None,
        revision: Optional[str] = None,
        allow_patterns: Optional[Iterable[str]] = None,
        token: Optional[str] = None,
    ) -> Path:
        """Download the model checkpoint plus tokenizer artifacts and return the checkpoint path."""

        spec = self.registry.get(model_name)
        resolved_cache = Path(cache_dir or self.cache_dir)
        resolved_cache.mkdir(parents=True, exist_ok=True)

        token = token or os.environ.get(self.hf_token_env)
        patterns = list(allow_patterns) if allow_patterns else [spec.filename, *spec.extra_files]

        LOGGER.info("Downloading %s from %s", spec.name, spec.repo_id)
        if snapshot_download is None:  # pragma: no cover - import guard
            raise RuntimeError("huggingface_hub is required to download models. Install llm-models with its dependencies.")
        download_root = Path(
            snapshot_download(
                repo_id=spec.repo_id,
                allow_patterns=patterns,
                cache_dir=str(resolved_cache),
                revision=revision,
                token=token,
            )
        )

        candidate = download_root / spec.filename
        if not candidate.exists():
            matches = list(download_root.rglob(spec.filename))
            if not matches:
                raise FileNotFoundError(f"Downloaded files did not contain {spec.filename}")
            candidate = matches[0]

        LOGGER.info("Model stored at %s", candidate)
        return candidate

    def ensure_task_models(self, task: str, *, max_vram_gb: Optional[int] = None) -> List[Path]:
        """Download all models that match the task within the VRAM budget."""

        budget = max_vram_gb or self._detect_available_vram()
        downloaded: List[Path] = []
        for spec in self.registry.list_for_task(task):
            if spec.recommended_vram_gb <= budget:
                downloaded.append(self.download_model(spec.name))
            else:
                LOGGER.debug("Skipping %s (needs %sGB, budget %sGB)", spec.name, spec.recommended_vram_gb, budget)
        return downloaded

    def _detect_available_vram(self) -> Optional[int]:
        """Attempt to detect total GPU VRAM via environment or nvidia-smi."""

        if "LLM_MAX_VRAM_GB" in os.environ:
            try:
                return int(os.environ["LLM_MAX_VRAM_GB"])
            except ValueError:
                LOGGER.warning("Invalid LLM_MAX_VRAM_GB value '%s'", os.environ["LLM_MAX_VRAM_GB"])

        nvidia_smi = os.environ.get("NVIDIA_SMI", "nvidia-smi")
        try:
            result = subprocess.run(
                [nvidia_smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            first_line = result.stdout.strip().splitlines()[0].strip()
            return int(first_line)
        except (subprocess.SubprocessError, FileNotFoundError, ValueError, IndexError) as error:
            LOGGER.debug("Unable to query nvidia-smi: %s", error)
            return None


DEFAULT_MODEL_SPECS: List[ModelSpec] = [
    ModelSpec(
        name="qwen2.5-coder-32b-instruct-q4_k_m",
        repo_id="Qwen/Qwen2.5-Coder-32B-Instruct-GGUF",
        filename="Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf",
        quantization="Q4_K_M",
        parameter_count_b=32,
        context_length=32768,
        recommended_vram_gb=28,
        download_size_gb=19.4,
        preferred_tasks=("coding", "reasoning", "planning"),
        description=(
            "Top-tier coding assistant with strong benchmark performance (HumanEval+, MBPP). "
            "Great balance between deep reasoning and instrument control."
        ),
        capability_score=0.92,
    ),
    ModelSpec(
        name="deepseek-coder-v2-lite-instruct-q4_k_m",
        repo_id="deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct-GGUF",
        filename="DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf",
        quantization="Q4_K_M",
        parameter_count_b=16,
        context_length=32768,
        recommended_vram_gb=20,
        download_size_gb=11.0,
        preferred_tasks=("coding", "reasoning", "agent"),
        description="Efficient coding model tuned for tool-use reasoning, excels at HumanEval and LiveCodeBench.",
        capability_score=0.88,
    ),
    ModelSpec(
        name="codellama-34b-instruct-q4_k_m",
        repo_id="TheBloke/CodeLlama-34B-Instruct-GGUF",
        filename="codellama-34b-instruct.Q4_K_M.gguf",
        quantization="Q4_K_M",
        parameter_count_b=34,
        context_length=16384,
        recommended_vram_gb=22,
        download_size_gb=18.2,
        preferred_tasks=("coding", "analysis"),
        description="Stable legacy workhorse with great compatibility across runtimes and strong structured output.",
        capability_score=0.83,
    ),
    ModelSpec(
        name="codeqwen1.5-14b-chat-q4_k_m",
        repo_id="Qwen/CodeQwen1.5-14B-Chat-GGUF",
        filename="codeqwen1.5-14b-chat-q4_k_m.gguf",
        quantization="Q4_K_M",
        parameter_count_b=14,
        context_length=32768,
        recommended_vram_gb=16,
        download_size_gb=8.5,
        preferred_tasks=("coding", "routing"),
        description="Fast fallback with broad coverage of libraries and concise chain-of-thought responses.",
        capability_score=0.78,
    ),
]
