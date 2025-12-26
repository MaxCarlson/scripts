# Multi-Agent Memory-Aware Orchestration System: Research Blueprint

Your $0-API-budget constraint with CLI subscriptions creates a unique architecture opportunity. This research synthesizes findings across all five domains to inform your 10 implementation documents—covering CLI integration, local model deployment on RTX 5090, multi-agent memory with Qdrant, consensus systems, and CrewAI patterns.

## Critical discovery: subscription vs API access

**ChatGPT Plus ($20/month)** provides web interface access and the new **Codex CLI** (included with subscription), but NOT standard API access. **Claude Pro ($20/month)** works directly with the **Claude Code CLI**—your best programmatic option. **Gemini CLI** offers a generous free tier (1,000 requests/day) requiring only a Google account. This means your architecture should prioritize Claude Code CLI for agentic coding tasks, Gemini CLI as a free fallback, and OpenAI's Codex CLI for interactive development.

---

## CLI integration architecture

### Claude Code CLI: your primary agentic interface

Claude Code CLI provides the richest programmatic integration for your subscription:

```bash
# Non-interactive execution with JSON output
claude -p "Refactor this module for testability" --output-format json --max-turns 5

# With model fallback for rate limits
claude -p "Analyze codebase" --fallback-model sonnet --output-format stream-json

# Subagent configuration for specialized tasks
claude --agents '{
  "code-reviewer": {
    "description": "Expert code reviewer",
    "prompt": "You are a senior code reviewer focusing on Python best practices",
    "tools": ["Read", "Grep", "Glob", "Bash"],
    "model": "sonnet"
  }
}'
```

**Session persistence** works via the `-c` flag (continue last conversation) or `-r <session-id>` for specific sessions. Rate limits are variable based on server load for Pro subscriptions—your wrapper should detect `429` responses and implement exponential backoff.

### MCP server integration for tool orchestration

Both Claude Code and Gemini CLI support the Model Context Protocol. Configure in `~/.claude.json`:

```json
{
  "mcpServers": {
    "qdrant": {
      "command": "python",
      "args": ["-m", "qdrant_mcp_server"],
      "env": { "QDRANT_URL": "http://localhost:6333" }
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "..." }
    }
  }
}
```

### Gemini CLI: your free-tier fallback

Gemini CLI offers **60 requests/minute and 1,000 requests/day** on the free tier with just a Google account—no API key required for basic usage. The 1M token context window makes it excellent for large codebase analysis:

```bash
gemini -p "Analyze the architecture of this repository" --output-format json
```

### Unified wrapper with LiteLLM

For programmatic access when you do have API credits, LiteLLM provides the cleanest abstraction:

```python
from litellm import Router

router = Router(
    model_list=[
        {"model_name": "claude", "litellm_params": {"model": "anthropic/claude-3-5-sonnet", "rpm": 50}},
        {"model_name": "gemini", "litellm_params": {"model": "gemini/gemini-2.5-flash", "rpm": 60}},
        {"model_name": "local", "litellm_params": {"model": "openai/qwen-32b", "base_url": "http://localhost:8080/v1"}}
    ],
    fallbacks=[{"claude": ["gemini", "local"]}, {"gemini": ["local"]}],
    num_retries=3, retry_after=5, cooldown_time=60
)
```

---

## Local model deployment for 32GB VRAM

### Model selection: Qwen2.5-Coder dominates

Your RTX 5090's **32GB GDDR7 at 1.79TB/s** enables running state-of-the-art code models. After benchmarking analysis, **Qwen2.5-Coder** is the clear winner across both model tiers:

| Role | Model | VRAM (Q4_K_M) | HumanEval+ | Context | Use Case |
|------|-------|---------------|------------|---------|----------|
| **Large** | Qwen2.5-Coder-32B-Instruct | ~18-19GB | **86.0%** | 128K | Complex analysis, architecture review |
| **Quick** | Qwen2.5-Coder-7B-Instruct | ~5GB (Q6_K: 7GB) | Best-in-class for size | 128K | Fast edits, inline suggestions |

The 32B model ties GPT-4o on HumanEval+ while the 7B model outperforms models 3-5x its size. Both offer **128K context**—8x longer than legacy options like Phind-CodeLlama-34B (16K context).

