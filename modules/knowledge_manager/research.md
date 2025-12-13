---

File: research.md (Complete File)
```markdown
# llmclis – Research & Design Notes

> **Purpose:** This file collects **background research, design rationale, and exploratory notes**.  
> LMs & CLIs should consult this file when they need deeper context, tradeoff analysis, or references before changing architecture.

---

## Metadata

- Created: `<fill: ISO8601 datetime>`
- Last Updated: `<auto-update on each edit>`
- Last Editor (Agent / CLI): `<name>`

---

## Usage Rules

1. This file is **append-only in spirit**: do not remove old sections, but mark outdated ideas clearly.
2. Keep entries **tied to concrete questions**:
   - e.g., “Which runtime for 70B?” → pros/cons, links, decision.
3. When a decision is made, cross-link to `plans.md` and optionally note any open follow-ups in `issues.md`.
4. Use headings that LMs can easily grep for:
   - `## Local LLM Runtimes`
   - `## Vector DB Options`
   - `## Hierarchical Memory Architecture`
   - etc.

---

## Local LLM Runtimes

### vLLM vs TGI vs llama.cpp (Summary)

**vLLM**

- Strengths:
  - High throughput and excellent scaling with concurrent requests (multiple agents can talk to it).
  - Very fast time-to-first-token due to continuous batching.
  - Supports long contexts with “paged attention”.
- Weaknesses:
  - Primarily “one model per server” design.
  - Requires Python for integration (or OpenAI-compatible HTTP server).

**Text Generation Inference (TGI)**

- Strengths:
  - Enterprise-grade inference server for HuggingFace models.
  - Easy Docker deployment.
  - Supports multiple models per machine (multiple services or variants).
  - Great for production setups with monitoring and scaling.
- Weaknesses:
  - Slightly heavier to configure.
  - Multi-model serving can complicate memory planning on a single GPU.

**llama.cpp**

- Strengths:
  - Single binary, ultra-portable, supports 4-bit/8-bit quantization.
  - Good for small/medium models and offline-use, including CPU-only.
- Weaknesses:
  - Not optimized for high-concurrency server scenarios.
  - Less convenient for “many parallel agents” compared to vLLM/TGI.

**Initial Decision (draft):**

- Primary runtime for **big model**: `vLLM` or `TGI` (to be finalized in `plans.md` S2.1).
- Keep `llama.cpp` in the toolbox for:
  - Quick local experiments.
  - Tiny models (7B) for cheap routing / meta tasks.

---

## Vector DB & Memory Backend

### Qdrant vs Milvus vs Chroma vs pgvector

**Qdrant**

- High-performance, Rust-based vector DB.
- Powerful payload filtering:
  - We can filter by `project_id`, `task_id`, `type`.
- Simple Docker deployment, good for single-machine usage.
- Great default for hierarchical project-based memory.

**Milvus**

- Designed for **massive scale** (billions of vectors, cluster mode).
- Great if the memory store becomes extremely large.
- More operational complexity than Qdrant.

**Chroma**

- Extremely easy to integrate (pure Python, local).
- Good for smaller-scale experiments and prototypes.
- Potentially less robust for very large or multi-process workloads.

**pgvector**

- Vector extension within PostgreSQL.
- Good if we want all data (tasks + embeddings) in one RDBMS.
- Not strictly needed if we’re happy to keep SQLite for KM and Qdrant for memory.

**Initial Decision (draft):**

- Use **Qdrant** as primary vector DB.
- Schema:
  - Collection: `memories`
  - Vector size: determined by embedding model (likely 768).
  - Payload fields:  
    - `project_id: int`  
    - `task_id: int`  
    - `type: str` (e.g., `raw_interaction`, `task_summary`, `project_summary`, `design_doc`, `code_snippet`)  
    - `agent: str`  
    - `created_at: str (ISO8601)`  

Implementation details are captured under `plans.md` S3.x.

---

## Hierarchical Memory Architecture

**Key Requirements:**

- Represent memory at multiple levels:
  - Project  
  - Task  
  - Subtask / Interaction
- Preserve **full history**, but allow LMs to operate on **summaries**.
- Support handoffs:
  - Agent A works on a task, then Agent B can resume with a concise, accurate summary.

### Memory Types

- `raw_interaction` – a single LLM turn or tool call; high volume.
- `task_summary` – condensed state of a given task at some checkpoint.
- `project_summary` – condensed state of project; may reference task summaries.
- `design_doc` – static or semi-static design documents for modules, architecture.
- `code_snippet` – code fragments that are important to search semantically.
- `handoff_summary` – explicitly written summary used when switching agents.

### Summarization Strategy

1. **Rolling Summaries for Long Threads**
   - Once a conversation for a task exceeds `N` tokens:
     - Summarize older part into a `task_summary`.
     - Store the summary in Qdrant (`type="task_summary"`).
     - Keep a small window of recent messages as raw context.

2. **On Handoff**
   - Before handing a task from one agent to another:
     - Generate a `handoff_summary` capturing:
       - Task goals.
       - Progress so far.
       - Known obstacles.
       - Next steps expected of the new agent.
   - Store this as both:
     - A memory item (`type="handoff_summary"`).
     - Embedded in the prompt for the new agent.

