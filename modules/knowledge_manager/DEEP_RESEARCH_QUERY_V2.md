# Deep Research Query: Multi-Agent Memory-Aware Orchestration System v2

**Date**: 2025-12-23
**Purpose**: Research and planning for a meta-agent orchestration system leveraging subscription CLI tools (ChatGPT CLI, Claude Code, Google CLI) with local RTX 5090 backup, hierarchical memory, and role-based access control.

---

## Executive Summary

Design a comprehensive implementation plan for transforming the existing `knowledge_manager` module into a **meta-agent orchestration platform** that:

1. **Prioritizes subscription CLI tools** as primary LLM interfaces (ChatGPT CLI, Claude Code, Google CLI)
2. **Uses local RTX 5090 (32GB VRAM)** for supplementary workloads and cost-free operations
3. **Implements hierarchical memory** with role-based access control
4. **Orchestrates multiple specialist agents** using CrewAI framework
5. **Provides seamless integration** with 30+ existing Python modules
6. **Operates within $0 API budget** (relies on $60/month subscriptions)
7. **Supports optional "turbo mode"** for premium API access when needed

---

## System Constraints & Resources

### Hardware Specifications

**GPU**:
- RTX 5090: **32GB VRAM**
- Supports concurrent model loading
- Target: 2 local models (large codebase understanding + small quick edits)

**System**:
- 64GB DDR5 RAM @ 6000MHz
- WSL2 + Windows 11 environment
- Termux (Android) for secondary testing

### Subscription Services (Primary LLM Access)

**Available CLI Tools** (~$60/month total):
1. **ChatGPT CLI** (via ChatGPT Plus $20/month)
   - Limited usage
   - GPT-4 Turbo access
   - Superior to local models for complex reasoning

2. **Claude Code CLI** (via Claude subscription $20/month)
   - Limited usage
   - Claude 3.5 Sonnet access
   - Excellent for code generation/refactoring

3. **Google CLI** (via Google subscription $20/month)
   - Limited usage
   - Gemini Pro access
   - Good for research/web integration

**Strategy**: These CLIs are **primary interfaces** - they outperform accessible local models for most tasks.

### API Budget

**Standard Operations**: $0/month
- Rely entirely on subscription CLI limits
- Use local models when CLI limits exhausted
- No direct API calls unless "turbo mode" enabled

**Turbo Mode** (Stretch Goal):
- User-enabled for critical tasks
- Direct API access (OpenAI/Anthropic/Google APIs)
- Uses premium models (GPT-4o, Claude Opus, etc.)
- User pays per-use

### Local Model Strategy

**Purpose**: Supplement subscription CLIs, not replace them

**Two-Model System**:

1. **Large Codebase Model** (Priority 1):
   - Target: DeepSeek-Coder-33B-instruct (4-bit) or similar
   - Purpose: Understand entire repositories, architectural analysis
   - VRAM: ~18-20GB (4-bit quantization)
   - Use when: Need to process 10k+ lines of context

2. **Small Quick-Edit Model** (Priority 2):
   - Target: CodeLlama-13B-instruct (4-bit) or StarCoder2-15B
   - Purpose: Local refactoring, quick fixes, syntax corrections
   - VRAM: ~8-10GB (4-bit quantization)
   - Use when: Simple edits, offline mode, fast iteration

**Concurrent Loading**: With 32GB VRAM, both models can run simultaneously (~28GB total)

**Quantization Preferences**:
- 4-bit GPTQ/AWQ for size efficiency
- Occasional ablated models for specialized tasks
- Embedding model: bge-large-en-v1.5 (~1GB)

### Performance Requirements

**Configurable Performance Modes**:

- **Fast Mode**: Small local model only (~1-2s latency)
- **Balanced Mode**: CLI tools when available, local when rate-limited
- **Deep Mode**: Large local model + CLI tools in parallel
- **Turbo Mode**: Premium API models (user pays per-use)

**User Control**:
- CLI flag: `km orchestrate --perf-mode [fast|balanced|deep|turbo]`
- Per-task override in TUI
- Global config default

---

## Current State Analysis

### Existing Infrastructure

