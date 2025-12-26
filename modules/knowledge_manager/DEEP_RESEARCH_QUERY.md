# Deep Research Query: Multi-Agent Memory-Aware Orchestration System

**Date**: 2025-12-23
**Purpose**: Research and planning for extending `knowledge_manager` into a production-ready meta-agent orchestration system with hierarchical memory, role-based access control, and hybrid local/remote LLM integration.

---

## Executive Summary

This research query tasks you with designing a comprehensive implementation plan for transforming the existing `knowledge_manager` module into a **meta-agent orchestration platform** that:

1. **Leverages local GPU resources** (RTX 5090) for high-throughput agent workloads
2. **Integrates subscription-based LLM APIs** (GPT-4, Claude, etc.) for specialized tasks
3. **Implements hierarchical memory** with role-based access control
4. **Orchestrates multiple specialist agents** (coding, testing, research, writing, management)
5. **Provides seamless interop** with existing Python modules in the repository

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

### Existing Planning Documents (knowledge_manager/)

**Reviewed Files**:
- `research.md` - Technology research (LLM runtimes, vector DBs, orchestration)
- `plans.md` - 8-stage roadmap (partially specified)
- `progress.md` - Duplicate of research.md
- `IMPLEMENTATION_STATUS.md` - Cross-project linking features
- `TODOS.md` - Feature roadmap for task management
- `claude-summary.md` - Recent work summary

**Current Vision (from existing docs)**:

1. **Stage 1**: Architecture skeleton (orchestrator layer)
2. **Stage 2**: Local LLM runtime (vLLM/TGI on RTX 5090)
3. **Stage 3**: Vector DB integration (Qdrant)
4. **Stage 4**: Hierarchical memory layer
5. **Stage 5**: Agent orchestration (CrewAI framework)
6. **Stage 6**: Routing & meta-controller
7. **Stage 7**: Model registry & policies
8. **Stage 8**: Deployment & developer experience

**Planned Agent Roles** (from `research.md:201-205`):
- `ProjectManagerAgent` - Task planning and delegation
- `CodingAgent` - Code implementation/refactoring
- `TestingAgent` - Test execution and validation
- `ResearchAgent` - External documentation/web research
- `WritingAgent` - Documentation generation

**Technology Decisions**:
- **Vector DB**: Qdrant (payload filtering, Docker deployment)
- **Orchestration**: CrewAI (hierarchical delegation)
- **Local Models**: WizardCoder-34B, Code Llama-34B, Llama-2-70B (4-bit)
- **Runtime**: vLLM (high concurrency) or TGI (enterprise-grade)
- **Embedding**: BAAI bge-large-en or Instructor-XL (768-1024 dims)
- **Remote APIs**: GPT-4, Claude 2 (for complex reasoning)

**Memory Schema** (from `research.md:114-118`):
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

## Identified Gaps (Your Research Focus)

### Gap 1: Memory Access Control Policies

**Current State**: Memory stores `agent` field but no access scoping defined.

**Missing**:
- Which agents can read which memory types?
- Should CodingAgent see ResearchAgent's web research?
- How to prevent memory pollution across agent domains?
- Privacy/segmentation rules for multi-project environments?

**Research Questions**:
1. What are best practices for role-based memory access in multi-agent systems?
2. Should memory filtering happen at query-time or storage-time?
3. How to balance context richness vs. focused agent workspaces?
4. Should certain memory types be read-only for specific agents?

**Desired Output**:
- Memory access policy matrix (agent × memory_type)
- Implementation strategy (Qdrant filters, middleware, config-driven)
- Edge case handling (cross-agent handoffs, manager override access)

---

### Gap 2: Subscription Service Integration Strategy

**Current State**: Plans mention "GPT-4/Claude for expensive tasks" but no integration details.

**Missing**:
- Concrete service registry (which APIs are available?)
- Cost tracking and budgeting per agent
- Rate limiting and fallback logic
- API key management (secure, per-environment)
- Model selection heuristics (when to use Claude vs GPT-4 vs local?)

