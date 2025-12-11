# llm-models

Utility helpers for selecting and downloading quantized coding models that run comfortably on a workstation-class GPU (e.g., RTX 5090).  The package exposes a small registry describing a curated list of Hugging Face releases and includes helpers that:

- Select the best model for a given task type and VRAM budget
- Download the requested `.gguf` checkpoint (plus tokenizer assets) into a local cache directory
- Provide metadata about recommended usage, quantization details, and context limits

## Curated Models

| Name | Hugging Face Repo | File | Params | Context | Quantization | Recommended VRAM (GB) | Notes |
| ---- | ----------------- | ---- | ------ | ------- | ------------ | --------------------- | ----- |
| Qwen2.5-Coder-32B-Instruct Q4_K_M | `Qwen/Qwen2.5-Coder-32B-Instruct-GGUF` | `Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf` | 32B | 32k | Q4_K_M | 28 | Strong coding + reasoning mix, high pass@1 benchmarks |
| DeepSeek-Coder-V2-Lite-Instruct Q4_K_M | `deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct-GGUF` | `DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf` | 16B | 32k | Q4_K_M | 20 | Excellent structured reasoning, competitive HumanEval |
| CodeLlama-34B-Instruct Q4_K_M | `TheBloke/CodeLlama-34B-Instruct-GGUF` | `codellama-34b-instruct.Q4_K_M.gguf` | 34B | 16k | Q4_K_M | 22 | Still strong for tool creation, broad ecosystem support |
| CodeQwen1.5-14B-Chat Q4_K_M | `Qwen/CodeQwen1.5-14B-Chat-GGUF` | `codeqwen1.5-14b-chat-q4_k_m.gguf` | 14B | 32k | Q4_K_M | 16 | Fast fallback when memory-constrained, good agentic coding |

The registry captures benchmark-informed capability scores so that higher-performing models (for coding and multi-step reasoning) are preferred whenever sufficient VRAM is available.

## Quick Usage

```python
from llm_models.registry import ModelAssignmentManager

manager = ModelAssignmentManager()
spec = manager.select_model(task="coding", max_vram_gb=32)
model_path = manager.download_model(spec.name)
print(f"Ready to load {spec.name} from {model_path}")
```

Environment variables:

- `LLM_MODELS_CACHE`: overrides the download directory (default `~/.cache/llm_models`)
- `LLM_MAX_VRAM_GB`: manual VRAM override when auto-detection is not available
- `HF_TOKEN`: personal access token for private Hugging Face downloads

See `llm_models/registry.py` for the complete API.