**Location**: `C:\Users\mcarls\src\scripts\modules\`

**Repository Structure**:
```
scripts/
├── modules/
│   ├── knowledge_manager/      ← PRIMARY: Core memory/task system
│   ├── agt/                    ← TUI agent interface (Gemini)
│   ├── llm-patcher/            ← LLM-driven code patching
│   ├── llm-interface/          ← API abstraction layer
│   ├── llm-models/             ← Model registry
│   ├── llm-manager/            ← LLM lifecycle management
│   ├── lmstui/                 ← LLM TUI components
│   ├── cross_platform/         ← Platform utilities
│   ├── standard_ui/            ← Terminal UI components
│   ├── file_utils/             ← File operations
│   └── [30+ other modules]     ← Reusable utilities
```

### Existing Planning Documents

**Reviewed Files** (knowledge_manager/):
- `research.md` - Technology research (LLM runtimes, vector DBs, orchestration)
- `plans.md` - 8-stage roadmap (partially specified)
- `IMPLEMENTATION_STATUS.md` - Cross-project linking features
- `TODOS.md` - Feature roadmap for task management

**Current Vision**:
1. **Stage 1**: Architecture skeleton (orchestrator layer)
2. **Stage 2**: Local LLM runtime (vLLM/TGI on RTX 5090)
3. **Stage 3**: Vector DB integration (Qdrant)
4. **Stage 4**: Hierarchical memory layer
5. **Stage 5**: Agent orchestration (CrewAI framework)
6. **Stage 6**: Routing & meta-controller
7. **Stage 7**: Model registry & policies
8. **Stage 8**: Deployment & developer experience

**Planned Agent Roles**:
- `ProjectManagerAgent` - Task planning and delegation
- `CodingAgent` - Code implementation/refactoring
- `TestingAgent` - Test execution and validation
- `ResearchAgent` - External documentation/web research
- `WritingAgent` - Documentation generation

**Technology Decisions**:
- **Vector DB**: Qdrant (payload filtering, Docker deployment)
- **Orchestration**: CrewAI (hierarchical delegation)
- **Embedding**: BAAI bge-large-en-v1.5 (768 dims)

**Memory Schema**:
```python
# Qdrant payload structure
{
    "project_id": int,
    "task_id": int,
    "type": str,  # raw_interaction, task_summary, project_summary,
                   # design_doc, code_snippet, handoff_summary
    "agent": str,
    "created_at": str  # ISO8601
}
```

---

## Research Focus Areas

### Gap 1: CLI Tool Integration Strategy

**Current State**: Plans assume direct API access; need to adapt for CLI tool limitations.

**Missing**:
- How to invoke ChatGPT CLI, Claude Code CLI, Google CLI from orchestrator?
- Rate limit detection and fallback logic?
- CLI output parsing (different formats per tool)?
- Session management (persistent contexts vs. one-shot calls)?
- How to track usage against subscription limits?

**Research Questions**:
1. What are the exact CLI interfaces for each tool?
   - ChatGPT CLI: Command syntax, input/output format, session handling
   - Claude Code CLI: Tool use, file operations, streaming
   - Google CLI: API compatibility, feature set
2. How to detect when subscription limits are hit?
3. Best fallback strategy: Queue tasks until limit resets vs. switch to local models?
4. Can CLIs be wrapped to provide unified interface?
5. How to handle tool-specific features (Claude Code's MCP servers, etc.)?

**Desired Output**:
- CLI integration architecture diagram
- Unified wrapper interface design
- Rate limit tracking system
- Fallback decision tree
- Example: CodingAgent → Claude Code CLI → local model fallback

---

### Gap 2: Local Model Deployment for 32GB VRAM

**Current State**: Research assumes 24GB VRAM; need updated architecture for 32GB.

**Missing**:
- Exact model selection for large + small models
- Concurrent loading strategy (both models always loaded?)
- Model swapping logic (when to unload/reload?)
- Quantization format selection (GPTQ vs AWQ vs GGUF)
- vLLM vs TGI vs llama.cpp for multi-model serving

**Research Questions**:
1. **Large Model Candidates** (for 32GB VRAM):
   - DeepSeek-Coder-33B-instruct (4-bit): ~18GB
   - CodeLlama-34B-instruct (4-bit): ~19GB
   - WizardCoder-33B-v1.1 (4-bit): ~18GB
   - Phind-CodeLlama-34B-v2 (4-bit): ~19GB
   - Which performs best for codebase understanding?

2. **Small Model Candidates**:
   - CodeLlama-13B-instruct (4-bit): ~8GB
   - StarCoder2-15B (4-bit): ~9GB
   - DeepSeek-Coder-6.7B (4-bit): ~5GB
   - Which balances speed + quality for quick edits?

3. **Concurrent Loading**:
   - Large (18GB) + Small (8GB) + Embedding (1GB) = 27GB
   - Leaves 5GB for CUDA overhead - feasible?
   - Performance impact of concurrent serving?

4. **Serving Framework**:
   - vLLM: Great concurrency, but one model per server
   - TGI: Multi-model support, enterprise features
   - llama.cpp: Lightweight, GGUF support
   - Which best supports 2 concurrent models + CLI fallback?

5. **Quantization**:
   - GPTQ (fast inference, GPU-only)
   - AWQ (slightly slower, better quality)
   - GGUF (llama.cpp, flexible layers)
   - Which for each model type?

**Desired Output**:
- Model selection with benchmarks (inference speed, quality)
- VRAM budget breakdown (27/32GB utilization)
- Docker compose configuration (dual-model serving)
- Model loading strategy (static vs. dynamic)
- Quantization recommendations per model

---

### Gap 3: Memory Access Control by Agent Role

**Current State**: Memory stores `agent` field but no access scoping defined.

**Missing**:
- Which agents can read which memory types?
- Should CodingAgent see ResearchAgent's web research?
- How to prevent memory pollution across agent domains?
- Privacy/segmentation rules for multi-project environments?

**Research Questions**:
1. What are best practices for role-based memory access in multi-agent systems?
2. Should memory filtering happen at query-time (Qdrant filters) or application-layer (Python middleware)?
3. How to balance context richness vs. focused agent workspaces?
4. Should certain memory types be read-only for specific agents?
5. How to handle cross-agent handoffs (temporary permission elevation)?

**Example Scenarios**:
- CodingAgent fixing a bug: Needs `code_snippet` + `task_summary`, maybe NOT `research_doc`
- ResearchAgent gathering context: Needs `project_summary` + `research_doc`, maybe NOT raw `code_snippet`
- ProjectManagerAgent planning: Needs ALL memory types (supervisor access)

**Desired Output**:
- Memory access policy matrix (agent roles × memory types)
- Implementation strategy (Qdrant payload filters vs. middleware)
- Configuration schema (YAML with permissions)
- Edge case handling (manager override, handoff protocol)
- Example queries with access control applied

---

### Gap 4: CLI Tool Routing & Cost Optimization

**Current State**: No clear strategy for when to use which CLI tool.

**Missing**:
- Decision algorithm: ChatGPT CLI vs. Claude Code CLI vs. Google CLI vs. local?
- Task-to-tool mapping (which agent uses which CLI?)
- Subscription limit tracking (remaining quota per tool)
- "Turbo mode" implementation (when to pay for premium API)

**Research Questions**:
1. **Tool Selection Heuristics**:
   - ChatGPT CLI: Best for reasoning/planning tasks? (ProjectManagerAgent)
   - Claude Code CLI: Best for code generation? (CodingAgent)
   - Google CLI: Best for research/web queries? (ResearchAgent)
   - Local models: Best for quick edits, offline, privacy?

2. **Limit Tracking**:
   - How to detect approaching subscription limits?
   - Should we estimate remaining quota or track actual usage?
   - Fallback strategy: Queue vs. local vs. turbo mode?

3. **Turbo Mode**:
   - User trigger: CLI flag, TUI button, task priority?
   - Which premium models: GPT-4o? Claude Opus? Both?
   - Cost estimation before execution?
   - Budget cap per task/project?

4. **Quality Feedback**:
   - Track success/failure per tool
   - Learn which tool works best for which tasks
   - Auto-adjust routing over time?

**Desired Output**:
- Routing decision tree (task type → tool selection)
- Subscription limit tracking design
- Turbo mode activation flow
- Cost estimation logic
- Quality feedback loop design

---

### Gap 5: Module Integration as Agent Tools

**Current State**: 30+ modules exist but no clear integration plan.

**Missing**:
- How should agents invoke existing modules?
  - `file_utils` for file operations
  - `llm-patcher` for code modifications
  - `cross_platform` for OS-specific tasks
  - `clipboard_tools` for data exchange
- Should agents call these as tools (CrewAI tool binding)?
- How to avoid duplication?

**Research Questions**:
1. What's the best pattern for exposing Python modules as agent tools?
2. Should each module have a manual tool wrapper, or auto-generate from docstrings?
3. How to handle module dependencies (some modules depend on each other)?
4. Should agents have direct imports, or go through a tool registry?
5. How do CLI tools interact with local modules (Claude Code can use filesystem)?

**Desired Output**:
- Module-to-tool mapping strategy
- Tool schema generation approach (manual vs. auto-generated)
- Example: CodingAgent using `llm-patcher` via Claude Code CLI
- Tool registry design (discovery, invocation, error handling)
- Dependency resolution for tool chains

---

### Gap 6: Hierarchical Memory Implementation Details

**Current State**: High-level design exists; low-level implementation missing.

**Missing**:
- Summarization triggers (token threshold? time-based? manual?)
- Summarization prompts (how to condense without losing critical info?)
- Handoff protocol (exact data structure for agent transitions)
- Memory compaction strategy (when to prune old raw interactions?)
- Query optimization (how to retrieve relevant memories efficiently?)

**Research Questions**:
1. What are proven summarization strategies for long-running agent tasks?
2. Which LLM should do summarization?
   - Local large model (free, slower)
   - CLI tool (limited quota, faster)
   - Dedicated small summarizer model
3. Should summaries be versioned (track what was summarized from what)?
4. How to implement "memory anchors" (preserve critical decisions verbatim)?
5. What's the optimal context window size for each agent role?
6. How to detect when a summary is losing critical information?

**Example Workflow**:
```
Task: "Implement new authentication system"
1. CodingAgent makes 50 interactions (10k tokens)
2. Trigger: Token threshold exceeded (>8k)
3. Summarization:
   - Send last 8k tokens to local large model
   - Prompt: "Summarize design decisions and progress"
   - Store as `task_summary` in Qdrant
   - Keep last 2k tokens as raw context
