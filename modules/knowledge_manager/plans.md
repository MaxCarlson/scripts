# llmclis – Plans

> **Purpose:** This file is the *source of truth for planned work and progress* on the LLM CLI Manager / Knowledge Manager ecosystem.  
> LMs and CLIs should read from here to decide **what to work on next**, and update this file as work is completed.

---

## Metadata

- Created: `<fill: ISO8601 datetime, e.g. 2025-12-11T12:34:00-08:00>`
- Last Updated: `<auto-update on each edit>`
- Primary Owner: `Max`
- Last Editor (Agent / CLI): `<name of LLM/CLI that last modified this file>`

---

## Usage Rules (for LMs & CLIs)

1. **Never delete history.**  
   - When closing a task, **check it off**, add completion metadata, and (if needed) move it under a “Done” section – do *not* erase it.
2. **Always update timestamps & agent names.**  
   - When you create a new task/section, set `Created` and `Created By`.  
   - When you modify a task (especially its status), update `Last Updated` and `Last Updated By`.
3. **Keep tasks small & actionable.**  
   - Break down work into steps that a single LLM run or short sequence can reasonably complete.
4. **Link to Research & Issues.**  
   - If a task requires more investigation, add a reference to a section in `research.md`.  
   - If you hit a blocker, open an entry in `issues.md` and link the issue ID here.
5. **Chronology matters.**  
   - Prefer appending new items instead of rewriting old ones; add “Notes” with dates.

---

## High-Level Roadmap

This section tracks *major stages* of the system. Each stage may contain multiple detailed tasks below.

- [ ] **Stage 1 – Architecture Skeleton**
- [ ] **Stage 2 – Local LLM Runtime Setup (RTX 5090)**
- [ ] **Stage 3 – Vector DB & Memory Backend**
- [ ] **Stage 4 – Hierarchical Memory Layer**
- [ ] **Stage 5 – Agent Orchestration (CrewAI)**
- [ ] **Stage 6 – Routing & Meta-Controller**
- [ ] **Stage 7 – Model Registry & Policies**
- [ ] **Stage 8 – Deployment & DX (Developer Experience)**

When the entire Stage is truly production-ready, check it off and add a dated note.

---

## Stage 1 – Architecture Skeleton

**Goal:** Implement the minimal glue code that connects the existing Knowledge Manager (SQLite + TUI) to a new “orchestrator” layer, without yet calling local models or remote APIs.

**Status:** `[ ] Not started` / `[ ] In progress` / `[ ] Done`

**Tasks:**

- [ ] **S1.1 – Orchestrator Module Skeleton**
  - **Description:** Create a `orchestrator/` Python package that will own:
    - Task selection from the Knowledge Manager DB.
    - Calls into agents / CrewAI.
    - Calls into memory (vector DB) and model servers.
  - **Created:** `<timestamp>` by `<agent/CLI>`
  - **Last Updated:** `<timestamp>` by `<agent/CLI>`
  - **Links:**  
    - Research: `research.md#orchestrator-and-crewai`  
    - Issues: `issues.md#km-001-orchestrator-sqlite-integration` *(example)*

- [ ] **S1.2 – Knowledge Manager Integration**
  - **Description:** Implement a thin wrapper around the existing SQLite schema:
    - `get_next_task_to_work_on(project_id: Optional[int])`
    - `mark_task_status(task_id, status, metadata)` (status ∈ {pending, in-progress, done, blocked})
    - `append_task_note(task_id, note, agent_name)`
  - **Created:** `<timestamp>`
  - **Last Updated:** `<timestamp>`
  - **Notes:**  
    - Ensure no schema-breaking changes; keep compatibility with current KM code.
    - Consider adding non-breaking columns like `last_agent`, `last_updated_at`.

- [ ] **S1.3 – CLI Entry Point for Orchestrator**
  - **Description:** Add a CLI command to start the orchestrator.
    - Example (eventual):  
      ~~~bash
      llmclis orchestrate --project_id 1 --max_steps 20
      ~~~
  - **Created:** `<timestamp>`
  - **Last Updated:** `<timestamp>`
  - **Notes:**  
    - This can initially just print which task *would* be worked on, without spinning up agents.

---

## Stage 2 – Local LLM Runtime (RTX 5090)

**Goal:** Stand up at least one performant local LLM endpoint (vLLM or TGI) that the orchestrator can call.

**Status:** `[ ] Not started` / `[ ] In progress` / `[ ] Done`

**Tasks:**

- [ ] **S2.1 – Decide on Primary Runtime (vLLM vs TGI)**
  - **Description:** Choose which runtime will host the main large model (e.g., Llama-2-70B or best code model).
  - **Created:** `<timestamp>`
  - **Last Updated:** `<timestamp>`
  - **Notes:**  
    - See `research.md#local-llm-runtimes` for pros/cons.
    - Consider concurrency (multiple agents) ⇒ vLLM strong candidate.