3. **Project Roll-Ups**
   - When a task completes:
     - Summarize the task outcome.
     - Append it into the `project_summary` (or generate an updated project summary).
   - The project summary is what new agents read first when beginning work on the project.

4. **Avoiding Information Loss**
   - Summaries must preserve:
     - Non-obvious constraints.
     - Decisions that were debated (and why the final decision was chosen).
   - When summarizing:
     - Prefer bullet points with explicit reasons, not just results.
     - For critical decisions, link the original raw interactions (via IDs or timestamps).

---

## Agent Orchestration Framework

### Why CrewAI?

- We want:
  - Manager agent + specialist agents (coder, tester, researcher, writer).
  - Built-in support for hierarchical delegation.
  - Good logging and memory hooks.

CrewAI provides:

- **Agent** abstraction:
  - Role, goal, backstory, tools.
- **Task** abstraction:
  - Unit of work the agent executes.
- **Crew** and **Process**:
  - Multi-agent setup.
  - Hierarchical manager/worker pattern.

This maps well to our desired structure:

- `ProjectManagerAgent` – reads from Knowledge Manager; plans and delegates.
- `CodingAgent` – handles implementation / refactoring tasks.
- `TestingAgent` – runs tests / code evaluation.
- `ResearchAgent` – external research / docs.
- `WritingAgent` – documentation, commentary.

### Integration Notes

- CrewAI can run inside the orchestrator process.
- The orchestrator:
  - Pulls a task from the Knowledge Manager.
  - Instantiates / reuses CrewAI agents.
  - Manages cross-task memory and logging.
- The agents themselves:
  - Should not talk directly to SQLite or Qdrant; they use tools or wrapper functions.

Cross-links:

- Implementation tasks in `plans.md#stage-5-agent-orchestration-crewai`.
- Potential issues in `issues.md#crewai-integration`.

---

## Routing & Meta-Controller

### Problem

We have multiple model types and costs:

- Small, fast local models (7B, 13B).
- Large local models (34B, 70B).
- Remote API models (GPT-4, Claude).

We need to:

- Use small models when possible.
- Escalate to bigger models when needed.
- Avoid unnecessary expensive calls.

### Approaches

1. **Rule-Based Heuristics (Phase 1)**
   - Use simple logic:
     - Very short, simple tasks → small model.
     - Large codegen / system design → big model.
     - If tests fail twice in a row → escalate.

2. **Router Models (Phase 2)**
   - RouteLLM / Semantic Router style:
     - A small classifier estimates complexity.
     - Chooses between weak vs strong model.
   - Benefits:
     - More consistent and data-driven than hand-rolled rules.

3. **Meta-Evaluation**
   - For critical tasks:
     - Ask a secondary model to critique the primary model’s answer.
     - If critique flags issues → escalate / re-run.

### Practical Plan

- Start with rule-based routing in Python (documented in `plans.md#stage-6`).
- Collect logs of:
  - Input complexity.
  - Chosen model.
  - Outcome (success/failure).
- Later, train a small router model on this log to replace or augment heuristics.

---

## Model Selection for Tasks

This section *justifies* the model mapping described in `plans.md` Stage 7.

### Coding Models

- **WizardCoder-34B**:
  - Fine-tuned on code instructions.
  - Very strong at implementing features from natural language specs.
- **Code Llama-34B**:
  - Meta’s official code model.
  - Good at following structured instructions, with strong multi-language support.

Preferred usage:

- Local coding: WizardCoder-34B or Code Llama-34B on the 5090.
- Testing/Review: Smaller code models (e.g., 13B) or GPT-3.5 when needed.

### General Reasoning Models

- **Llama-2-70B Chat**:
  - Good open model for reasoning and chat.
  - Can be 4-bit quantized to fit on 5090.
- **GPT-4 / Claude 2**:
  - Use sparingly (for hard design decisions, ambiguous bugs, etc.).

### Embedding Models

- **BAAI bge-large-en / bge-m3** or **Instructor-XL**:
  - High-quality open-source embedding models.
  - Produce dense vectors (≈768–1024 dimensions) with strong retrieval performance.
- **Ada-002**:
  - Strong API-based option; only needed if we don’t want local embeddings.

---

## Deployment Layout

The target layout:

- `docker-compose.yml`:
  - `qdrant` – vector DB.
  - `llm_main` – large model server (vLLM or TGI).
  - `llm_aux` – optional medium model server.
- Orchestrator (Python) running:
  - Directly in WSL2 venv, or
  - As another service.

Key considerations:

- GPU utilization:
  - Ensure we don’t load more models than VRAM allows.
- Data persistence:
  - Mount volumes for Qdrant and models.
  - Keep Knowledge Manager DB on host, mounted into orchestrator container.

---

## Open Research Questions (sync with issues.md)

- How aggressively should we compress memory (risking loss of nuance)?
- When is it worth parallelizing multiple models vs using a single strong model?
- What is the best balance of summaries vs raw retrieval for coding tasks?

*(When any of these are explored in more depth, add subsections here and open structured issues in `issues.md`.)*