4. Handoff to TestingAgent:
   - Retrieve task_summary from memory
   - Inject into TestingAgent context
   - TestingAgent continues with compressed history
```

**Desired Output**:
- Summarization pipeline design (trigger → prompt → store → verify)
- Memory lifecycle state machine (raw → summary → archive → prune)
- Handoff data structure specification
- Query ranking algorithm (semantic + recency + importance)
- Summarization prompt templates

---

### Gap 7: Developer Experience & Observability

**Current State**: CLI and TUI exist for task management; agent interface undefined.

**Missing**:
- How do users interact with the orchestrator?
- How to monitor multi-agent collaboration?
- Debugging tools for failed tasks?
- Configuration management?

**Research Questions**:
1. **Orchestrator Interface**:
   - CLI: `km orchestrate --task-id <id> --perf-mode balanced`
   - TUI: Live dashboard with agent status?
   - API: HTTP server for external integrations?
   - Should orchestrator run as daemon or on-demand?

2. **Observability**:
   - What metrics matter?
     - Task completion time
     - CLI vs. local model usage ratio
     - Cost per task (for turbo mode)
     - Memory query count
   - Logging strategy:
     - Agent decision traces
     - Memory retrievals
     - Tool invocations
     - CLI responses

3. **Debugging Tools**:
   - Replay agent conversations
   - Inspect memory retrievals (what context was used?)
   - View routing decisions (why local vs. CLI?)
   - Simulate tasks without execution

4. **Configuration**:
   - Per-user settings (default perf mode, turbo budget)
   - Per-project overrides (always use CLI for critical projects)
   - Agent-specific configs (CodingAgent always uses Claude Code)

**Desired Output**:
- User interaction flow diagrams
- TUI dashboard mockup (agent status, memory stats, cost tracking)
- Logging architecture (structured logs, retention policy)
- Configuration file schema
- Debugging tool design (replay, inspect, simulate)

---

### Gap 8: Multi-Model Commit/PR Proofreading

**Current State**: Not explicitly planned; user identified as use case.

**Missing**:
- Architecture for multi-model validation
- When to trigger (pre-commit hook? manual command?)
- Which models to use (all 3 CLIs + local models?)
- How to aggregate feedback from multiple models?
- Integration with git workflow

**Research Questions**:
1. **Trigger Mechanism**:
   - Git pre-commit hook?
   - Manual: `km review-commit`
   - Automatic on PR creation?

2. **Model Selection**:
   - Use all available models (3 CLIs + 2 local)?
   - Parallel execution or sequential?
   - Aggregate strategy: Majority vote? Weighted consensus?

3. **Review Criteria**:
   - Code quality (linting, style, best practices)
   - Logic errors (bugs, edge cases)
   - Security vulnerabilities
   - Performance implications
   - Documentation completeness

4. **Output Format**:
   - Unified report (all models' feedback merged)
   - Per-model breakdown (see where models disagree)
   - Severity scoring (critical, warning, suggestion)
   - Auto-fix suggestions (if models agree on fix)

5. **Integration**:
   - Works with existing git hooks?
   - Compatible with GitHub/GitLab CI?
   - Local TUI for interactive review?

**Desired Output**:
- Multi-model review architecture
- Git integration strategy (hooks, commands)
- Aggregation algorithm (consensus, voting, weighted)
- Review report format (markdown, JSON, terminal output)
- Example workflow: `git commit` → multi-model review → approve/reject

---

## Research Deliverables

Produce the following planning documents:

### 1. `CLI_INTEGRATION_ARCHITECTURE.md`

**Contents**:
- CLI tool survey (ChatGPT CLI, Claude Code CLI, Google CLI)
- Unified wrapper interface design
- Rate limit tracking and detection
- Fallback logic (CLI → local model)
- Session management strategy
- Example: CodingAgent invoking Claude Code CLI with file context

**Format**: Markdown + architecture diagrams + Python pseudo-code

---

### 2. `LOCAL_MODEL_DEPLOYMENT_32GB.md`

**Contents**:
- Model recommendations (large + small for 32GB VRAM)
- VRAM budget analysis (concurrent loading feasibility)
- Quantization strategy (GPTQ vs AWQ vs GGUF)
- Serving framework comparison (vLLM vs TGI vs llama.cpp)
- Docker compose configuration
- Benchmarking plan (latency, throughput, quality)
- Model swapping logic (if needed)

**Format**: Markdown + docker-compose.yml + benchmark scripts

---

### 3. `MEMORY_ACCESS_POLICY.md`

**Contents**:
- Access control matrix (agent roles × memory types)
- Read/write permissions per agent
- Implementation approach (Qdrant filters vs. middleware)
- Configuration schema (YAML permissions)
- Edge cases (manager overrides, cross-agent handoffs)
- Example queries with access control applied

**Format**: Markdown + YAML schema + code examples

---

### 4. `ROUTING_AND_COST_OPTIMIZATION.md`

**Contents**:
- Routing decision algorithm (task → tool selection)
- CLI tool mapping (agent roles → preferred tools)
- Subscription limit tracking design
- Turbo mode implementation (trigger, cost estimation, budget caps)
- Quality feedback loop (track success/failure per tool)
- Performance mode implementation (fast/balanced/deep/turbo)
- Example: Route task through Claude Code CLI → local fallback

**Format**: Markdown + flowcharts + Python router pseudo-code

---

### 5. `MODULE_INTEGRATION_STRATEGY.md`

**Contents**:
- Survey of existing modules (file_utils, llm-patcher, cross_platform, etc.)
- Tool schema design (manual vs. auto-generated)
- Tool registry implementation
- Integration with CLI tools (how Claude Code accesses local modules)
- Dependency resolution for tool chains
- Example: CodingAgent using llm-patcher through Claude Code

**Format**: Markdown + JSON tool schemas + integration examples

---

### 6. `HIERARCHICAL_MEMORY_IMPLEMENTATION.md`

**Contents**:
- Detailed summarization pipeline (trigger → prompt → storage → validation)
- LLM selection for summarization (local vs. CLI)
- Memory lifecycle state machine
- Handoff protocol specification
- Query optimization strategy (vector search + metadata filters)
- Pruning and archival policies
- Summarization prompt templates
- Example: 100 interactions → 5 summaries → 1 project summary

**Format**: Markdown + state diagrams + prompt templates

---

### 7. `DEVELOPER_EXPERIENCE.md`

**Contents**:
- CLI commands for orchestrator (`km orchestrate`, `km review-commit`)
- TUI dashboard design (live agent status, memory stats, cost tracking)
- Configuration file schema (performance modes, agent preferences, turbo budget)
- Logging and observability stack (structured logs, metrics, traces)
- Debugging tools (replay conversations, inspect memory, simulate tasks)
- Performance mode implementation (fast/balanced/deep/turbo toggles)
- Example workflows

**Format**: Markdown + mockups + CLI examples

---

### 8. `MULTI_MODEL_REVIEW_SYSTEM.md`

**Contents**:
- Multi-model proofreading architecture
- Git integration strategy (pre-commit hooks, manual commands)
- Model orchestration (parallel execution, aggregation)
- Review criteria and scoring
- Output format (unified report, per-model breakdown)
- Auto-fix suggestions (when models agree)
- Example workflow: commit → review → approve/reject

**Format**: Markdown + git hook examples + aggregation algorithm

---

### 9. `UPDATED_PLANS.md`

**Contents**:
- Revised 8-stage roadmap with new stages:
  - **S2.5**: CLI tool integration (wrappers, rate limiting, fallbacks)
  - **S3.5**: Memory access control implementation
  - **S7.5**: Multi-model routing and cost tracking
  - **S9**: Module integration (tools binding)
  - **S10**: Monitoring and observability
  - **S11**: Multi-model review system
- Task breakdown for each stage (actionable, testable)
- Dependencies between stages
- Estimated complexity (trivial, moderate, complex)
- Links to detailed design docs

**Format**: Markdown matching existing `plans.md` structure

---

### 10. `FEASIBILITY_REPORT.md`

**Contents**:
- VRAM validation (can 32GB support dual models + embeddings?)
- CLI limit analysis (can subscription quotas handle expected usage?)
- Performance projections (latency, throughput per mode)
- Cost analysis (turbo mode usage estimates)
- Risk assessment (potential blockers, unknowns)
- Prototyping recommendations (what to test before full build)

**Format**: Markdown + charts + risk matrix

---

## Research Methodology

### Phase 1: External Research (1-2 hours)

**Research Topics**:
1. **CLI Tool Capabilities**:
   - ChatGPT CLI documentation (command syntax, features, limits)
   - Claude Code CLI documentation (MCP servers, tool use, file ops)
   - Google CLI documentation (API compatibility, features)
   - Rate limit behaviors and detection strategies

2. **Multi-agent memory systems**:
   - AutoGPT, BabyAGI, MetaGPT (how they handle shared memory)
   - Role-based access control patterns
   - Memory summarization techniques

3. **Model serving for 32GB VRAM**:
   - vLLM multi-model support
   - TGI concurrent model serving
   - llama.cpp multi-instance management
   - Benchmark data for DeepSeek-Coder, CodeLlama, StarCoder2

4. **Multi-model consensus**:
   - Voting algorithms (majority, weighted)
   - Conflict resolution strategies
   - Quality aggregation patterns

**Deliverable**: Annotated bibliography with key insights

---

### Phase 2: Architecture Design (3-4 hours)

**Tasks**:
1. Design CLI integration layer (unified wrappers, rate limiting)
2. Design local model deployment (Docker compose, 32GB VRAM budget)
3. Design memory access control system
4. Design routing & cost optimization (CLI → local fallback)
5. Design module → tool integration
6. Design hierarchical memory (summarization, handoffs)
7. Design developer experience (CLI/TUI/observability)
8. Design multi-model review system

**Deliverable**: 8 detailed design documents (listed above)

---

### Phase 3: Implementation Planning (1-2 hours)

**Tasks**:
1. Break down each design into implementation stages
2. Identify dependencies (what must be built first?)
3. Estimate complexity for each task
4. Map tasks to existing 8-stage roadmap (or add new stages)
5. Identify risky/unknown areas requiring prototyping

**Deliverable**: `UPDATED_PLANS.md` with actionable tasks

---

### Phase 4: Validation (1 hour)

**Tasks**:
1. VRAM budget validation (can dual models + embeddings fit in 32GB?)
2. CLI limit analysis (can subscription quotas handle expected usage?)
3. Performance estimation (latency for each mode)
4. Cost projection (turbo mode usage frequency)
5. Risk assessment (blockers, unknowns, prototyping needs)

**Deliverable**: `FEASIBILITY_REPORT.md` with risk assessment

---

## Success Criteria

Your research is successful if it produces:

1. **Complete design documents** (10 docs covering all gaps)
2. **Actionable roadmap** (`UPDATED_PLANS.md` with tasks)
3. **Feasibility validation** (VRAM budgets, CLI limits, performance projections)
4. **Clear next steps** (what to implement first?)

**Bonus Points**:
- Code examples (Python pseudo-code, YAML schemas, docker-compose)
- Diagrams (state machines, flowcharts, architecture)
- Trade-off analysis (design alternatives with pros/cons)
- Prototyping recommendations (what to test before full build)

---

## Key Design Principles

### Priority Hierarchy

1. **CLI Tools First**: ChatGPT CLI, Claude Code CLI, Google CLI are superior - use them by default
2. **Local Models as Backup**: Only when CLI limits hit or offline mode required
3. **Zero API Cost**: No direct API calls unless turbo mode explicitly enabled
4. **Performance Flexibility**: User controls speed vs. quality tradeoff
5. **Personal Projects Focus**: Optimize for solo developer workflow, not enterprise scale

### Technical Constraints

**Must Preserve**:
- Existing `knowledge_manager` SQLite schema (backward compatibility)
- CLI interface (`km` command with subcommands)
- TUI interface (`kmtui` for browsing tasks/projects)
- Cross-platform support (Windows 11, WSL2, Termux)

**Must Integrate With**:
- CrewAI framework (chosen orchestration layer)
- Qdrant (chosen vector database)
- Existing 30+ Python modules (reuse, don't duplicate)

**Must Support**:
- Offline mode (local models only)
- Hybrid mode (CLI + local with smart routing)
- Multi-project workflows
- Long-running tasks (days/weeks with persistent memory)
- Performance modes (fast/balanced/deep/turbo)

### Code Standards (from repository CLAUDE.md)

1. **Python arguments**: ALL must have short + long forms (`-v, --verbose`)
2. **Test naming**: `module_name_test.py` (not `test_module.py`)
3. **File output**: COMPLETE files, no truncation
4. **Platform compatibility**: Handle Windows 11, Termux, WSL2 explicitly
5. PEP 8 + type hints
6. Use `logging`, not `print`
7. Use `pathlib`, not `os.path`

---

## Output Format

Deliver research as:

1. **Individual markdown files** (one per deliverable, 10 total)
2. **Place in**: `knowledge_manager/research-output/`
3. **Reference existing docs**: Link to `research.md`, `plans.md` sections
4. **Include metadata**: Author, date, version, status (draft/final)
5. **Use diagrams**: Mermaid, ASCII art, or external tools
6. **Provide examples**: Code snippets, YAML configs, CLI commands

---

## Timeline Guidance

**Suggested Phasing**:
- Phase 1 (External Research): 1-2 hours
- Phase 2 (Architecture Design): 3-4 hours
- Phase 3 (Implementation Planning): 1-2 hours
- Phase 4 (Validation): 1 hour

**Total**: ~6-9 hours of deep research

---

## Next Steps

**Immediate Actions**:
1. Review this research query for completeness
2. Proceed with Phase 1 (External Research)
3. Document findings in `01_LITERATURE_REVIEW.md`
4. Continue through phases sequentially
5. Produce all 10 deliverables

**Post-Research**:
- Integrate findings into `knowledge_manager/plans.md`
- Create implementation tasks in Knowledge Manager DB
- Prototype critical unknowns (VRAM limits, CLI wrappers)
- Begin Stage 1 implementation (architecture skeleton)

---

## End of Research Query v2

**This document is ready to be provided to another LLM for deep research execution.**

**Expected output**: 10 comprehensive design documents totaling ~100-150 pages of detailed implementation planning.