### Quantization strategy for RTX 5090

**GGUF with Q4_K_M** provides the best quality/size tradeoff for your setup. For the RTX 5090's Blackwell architecture, ensure you're running CUDA 12.8+ and PyTorch 2.5+:

```bash
# Download pre-quantized models
huggingface-cli download bartowski/Qwen2.5-Coder-32B-Instruct-GGUF \
  Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf --local-dir ./models

huggingface-cli download bartowski/Qwen2.5-Coder-7B-Instruct-GGUF \
  Qwen2.5-Coder-7B-Instruct-Q6_K.gguf --local-dir ./models
```

### Multi-model serving with llama-swap

**llama-swap** is the optimal solution for your single-GPU multi-model architecture—a lightweight Go binary that hot-swaps llama.cpp servers behind an OpenAI-compatible API:

```yaml
# llama-swap config.yaml
healthCheckTimeout: 120

models:
  "qwen2.5-coder-32b":
    cmd: >
      llama-server --port 8999 
      --model /models/Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf 
      --n-gpu-layers 99 --ctx-size 16384 --parallel 2
    proxy: http://127.0.0.1:8999
    aliases: ["gpt-4", "large"]
    ttl: 600  # Unload after 10 min idle

  "qwen2.5-coder-7b":
    cmd: >
      llama-server --port 8998 
      --model /models/Qwen2.5-Coder-7B-Instruct-Q6_K.gguf 
      --n-gpu-layers 99 --ctx-size 8192 --parallel 4
    proxy: http://127.0.0.1:8998
    aliases: ["gpt-3.5-turbo", "fast"]
    ttl: 0  # Never unload

groups:
  always-on:
    swap: false
    members: ["qwen2.5-coder-7b"]
```

**Expected performance on RTX 5090:**
- Qwen2.5-Coder-32B Q4_K_M: ~40-60 tokens/sec
- Qwen2.5-Coder-7B Q6_K: ~200-300 tokens/sec
- Model swap time: ~5-15 seconds

**VRAM allocation:**
- Small model (always loaded): ~7GB
- Large model (on-demand): ~19GB
- KV cache + overhead: ~6GB
- **Total: ~32GB** ✓

---

## Multi-agent memory architecture with Qdrant

### Lessons from existing implementations

Four distinct memory patterns emerged from production multi-agent systems:

| System | Pattern | Key Innovation |
|--------|---------|----------------|
| **AutoGPT** | Retrieval-based | Stores agent-tool interactions as embeddings, not just user-agent |
| **BabyAGI** | Task queue + vector DB | Retrieves relevant past tasks to prevent repetition |
| **MetaGPT** | Subscription-based | Agents subscribe to message types based on role profiles |
| **MemGPT** | OS-inspired tiers | Self-managing memory with virtual context and strategic forgetting |

For your CrewAI + Qdrant stack, **combine MetaGPT's subscription model with MemGPT's hierarchical tiers**.

### Qdrant collection design for RBAC

Use a single collection with payload-based multitenancy and access control:

```python
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

# Create collection with tenant-optimized indexing
client.create_collection(
    collection_name="crewai_agent_memory",
    vectors_config=models.VectorParams(size=1536, distance=models.Distance.COSINE),
    hnsw_config=models.HnswConfigDiff(payload_m=16, m=0),  # Tenant-only indexing
)

# Create tenant index for performance
client.create_payload_index(
    collection_name="crewai_agent_memory",
    field_name="group_id",
    field_schema=models.KeywordIndexParams(
        type=models.KeywordIndexType.KEYWORD,
        is_tenant=True,  # Vectors of same tenant stored together
    ),
)
```

**Payload schema for hierarchical access control:**

```python
MEMORY_PAYLOAD = {
    "group_id": str,        # Primary tenant (project/organization)
    "access_level": str,    # "public" | "project" | "team" | "private" | "admin"
    "memory_type": str,     # "raw" | "task_summary" | "project_summary" | "global"
    "agent_id": str,        # Creating agent
    "user_id": str,         # Owning user (for private memories)
    "crew_id": str,         # CrewAI crew identifier
    "summary_level": int,   # 1=raw, 2=task, 3=project, 4=global
    "content": str,         # Memory content
    "created_at": str,      # ISO timestamp
}
```