**Research Questions**:
1. How to design a flexible model router that supports:
   - Local models (vLLM endpoint)
   - OpenAI API (GPT-4 Turbo, GPT-4o, etc.)
   - Anthropic API (Claude 3.5 Sonnet, Opus, Haiku)
   - Other providers (Gemini, Groq, Together, Replicate)?
2. Should each agent have a dedicated model, or share a pool?
3. How to implement cost-aware routing (cheapest capable model first)?
4. Best practices for API key rotation and multi-environment configs?

**Desired Output**:
- Service registry schema (YAML/JSON)
- Agent-to-model mapping configuration
- Cost estimation and tracking design
- Fallback/escalation logic (local → GPT-4 → Claude Opus)

---

### Gap 3: Integration with Existing Modules

**Current State**: 30+ modules exist but no clear integration plan.

**Missing**:
- How should agents invoke existing modules?
  - `file_utils` for file operations
  - `llm-patcher` for code modifications
  - `cross_platform` for OS-specific tasks
  - `clipboard_tools` for data exchange
- Should agents call these as tools (CrewAI tool binding)?
- How to avoid duplication (agents re-implementing existing utilities)?

**Research Questions**:
1. What's the best pattern for exposing Python modules as agent tools?
2. Should each module have a tool wrapper, or generate tool schemas automatically?
3. How to handle module dependencies (some modules depend on each other)?
4. Should agents have direct imports, or go through a tool registry?

**Desired Output**:
- Module-to-tool mapping strategy
- Tool schema generation approach (manual vs auto-generated)
- Dependency resolution for tool chains
- Example: How CodingAgent uses `llm-patcher` as a tool

---

### Gap 4: Hierarchical Memory Implementation Details

**Current State**: High-level design exists; low-level implementation details missing.

**Missing**:
- Summarization triggers (token threshold? time-based? manual?)
- Summarization prompts (how to condense without losing critical details?)
- Handoff protocol (exact data structure for agent transitions)
- Memory compaction strategy (when to prune old raw interactions?)
- Query optimization (how to retrieve relevant memories efficiently?)

**Research Questions**:
1. What are proven summarization strategies for long-running agent tasks?
2. How to detect when a summary is losing critical information?
3. Should summaries be versioned (track what was summarized from what)?
4. How to implement "memory anchors" (preserve critical decisions verbatim)?
5. What's the optimal context window size for each agent role?

**Desired Output**:
- Summarization pipeline design (trigger → prompt → store → verify)
- Memory lifecycle state machine (raw → summary → archive → prune)
- Handoff data structure spec
- Query ranking algorithm (semantic + recency + importance)

---

### Gap 5: Local LLM Deployment Architecture

**Current State**: "Use vLLM or TGI on 5090" - needs concrete deployment plan.

**Missing**:
- Docker compose configuration
- Model loading strategy (multiple models? model swapping?)
- VRAM budget (how many models fit on 5090 simultaneously?)
- Quantization strategy (4-bit? 8-bit? AWQ? GPTQ?)
- Endpoint design (one service? multiple ports?)

**Research Questions**:
1. Can RTX 5090 (24GB VRAM) run multiple models concurrently?
   - Example: WizardCoder-34B (4-bit) + Llama-70B (4-bit) simultaneously?
2. Should different agents have dedicated model instances or share?
3. How to handle model warming (pre-load vs. on-demand)?
4. What's the latency/throughput tradeoff for vLLM vs TGI?
5. Best practices for GPU memory management with concurrent agents?

**Desired Output**:
- VRAM budget analysis (model sizes, concurrent load)
- Docker compose configuration
- Model loading strategy (static vs. dynamic)
- Benchmarking plan (test concurrency, latency, throughput)

---

### Gap 6: Routing & Cost Optimization

**Current State**: Rule-based routing planned; specifics undefined.

**Missing**:
- Concrete routing rules (input length? task complexity? domain?)
- Cost estimation logic (tokens × price per agent invocation)
- Budget limits and alerts
- A/B testing framework (compare local vs API quality)

**Research Questions**:
1. What heuristics best predict when a task needs GPT-4 vs local model?
2. How to learn from routing decisions (track success/failure per route)?
3. Should routing be per-task or per-message within a task?
4. How to implement "auto-escalation" (retry with stronger model on failure)?