- [ ] **S2.2 – Dockerized Model Server**
  - **Description:** Write a `docker-compose` service for the chosen runtime and model.
  - **Checklist:**
    - [ ] GPU enabled (`--gpus all` + NVIDIA container toolkit).
    - [ ] Model weights mounted from host (`~/models` → `/models`).
    - [ ] HTTP port exposed & documented.
  - **Links:**  
    - Research: `research.md#deployment-layout`

- [ ] **S2.3 – Healthcheck + Smoke Test**
  - **Description:** Implement a small Python script or CLI subcommand that:
    - Hits the local model endpoint with a trivial prompt.
    - Prints latency & response size.
  - **Notes:**  
    - This will be reused in CI / periodic health checks.

---

## Stage 3 – Vector DB & Memory Backend

**Goal:** Stand up Qdrant and integrate minimal memory operations (`store_memory`, `query_memory`).

**Status:** `[ ] Not started` / `[ ] In progress` / `[ ] Done`

**Tasks:**

- [ ] **S3.1 – Qdrant Docker Service**
  - **Description:** Add `qdrant` service to `docker-compose.yml`:
    - Volume backed data
    - Port 6333 exposed
  - **Created:** `<timestamp>`
  - **Last Updated:** `<timestamp>`

- [ ] **S3.2 – Python Memory Client**
  - **Description:** Implement a small `memory/` module:
    - `store_memory(text, project_id, task_id, type, agent)`
    - `query_memory(query_text, project_id=None, task_id=None, type=None, top_k=5)`
  - **Notes:**  
    - Embedding model details in `research.md#embedding-model-selection`.

- [ ] **S3.3 – E2E Memory Test**
  - [ ] Round-trip test: write text → embed+store → query → confirm round-trip text is among results.

---

## Stage 4 – Hierarchical Memory Layer

**Goal:** Implement the actual hierarchical memory semantics (project / task / subtask + summaries + compaction).

**Status:** `[ ] Not started` / `[ ] In progress` / `[ ] Done`

**Tasks:**

- [ ] **S4.1 – Memory Schema & Types**
  - Define and document memory `type` values:
    - `raw_interaction`, `task_summary`, `project_summary`, `design_doc`, `code_snippet`, etc.
  - Add to `research.md#hierarchical-memory-architecture`.

- [ ] **S4.2 – Summarization Jobs**
  - Implement utility(s) that:
    - Summarize long conversations into a compact “task summary”.
    - Summarize multiple task summaries into a “project summary”.
  - Add prompts & guidelines into `research.md#summarization-strategy`.

- [ ] **S4.3 – Handoff Summary Hook**
  - On agent handoff (e.g., coder → tester), auto-generate a handoff summary & store in memory.

---

## Stage 5 – Agent Orchestration (CrewAI)

**Goal:** Use CrewAI (or equivalent) to run a Manager + Specialist agents atop the orchestrator.

**Status:** `[ ] Not started` / `[ ] In progress` / `[ ] Done`

**Tasks (abbrev):**

- [ ] **S5.1 – CrewAI Setup & Basic Example**
- [ ] **S5.2 – Define Agent Roles (manager, coder, tester, researcher, writer)**
- [ ] **S5.3 – Connect Agents to Orchestrator & KM**
- [ ] **S5.4 – Integrate Memory Retrieval into Agent Context**

_Detailed description preserved in `research.md#agent-orchestration-framework`._

---

## Stage 6 – Routing & Meta-Controller

**Goal:** Implement routing logic to pick which model/agent handles each task.

**Core tasks (details in research):**

- [ ] **S6.1 – Rule-Based Router**
- [ ] **S6.2 – Optional RouteLLM / Semantic Router Experiment**
- [ ] **S6.3 – Fallback/Escalation Logic (cheap → expensive on failure)**

---

## Stage 7 – Model Registry & Policies

**Goal:** Centralize model configuration and mapping from roles → models.

- [ ] **S7.1 – model_registry.yaml**
- [ ] **S7.2 – Role → Model Mapping**
- [ ] **S7.3 – Offline vs Online Modes (local-only vs local+API)**

See `research.md#model-selection-for-tasks` for recommendations.

---

## Stage 8 – Deployment & DX

**Goal:** Make it smooth to bring the whole stack up and run a project.

- [ ] **S8.1 – docker-compose.yml**
- [ ] **S8.2 – “First Run” Script / CLI**
- [ ] **S8.3 – Developer Documentation & Examples**

---

## Done / Completed Work Log

> When you fully complete any task above, also add an entry here.

- *(Empty – to be populated as work completes)*