**Query with access control enforcement:**

```python
def query_agent_memory(query_vector, user_id, project_id, access_levels):
    return client.query_points(
        collection_name="crewai_agent_memory",
        query=query_vector,
        query_filter=models.Filter(
            must=[models.FieldCondition(key="group_id", match=models.MatchValue(value=project_id))],
            should=[
                models.FieldCondition(key="access_level", match=models.MatchValue(value="public")),
                models.FieldCondition(key="access_level", match=models.MatchValue(value="team")),
                models.Filter(must=[
                    models.FieldCondition(key="access_level", match=models.MatchValue(value="private")),
                    models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))
                ])
            ]
        ),
        limit=10
    )
```

### Hierarchical summarization for context management

Implement four-level progressive summarization to manage context across agent handoffs:

```
Level 4: GLOBAL SUMMARY    → "Team achieved 80% accuracy on ML pipeline"
Level 3: PROJECT SUMMARY   → "Completed data preprocessing, model training"  
Level 2: TASK SUMMARY      → "Cleaned dataset, removed 15% outliers"
Level 1: RAW INTERACTIONS  → Individual agent messages and tool calls
```

**Summarization triggers at 70% context utilization**, retaining the most recent 30% of raw interactions while compressing older content. A **6:1 compression ratio** is achievable with semantic summarization while preserving key facts, numbers, and decisions.

---

## Multi-model review and consensus systems

### Voting algorithm selection

For code review aggregation, **weighted voting with confidence scores** outperforms simple majority voting:

```python
def weighted_code_review(reviews, model_weights):
    issue_scores = {}
    for review, weight in zip(reviews, model_weights):
        for issue in review.issues:
            key = normalize_issue(issue)
            if key not in issue_scores:
                issue_scores[key] = {"votes": 0, "severity": [], "confidence": []}
            issue_scores[key]["votes"] += weight
            issue_scores[key]["severity"].append(issue.severity)
            issue_scores[key]["confidence"].append(issue.confidence)
    
    # Filter to high-agreement issues
    threshold = sum(model_weights) * 0.6  # 60% weighted agreement
    return [issue for issue, data in issue_scores.items() if data["votes"] >= threshold]
```

**Research-backed improvements:**
- Self-consistency sampling (+17% accuracy on reasoning tasks)
- **Multi-Agg pattern** from SWR-Bench: aggregating reviews from multiple distinct models improves F1 by **43.67%** and recall by **118%**

### Auto-approve decision matrix

| Condition | Action |
|-----------|--------|
| All models agree (100%), confidence >0.9, no high-severity | **Auto-approve** |
| Majority agree (>66%), confidence 0.7-0.9, severity ≤5 | **Auto-approve with note** |
| Split decision (50-66%), any confidence | **Human review** |
| Any high-severity (≥8) flagged | **Human review required** |
| Security-related flag by any model | **Mandatory human review** |

### Git pre-commit integration

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: multi-model-review
        name: Multi-Model Code Review
        entry: python scripts/multi_model_review.py
        language: python
        types: [python]
        stages: [pre-commit, pre-push]
```

The review script should run models in parallel, aggregate using weighted voting, and block commits only on high-confidence, high-severity issues flagged by multiple models.

---

## CrewAI framework integration

### Hierarchical delegation configuration

```python
from crewai import Crew, Process, Agent, Task

# Worker agents (allow_delegation=False)
researcher = Agent(
    role="Code Analyst",
    goal="Analyze codebase structure and dependencies",
    allow_delegation=False,
    llm="ollama/qwen2.5-coder:7b"  # Quick local model
)

architect = Agent(
    role="Architecture Reviewer", 
    goal="Evaluate architectural decisions",
    allow_delegation=False,
    llm="ollama/qwen2.5-coder:32b"  # Large local model for complex analysis
)