**Desired Output**:
- Routing decision tree or flowchart
- Cost tracking schema (per agent, per task, per project)
- Budget management system design
- Quality feedback loop (improve routing over time)

---

### Gap 7: Developer Experience & Tooling

**Current State**: CLI and TUI exist for task management; agent interface undefined.

**Missing**:
- How do users interact with the orchestrator?
  - CLI: `km orchestrate --task-id <id>` ?
  - TUI: Live agent status dashboard?
  - API: HTTP server for external integrations?
- Logging and observability (agent decision traces, memory queries)
- Debugging tools (replay agent conversations, inspect memory retrievals)
- Configuration management (per-user settings, project-specific overrides)

**Research Questions**:
1. Should the orchestrator run as a daemon or on-demand?
2. How to visualize multi-agent collaboration (TUI dashboard? web UI?)?
3. What metrics matter (task completion time, cost, retry rate)?
4. How to make agent reasoning transparent to users?

**Desired Output**:
- User interaction flow diagrams
- Observability stack design (logging, metrics, tracing)
- Configuration file schema
- Example CLI/TUI workflows

---

## Research Deliverables

You are expected to produce the following planning documents:

### 1. `MEMORY_ACCESS_POLICY.md`

**Contents**:
- Access control matrix (agent roles × memory types)
- Read/write permissions per agent
- Implementation approach (Qdrant payload filters, middleware, config)
- Edge cases (manager overrides, cross-agent handoffs)
- Example queries with access control applied

**Format**: Markdown with tables, code examples, YAML schemas

---

### 2. `SERVICE_REGISTRY_DESIGN.md`

**Contents**:
- Service registry schema (local + remote models)
- Agent-to-model mapping configuration
- Cost tracking and budgeting system
- Rate limiting and fallback strategies
- API key management approach
- Example: Routing CodingAgent request through local → GPT-4 → Claude

**Format**: Markdown + YAML examples + Python pseudo-code

---

### 3. `MODULE_INTEGRATION_STRATEGY.md`

**Contents**:
- Survey of existing modules (file_utils, llm-patcher, cross_platform, etc.)
- Tool schema design (how modules become agent tools)
- Tool registry implementation approach
- Dependency resolution for tool chains
- Example: CodingAgent using llm-patcher to apply code changes
- Auto-generation strategy (parse module docstrings → tool schemas)

**Format**: Markdown + JSON tool schemas + Python integration examples

---

### 4. `HIERARCHICAL_MEMORY_IMPLEMENTATION.md`

**Contents**:
- Detailed summarization pipeline (trigger → prompt → storage → validation)
- Memory lifecycle state machine diagram
- Handoff protocol specification
- Query optimization strategy (vector search + metadata filters)
- Pruning and archival policies
- Example: Task with 100 interactions → 5 summaries → 1 project-level summary

**Format**: Markdown + state diagrams + Python pseudo-code

---

### 5. `LOCAL_LLM_DEPLOYMENT.md`

**Contents**:
- VRAM budget analysis (model sizes, quantization options)
- Docker compose configuration (vLLM + Qdrant + orchestrator)
- Model loading strategy (concurrent vs. swapping)
- Benchmarking plan (latency, throughput, concurrency)
- Health checks and monitoring
- Example: Running WizardCoder-34B + embedding model simultaneously

**Format**: Markdown + docker-compose.yml + benchmark scripts

---

### 6. `ROUTING_AND_COST_OPTIMIZATION.md`

**Contents**:
- Routing decision algorithm (heuristics + learning)
- Cost tracking schema (per-agent, per-task, per-project)
- Budget management and alerts
- Auto-escalation logic (retry with stronger model)
- Quality feedback loop design
- Example: Route coding task through local → GPT-4 based on failure

**Format**: Markdown + flowcharts + Python router pseudo-code

---

### 7. `DEVELOPER_EXPERIENCE.md`

**Contents**:
- CLI commands for orchestrator (`km orchestrate`, `km agents status`)
- TUI dashboard design (live agent status, memory stats)
- Configuration file schema (per-user, per-project)
- Logging and observability stack
- Debugging tools (replay conversations, inspect memory)
- Example workflows: "User requests feature → agents collaborate → code generated"

