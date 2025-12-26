"""Model Manager - Manages AI models and selects best model for tasks."""

import json
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict
from pathlib import Path


class ModelCapability(Enum):
    """Capabilities that models can have."""
    CODE_GENERATION = "code_generation"
    CODE_UNDERSTANDING = "code_understanding"
    REASONING = "reasoning"
    MATH = "math"
    CHAT = "chat"
    FUNCTION_CALLING = "function_calling"
    VISION = "vision"
    LONG_CONTEXT = "long_context"


class ModelProvider(Enum):
    """Model providers/sources."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    LOCAL_LMSTUDIO = "local_lmstudio"
    LOCAL_OLLAMA = "local_ollama"
    CUSTOM = "custom"


@dataclass
class GPUInfo:
    """Information about available GPU."""
    name: str
    vram_total_gb: float
    vram_available_gb: float
    compute_capability: Optional[str] = None
    cuda_version: Optional[str] = None


@dataclass
class ModelConfig:
    """Configuration for an AI model."""
    name: str
    provider: ModelProvider
    model_id: str  # API model ID or local model path
    capabilities: List[ModelCapability]
    context_window: int
    max_output_tokens: int
    priority: int = 5  # 1-10, higher is better for general use

    # Resource requirements
    requires_gpu: bool = False
    vram_required_gb: Optional[float] = None

    # Cost/availability
    cost_per_million_tokens: Optional[float] = None
    requires_api_key: bool = False
    is_local: bool = False

    # Performance
    tokens_per_second: Optional[float] = None

    # Additional metadata
    metadata: Dict = field(default_factory=dict)


class ModelManager:
    """Manages AI models and selects optimal model for tasks."""

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize model manager.

        Args:
            config_path: Optional path to custom model config JSON
        """
        self.models: Dict[str, ModelConfig] = {}
        self.gpu_info: Optional[GPUInfo] = None

        self._detect_gpu()
        self._register_default_models()

        if config_path and config_path.exists():
            self._load_config(config_path)

    def _detect_gpu(self):
        """Detect available GPU (if any)."""
        try:
            # Try nvidia-smi for NVIDIA GPUs
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if lines:
                    parts = lines[0].split(",")
                    if len(parts) >= 3:
                        self.gpu_info = GPUInfo(
                            name=parts[0].strip(),
                            vram_total_gb=float(parts[1].strip()) / 1024,
                            vram_available_gb=float(parts[2].strip()) / 1024
                        )
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            # nvidia-smi not available or failed
            pass

    def _register_default_models(self):
        """Register common models."""
        models = [
            # Anthropic models
            ModelConfig(
                name="Claude Opus 4.5",
                provider=ModelProvider.ANTHROPIC,
                model_id="claude-opus-4-5-20251101",
                capabilities=[
                    ModelCapability.CODE_GENERATION,
                    ModelCapability.CODE_UNDERSTANDING,
                    ModelCapability.REASONING,
                    ModelCapability.MATH,
                    ModelCapability.CHAT,
                    ModelCapability.FUNCTION_CALLING,
                    ModelCapability.VISION,
                    ModelCapability.LONG_CONTEXT,
                ],
                context_window=200000,
                max_output_tokens=16000,
                priority=10,
                requires_api_key=True,
                is_local=False,
            ),
            ModelConfig(
                name="Claude Sonnet 4.5",
                provider=ModelProvider.ANTHROPIC,
                model_id="claude-sonnet-4-5-20250929",
                capabilities=[
                    ModelCapability.CODE_GENERATION,
                    ModelCapability.CODE_UNDERSTANDING,
                    ModelCapability.REASONING,
                    ModelCapability.CHAT,
                    ModelCapability.FUNCTION_CALLING,
                    ModelCapability.VISION,
                    ModelCapability.LONG_CONTEXT,
                ],
                context_window=200000,
                max_output_tokens=16000,
                priority=9,
                requires_api_key=True,
                is_local=False,
            ),

            # OpenAI models
            ModelConfig(
                name="GPT-4 Turbo",
                provider=ModelProvider.OPENAI,
                model_id="gpt-4-turbo-preview",
                capabilities=[
                    ModelCapability.CODE_GENERATION,
                    ModelCapability.CODE_UNDERSTANDING,
                    ModelCapability.REASONING,
                    ModelCapability.CHAT,
                    ModelCapability.FUNCTION_CALLING,
                ],
                context_window=128000,
                max_output_tokens=4096,
                priority=8,
                requires_api_key=True,
                is_local=False,
            ),

            # Google models
            ModelConfig(
                name="Gemini Pro",
                provider=ModelProvider.GOOGLE,
                model_id="gemini-pro",
                capabilities=[
                    ModelCapability.CODE_GENERATION,
                    ModelCapability.REASONING,
                    ModelCapability.CHAT,
                ],
                context_window=32000,
                max_output_tokens=8192,
                priority=7,
                requires_api_key=True,
                is_local=False,
            ),

            # Local LM Studio models (examples - these depend on what's loaded)
            ModelConfig(
                name="LM Studio - Default",
                provider=ModelProvider.LOCAL_LMSTUDIO,
                model_id="local-model",  # Will be determined by what's loaded
                capabilities=[
                    ModelCapability.CODE_GENERATION,
                    ModelCapability.CHAT,
                ],
                context_window=8192,
                max_output_tokens=2048,
                priority=6,
                requires_gpu=True,
                vram_required_gb=8.0,
                is_local=True,
            ),
        ]

        for model in models:
            self.models[model.name] = model

    def _load_config(self, config_path: Path):
        """Load custom model configurations from JSON."""
        try:
            with open(config_path) as f:
                config = json.load(f)
                # TODO: Parse and add custom models
        except Exception as e:
            print(f"Failed to load model config: {e}")

    def get_best_model(
        self,
        capability: ModelCapability,
        prefer_local: bool = False,
        max_cost: Optional[float] = None,
        min_context: Optional[int] = None,
    ) -> Optional[ModelConfig]:
        """
        Get the best available model for a capability.

        Args:
            capability: Required model capability
            prefer_local: Prefer local models over API models
            max_cost: Maximum cost per million tokens
            min_context: Minimum context window size

        Returns:
            Best available model or None
        """
        candidates = [
            model for model in self.models.values()
            if capability in model.capabilities
        ]

        # Filter by cost
        if max_cost is not None:
            candidates = [
                m for m in candidates
                if m.cost_per_million_tokens is None or m.cost_per_million_tokens <= max_cost
            ]

        # Filter by context window
        if min_context is not None:
            candidates = [m for m in candidates if m.context_window >= min_context]

        # Filter by GPU availability for local models
        candidates = [
            m for m in candidates
            if not m.requires_gpu or (self.gpu_info and self.has_sufficient_vram(m))
        ]

        if not candidates:
            return None

        # Sort by preference
        if prefer_local:
            # Local models first, then by priority
            candidates.sort(key=lambda m: (not m.is_local, -m.priority))
        else:
            # Just by priority
            candidates.sort(key=lambda m: -m.priority)

        return candidates[0]

    def has_sufficient_vram(self, model: ModelConfig) -> bool:
        """
        Check if GPU has sufficient VRAM for model.

        Args:
            model: Model to check

        Returns:
            True if sufficient VRAM available
        """
        if not self.gpu_info or not model.vram_required_gb:
            return False
        return self.gpu_info.vram_available_gb >= model.vram_required_gb

    def get_available_models(
        self,
        capability: Optional[ModelCapability] = None,
        local_only: bool = False,
    ) -> List[ModelConfig]:
        """
        Get all available models.

        Args:
            capability: Filter by capability
            local_only: Only return local models

        Returns:
            List of available models
        """
        models = list(self.models.values())

        if capability:
            models = [m for m in models if capability in m.capabilities]

        if local_only:
            models = [m for m in models if m.is_local]

        models.sort(key=lambda m: -m.priority)
        return models

    def register_model(self, model: ModelConfig):
        """
        Register a new model.

        Args:
            model: ModelConfig to register
        """
        self.models[model.name] = model

    def get_gpu_status(self) -> Dict:
        """
        Get GPU status information.

        Returns:
            Dictionary with GPU info
        """
        if not self.gpu_info:
            return {"available": False}

        return {
            "available": True,
            "name": self.gpu_info.name,
            "vram_total_gb": self.gpu_info.vram_total_gb,
            "vram_available_gb": self.gpu_info.vram_available_gb,
            "compute_capability": self.gpu_info.compute_capability,
            "cuda_version": self.gpu_info.cuda_version,
        }

    def get_model_recommendations(
        self,
        task_description: str,
        prefer_local: bool = False,
    ) -> List[tuple[ModelConfig, str]]:
        """
        Get model recommendations for a task with explanations.

        Args:
            task_description: Description of the task
            prefer_local: Prefer local models

        Returns:
            List of (model, reason) tuples
        """
        # Simple keyword-based matching for now
        # TODO: Could use embeddings/semantic search in the future

        recommendations = []

        # Check for keywords
        task_lower = task_description.lower()

        if any(kw in task_lower for kw in ["code", "program", "script", "function"]):
            model = self.get_best_model(ModelCapability.CODE_GENERATION, prefer_local)
            if model:
                recommendations.append((model, "Best for code generation tasks"))

        if any(kw in task_lower for kw in ["math", "calculate", "solve"]):
            model = self.get_best_model(ModelCapability.MATH, prefer_local)
            if model:
                recommendations.append((model, "Best for mathematical reasoning"))

        if any(kw in task_lower for kw in ["reason", "think", "analyze"]):
            model = self.get_best_model(ModelCapability.REASONING, prefer_local)
            if model:
                recommendations.append((model, "Best for complex reasoning"))

        # Default to general chat capability
        if not recommendations:
            model = self.get_best_model(ModelCapability.CHAT, prefer_local)
            if model:
                recommendations.append((model, "General purpose model"))

        return recommendations