# Hierarchical crew with manager
crew = Crew(
    agents=[researcher, architect],
    tasks=[analysis_task, review_task],
    process=Process.hierarchical,
    manager_llm="anthropic/claude-3-5-sonnet",  # Use Claude for orchestration via API
    memory=True,
    planning=True
)
```

### Custom tool integration for your knowledge_manager

Wrap your existing Python module as CrewAI tools:

```python
from crewai.tools import tool
from knowledge_manager import KnowledgeManager

km = KnowledgeManager()

@tool("Query Knowledge Base")
def query_knowledge(query: str) -> str:
    """Search the project knowledge base for relevant information.
    Use this for finding documentation, past decisions, and code patterns."""
    results = km.semantic_search(query, limit=5)
    return "\n".join([f"- {r.content} (score: {r.score:.2f})" for r in results])

@tool("Store Knowledge")
def store_knowledge(content: str, category: str) -> str:
    """Store new knowledge in the project knowledge base.
    Categories: decision, pattern, documentation, note"""
    doc_id = km.store(content, metadata={"category": category})
    return f"Stored as document {doc_id}"

agent = Agent(
    role="Knowledge Worker",
    tools=[query_knowledge, store_knowledge]
)
```

### Memory configuration with local embeddings

Use Ollama for free local embeddings to avoid API costs:

```python
crew = Crew(
    agents=[...],
    tasks=[...],
    memory=True,
    embedder={
        "provider": "ollama",
        "config": {
            "model": "nomic-embed-text",
            "url": "http://localhost:11434/api/embeddings"
        }
    }
)
```

---

## Recommended implementation roadmap

Based on dependencies and risk factors, prioritize implementation in this order:

1. **Local model deployment** (Week 1-2)
   - Install llama.cpp with CUDA 12.8+, download Qwen2.5-Coder models
   - Configure llama-swap for multi-model serving
   - Verify performance benchmarks on RTX 5090

2. **CLI wrapper layer** (Week 2-3)
   - Build unified Python wrapper for Claude Code CLI, Gemini CLI, and local models
   - Implement rate limit detection and fallback logic
   - Add structured output parsing (JSON mode)

3. **Qdrant memory system** (Week 3-4)
   - Deploy Qdrant, create collection with RBAC schema
   - Implement hierarchical summarization pipeline
   - Build CrewAI memory backend integration

4. **CrewAI orchestration** (Week 4-5)
   - Define agent roles and tool bindings
   - Configure hierarchical process with manager
   - Integrate memory backend

5. **Multi-model review system** (Week 5-6)
   - Implement weighted voting aggregation
   - Build Git pre-commit hook integration
   - Configure auto-approve thresholds

6. **Observability and DX** (Week 6-7)
   - Add monitoring for memory operations
   - Build TUI for agent interaction
   - Implement cost tracking (local vs CLI usage)

---

## Key technical risks and mitigations

| Risk | Mitigation |
|------|------------|
| RTX 5090 software compatibility | Test with CUDA 12.8+ and latest llama.cpp builds before production |
| Claude Pro rate limits variable | Implement aggressive caching, use Gemini free tier as backup |
| Qdrant payload filtering performance | Set `is_tenant=True` on group_id index, benchmark with realistic data |
| Context window pressure with 32B model | Keep context under 16K tokens, use summarization proactively |
| CrewAI version API changes | Pin version in requirements.txt, test tool imports carefully |

---

## Resource reference summary

| Component | Recommended Solution | Documentation |
|-----------|---------------------|---------------|
| CLI orchestration | Claude Code CLI + Gemini CLI | code.claude.com/docs, geminicli.com |
| Unified API | LiteLLM Router | docs.litellm.ai/docs/routing |
| Large code model | Qwen2.5-Coder-32B-Instruct Q4_K_M | huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct |
| Quick edit model | Qwen2.5-Coder-7B-Instruct Q6_K | huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct |
| Multi-model serving | llama-swap | github.com/mostlygeek/llama-swap |
| Vector database | Qdrant (local or cloud) | qdrant.tech/documentation |
| Agent framework | CrewAI | docs.crewai.com |
| Local embeddings | nomic-embed-text via Ollama | ollama.ai |

This research provides the technical foundation for all 10 implementation documents. The architecture optimizes for your $0 API budget by maximizing local model usage while strategically leveraging CLI subscriptions for complex orchestration tasks that benefit from frontier model capabilities.