**Format**: Markdown + mockups + CLI examples

---

### 8. `UPDATED_PLANS.md`

**Contents**:
- Revised 8-stage roadmap with new stages for:
  - S3.5: Memory access control implementation
  - S7.5: Service registry and cost tracking
  - S9: Module integration (tools binding)
  - S10: Monitoring and observability
- Task breakdown for each stage (actionable, testable)
- Dependencies between stages
- Estimated complexity (trivial, moderate, complex)
- Links to detailed design docs above

**Format**: Markdown matching existing `plans.md` structure

---

## Research Constraints & Context

### Available Resources

**Hardware**:
- RTX 5090 (24GB VRAM) - primary inference GPU
- WSL2 + Windows 11 environment
- Termux (Android) - secondary testing environment

**Software/Services** (assumed available, verify specifics):
- OpenAI API (GPT-4 Turbo, GPT-4o)
- Anthropic API (Claude 3.5 Sonnet, Opus, Haiku)
- Potentially: Google Gemini, Groq, Together AI, Replicate

**Existing Codebase**:
- 30+ Python modules (cross-platform, file_utils, llm-*, etc.)
- SQLite database (tasks, projects, cross-project links)
- Textual TUI framework (for interactive interfaces)
- Pytest test suite

### Architecture Constraints

**Must Preserve**:
- Existing `knowledge_manager` SQLite schema (backward compatibility)
- CLI interface (`km` command with subcommands)
- TUI interface (`kmtui` for browsing tasks/projects)
- Cross-platform support (Windows 11, WSL2, Termux)

