# Deep Research Request — Agent Memory & CLI LLM Context Management

> **For the researcher:** This is a deep research request. Please investigate all
> topics below thoroughly and return a structured report with specific, actionable
> findings. Prioritize practical recommendations over theory. Where multiple
> approaches exist, give a clear recommendation with reasoning.
>
> **Depth requested:** Full deep research on each topic. Citations appreciated
> but not required — quality of analysis matters more.

---

## Background

I'm building `agent_memory` — a standalone Python module for persistent,
human-editable memory for AI coding agents (Claude Code, Codex, Gemini CLI).
Notes are Markdown files with YAML frontmatter, indexed in SQLite with FTS5.
A local LLM (LM Studio on RTX 5090) handles ambiguous placement decisions.

The system runs on: WSL2 Ubuntu, Windows 11, Termux Android.

I have active implementations of:
1. `llm_local` — stdlib-only LM Studio inference client (complete)
2. `agent_memory` core — NoteStore, SQLite index, FTS5 search (in progress)
3. `agent_sync` — multi-agent coordination (Claude → Codex → Gemini CLI handoffs)

---

## Research Topics

### Topic 1: Memory Architecture for AI Coding Agents

**Question:** What are the best-known approaches for structuring persistent memory
for AI coding agents that work across sessions and multiple LLM backends?

Specifically investigate:
- **Note taxonomy/ontology**: Are there established taxonomies for AI agent
  memory beyond the basic episodic/semantic/procedural split? My current taxonomy
  (constraint, preference, decision, code_note, handoff, task, bug, session) —
  is it missing anything critical? Are any kinds redundant?
- **Memory compaction**: How should a system automatically merge, supersede, or
  expire old notes? What triggers compaction — time, note count, similarity
  threshold? What LLM prompting strategies work best for memory merging?
- **Retrieval strategies**: Beyond FTS5 keyword search and pgvector similarity,
  what hybrid retrieval strategies work best for coding context injection? Any
  research on BM25 + dense vector hybrid for code-specific memory?
- **Context injection ordering**: When injecting memories into a new agent session,
  what ordering and filtering heuristics produce the best results? (e.g., recency
  vs. relevance vs. kind priority)

---

### Topic 2: SQLite FTS5 vs. Alternatives for Local Search

**Question:** For a local-first, file-backed memory system with ~1K–50K notes,
what is the best search approach?

Investigate:
- **FTS5 performance characteristics**: At what note count does FTS5 become slow?
  What are the best tokenizer settings for mixed natural-language + code content?
  (`unicode61` vs `porter` vs `trigram` — which for code search?)
- **SQLite FTS5 + trigram**: Is the trigram tokenizer in FTS5 viable for partial
  word matches in code identifiers? Performance tradeoffs?
- **Alternatives to FTS5**: For local-only search (no server), is there a better
  option than FTS5? (tantivy/pyo3, whoosh, minisearch via subprocess, DuckDB FTS)?
  Tradeoffs for a Python stdlib-preferred codebase.
- **Hybrid local search**: Is it worth maintaining a separate BM25 index (e.g.,
  `rank_bm25` Python lib) alongside FTS5 for better ranking? At what scale?

---

### Topic 3: LLM-Based Memory Placement Classification

**Question:** What are the best prompting strategies for using a local LLM (~7B
parameter model in LM Studio) to classify where a memory note should be placed?

My current system calls `llm_local.complete(prompt)` and expects either `"global"`
or `"<project-slug>"` back. The placement decision is: should this note apply
everywhere (global) or only to one project?

Investigate:
- **Prompt engineering for classification**: For a small local model (7B–13B),
  what prompt format produces the most reliable binary/categorical classification?
  JSON-structured output vs. plain text? Few-shot vs. zero-shot?
- **Confidence scoring**: How to get a confidence score from a local model for
  classification decisions? When should the system fall back to interactive user
  prompt vs. use the LLM decision automatically?
- **Memory-specific classification prompts**: Are there known prompt patterns
  for memory placement/routing in multi-project coding environments?
- **Model selection**: For a 7B–13B parameter model running locally, which model
  families (Llama 3, Mistral, Qwen, Gemma) perform best on classification tasks
  with short inputs?

---

### Topic 4: Multi-Agent Context Handoff Patterns

**Question:** What are the best-known patterns for handing off context between
heterogeneous AI agents (Claude Code → Codex → Gemini CLI → local workers)?

My `agent_sync` module implements sequential handoffs via:
- Structured handoff notes in `agent_memory`
- Git worktrees for isolation
- SQLite WAL for state coordination

Investigate:
- **Handoff note content**: What information is most critical to include in an
  agent-to-agent handoff? Research on what context gets "lost" most often in
  multi-LLM workflows and how to prevent it.
- **State serialization formats**: For agent coordination state (current task,
  completed steps, pending blockers, file changes), what serialization format
  is most reliably parsed by different LLM backends? YAML vs JSON vs structured
  Markdown?
- **Token budget management**: With hard token limits per session (5-hour lockout),
  what strategies exist for minimizing context re-establishment cost when switching
  between agents? Is there research on "cold start" cost reduction for LLM coding
  agents?
- **Handoff verification**: How should a receiving agent verify it has understood
  the handoff correctly before starting work? Any established handoff acknowledgment
  patterns?

---

### Topic 5: Markdown + YAML Frontmatter as a Memory Format

**Question:** Is Markdown + YAML frontmatter a good long-term format for AI agent
memory? What are the known failure modes at scale?

Investigate:
- **Competing formats**: What alternatives to Markdown+frontmatter exist for
  human-editable, version-controlled AI memory? (Org-mode, TOML files, plain
  JSON, Dendron-style linking, Logseq-style blocks)
- **Frontmatter schema evolution**: How should the schema version field be used
  to handle migrations? What migration patterns work for files that need new
  required fields added?
- **Git performance**: At what note count does `git log` and `git diff` become
  slow on a flat directory of `.md` files? Are there directory sharding strategies
  that help (e.g., date-based subdirs)?
- **Human editability vs. agent reliability**: Are there known failure modes when
  humans edit frontmatter that agents then read? What validation + recovery
  patterns are most robust?

---

## Deliverable Format

Please structure the response as:

```
## Topic 1: [name]
### Key Findings
### Recommendation
### Caveats / Open Questions

## Topic 2: [name]
...
```

For each topic: specific findings first, then a concrete recommendation I can
act on, then any important caveats.

**Length:** As thorough as needed. This will inform architectural decisions for
a production system I'm actively building.