**Must Integrate With**:
- CrewAI framework (chosen orchestration layer)
- Qdrant (chosen vector database)
- Existing Python modules (reuse, don't duplicate)

**Must Support**:
- Offline mode (local models only)
- Hybrid mode (local + API with cost limits)
- Multi-project workflows (agents work on multiple projects)
- Long-running tasks (days/weeks with persistent memory)

### Design Principles (from `CLAUDE.md`)

**Critical Rules**:
1. **Python arguments**: ALL must have short + long forms (`-v, --verbose`)
2. **Test naming**: `module_name_test.py` (not `test_module.py`)
3. **File output**: COMPLETE files, no truncation
4. **Platform compatibility**: Handle Windows 11, Termux, WSL2 explicitly

**Code Standards**:
- PEP 8 + type hints
- Use `logging`, not `print`
- Use `pathlib`, not `os.path`
- UTF-8 everywhere
- Structured exceptions with actionable messages

---

## Research Methodology

### Phase 1: Literature Review (External Research)

**Research Topics**:
1. **Multi-agent memory systems**:
   - How do systems like AutoGPT, BabyAGI, MetaGPT handle shared memory?
   - Role-based access control in agent frameworks
   - Memory summarization techniques (hierarchical, sliding window, etc.)

2. **LLM routing strategies**:
   - RouteLLM (Anyscale) - routing by complexity
   - Semantic Router patterns
   - Cost-aware model selection
   - Quality-based escalation

3. **Agent orchestration frameworks**:
   - CrewAI best practices and limitations
   - LangGraph (alternative consideration)
   - AutoGen (Microsoft) - lessons learned

4. **Vector DB optimization**:
   - Qdrant payload filtering performance
   - Hybrid search (dense + sparse)
   - Memory retrieval ranking algorithms

**Deliverable**: Annotated bibliography with key insights

---

### Phase 2: Architecture Design (Synthesis)

**Tasks**:
1. Design memory access control system (based on Phase 1 research)
2. Design service registry and routing logic
3. Design module → tool integration layer
4. Design detailed memory lifecycle and summarization
5. Design local LLM deployment (Docker compose + VRAM budgeting)
6. Design cost tracking and budget management
7. Design observability and debugging tools

**Deliverable**: 7 detailed design documents (listed above)

---

### Phase 3: Implementation Planning (Roadmap)

**Tasks**:
1. Break down each design into implementation stages
2. Identify dependencies (what must be built first?)
3. Estimate complexity for each task
4. Map tasks to existing `plans.md` stages (or add new stages)
5. Identify risky/unknown areas requiring prototyping

**Deliverable**: `UPDATED_PLANS.md` with actionable tasks

---

### Phase 4: Validation (Feasibility Check)

**Tasks**:
1. VRAM budget validation (can proposed models fit on 5090?)
2. API rate limit analysis (can proposed usage stay within budget?)
3. CrewAI compatibility check (does framework support design?)
4. Qdrant performance estimation (can it handle query load?)

**Deliverable**: Feasibility report with risk assessment

---

## Specific Research Questions (Prioritized)

### Priority 1 (Critical Path)

1. **Memory Access Control**:
   - Should filtering be query-time (Qdrant filters) or application-layer (Python middleware)?
   - How granular? (agent-level? role-level? per-memory-type?)
   - Best way to configure? (YAML? Database table? Python dataclasses?)

2. **Service Registry**:
   - How to structure model definitions? (OpenAI vs Anthropic API differences?)
   - Should routing be rule-based or ML-based (router model)?
   - Where to store costs? (In-memory? SQLite? Separate analytics DB?)

3. **VRAM Budgeting**:
   - Exact size of WizardCoder-34B at 4-bit quantization?
   - Can we run 34B model + embedding model (bge-large-en) concurrently?
   - vLLM vs TGI: which handles multi-model serving better?

### Priority 2 (Important)

4. **Module Integration**:
   - Should tools be auto-generated from module docstrings + type hints?
   - How to handle async modules (many existing modules are async)?
   - Error handling: if a tool fails, should agent retry or escalate?

5. **Memory Summarization**:
   - What token threshold triggers summarization? (5k? 10k? 20k?)
   - Which LLM should do summarization? (Local 70B? GPT-4? Dedicated summarizer?)
   - How to validate summary quality? (Perplexity? Semantic similarity?)

### Priority 3 (Nice-to-Have)

6. **Developer UX**:
   - Should orchestrator run as systemd service (Linux) or Task Scheduler (Windows)?
   - TUI vs Web UI for monitoring? (Textual dashboard? FastAPI + React?)
   - How to handle agent failures gracefully (retry? alert user? auto-escalate?)

---

## Success Criteria

Your research is successful if it produces:

1. **Complete design documents** (7 docs covering all gaps)
2. **Actionable roadmap** (`UPDATED_PLANS.md` with tasks)
3. **Feasibility validation** (VRAM budgets, cost estimates, performance projections)
4. **Clear next steps** (what to implement first?)

**Bonus Points**:
- Code examples (Python pseudo-code, YAML schemas)
- Diagrams (state machines, flowcharts, architecture)
- Trade-off analysis (design alternatives with pros/cons)
- Prototyping recommendations (what to test before full build?)

---

## Output Format

Deliver research as:

1. **Individual markdown files** (one per deliverable)
2. **Place in**: `knowledge_manager/research-output/`
3. **Reference existing docs**: Link to `research.md`, `plans.md` sections
4. **Include metadata**: Author, date, version, status (draft/final)

---

## Timeline Guidance

**Suggested Phasing**:
- Phase 1 (Literature Review): 1-2 hours
- Phase 2 (Design): 3-4 hours
- Phase 3 (Planning): 1-2 hours
- Phase 4 (Validation): 1 hour

**Total**: ~6-9 hours of deep research

---

## Questions for Clarification (Before You Start)

Before beginning research, clarify with user:

1. **Subscription Services**: Which specific APIs do you have access to?
   - OpenAI (model tier?)
   - Anthropic (Claude access level?)
   - Others (Gemini, Groq, Together)?

2. **VRAM Priorities**: If models don't fit concurrently, which takes priority?
   - Large general model (70B) or specialized coder (34B)?

3. **Cost Budget**: What's the monthly budget for API usage?
   - Unlimited? $100/month? $1000/month?

4. **Primary Use Case**: What will this system build first?
   - Personal coding projects?
   - Open-source contributions?
   - Commercial work?

---

## End of Research Query

**Next Step**: Research agent should acknowledge receipt and ask clarifying questions above before proceeding.
