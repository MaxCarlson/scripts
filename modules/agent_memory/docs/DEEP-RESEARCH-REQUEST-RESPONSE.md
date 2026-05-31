# Deep Research Report on Agent Memory and CLI LLM Context Management

The strongest overall pattern across the literature and vendor documentation is to treat agent memory as a **layered system** rather than a single note store: a small always-visible core memory, a larger searchable long-term store, and one or more summarized or reflective layers that continuously consolidate past work. For your stack, that points to a pragmatic design: keep Markdown notes as the human-editable ground truth, index them with SQLite FTS5 for lexical retrieval, optionally add embeddings later for semantic recall, and use a small local model only for narrowly-scoped routing and compaction decisions with strict schemas and low-temperature decoding. This matches what recent memory systems, agent frameworks, and prompt-structure guidance converge on, while staying compatible with LM Studio, WSL2, Windows, and Termux. citeturn15academia0turn15academia2turn15academia3turn50view2turn51view0

## Memory architecture for coding agents

### Key findings

The common episodic/semantic/procedural split is still useful, but recent agent-memory work has moved toward **additional operational layers** that matter a lot for coding agents: **working memory or core memory** that is always in context, **archival or long-term memory** that is queried on demand, **reflective or summarized memory** that compresses prior sessions, and sometimes **relational or graph memory** that preserves links and temporal structure between events. Letta, for example, explicitly separates always-visible memory blocks from archival memory that must be queried via tools; D-Mem adds a fast retrieval path with a higher-fidelity fallback; Zep emphasizes temporally-aware graph memory; and A-MEM focuses on dynamic indexing, linking, and memory evolution over time. citeturn50view2turn51view0turn52view1turn15academia3turn49academia1turn15academia0

That means your current note kinds are close, but a few of them are better modeled as either **attributes** or **higher-signal note types**. In practice, `session` is usually more useful as provenance metadata than as a first-class memory type; `handoff` is valid and important in a multi-agent system; `decision` is critical and should stay; `task` can be split into live task state versus durable task lessons; and you are likely missing durable categories for **environment/runtime facts**, **workflow/procedure**, **artifact/file notes**, and **evidence/observation**. Letta’s docs also suggest that “scratchpad” or “working memory” deserves special treatment because it changes frequently and should stay directly visible, while archival facts should sit outside the prompt until retrieved. citeturn51view0turn52view2turn52view4

Compaction is no longer just “summarize old messages.” Recent systems use **continuous consolidation**. MemoryBank explicitly uses a forgetting-curve-inspired update mechanism; A-MEM allows new memories to refine existing note representations and links; Reflective Memory Management uses prospective and retrospective reflection to summarize at multiple granularities and improve future retrieval; Anthropic’s context-management docs treat context curation as necessary because irrelevant content degrades model focus; and Letta exposes multiple compaction modes that summarize old messages while keeping recent ones visible. citeturn16academia2turn15academia0turn16academia3turn9view1turn52view5

For retrieval in code-heavy environments, the evidence strongly favors **hybrid lexical + semantic retrieval**, not dense retrieval alone. Dense retrievers are known to lag on rare entities and salient phrases, which maps directly onto code identifiers, filenames, error strings, and config keys. SPAR was proposed precisely because dense retrieval struggles on salient phrases and rare entities; repository-level code search work shows strong gains from BM25 first-stage retrieval plus neural reranking; and hybrid search studies continue to report gains from combining lexical and dense signals with weighted ranking or reranking. citeturn13academia2turn13academia1turn12academia3

Ordering matters because long-context models still show strong positional bias. “Lost in the Middle” found that relevant information is used most reliably when it appears near the beginning or end of the context, not buried in the middle. Anthropic’s prompt guidance similarly recommends placing long-form material near the top and queries at the end, and notes measurable gains from that layout in long-document settings. citeturn14academia0turn14academia1turn48view0

### Recommendation

I would formalize your memory model into **three storage tiers plus one routing layer**.

Use a **core tier** for always-visible facts that should shape every generation: project constraints, coding preferences, durable decisions, workflow rules, and the current handoff summary. This maps well to Letta-style memory blocks and to your own “global” versus project-scoped notes. Use an **archival tier** for everything else that should be searchable but not pinned: historical bug notes, code notes, research snippets, older handoffs, and detailed session traces. Use a **reflective tier** for synthesized notes: “what changed,” “what we learned,” and “what supersedes what.” Finally, use a **routing layer** that decides what belongs in core versus archival, and what should be merged or expired. citeturn51view0turn52view1turn15academia0turn16academia3

Concretely, I would keep your existing note kinds but rework them slightly:
- Keep: `constraint`, `preference`, `decision`, `handoff`, `bug`, `code_note`.
- Convert `session` into metadata fields like `session_id`, `created_at`, `source_agent`, and `supersedes`.
- Split `task` into either `task_state` or `task_lesson`; the former expires quickly, the latter survives.
- Add `environment` for runtime/toolchain/platform facts, `procedure` for reusable workflows, and `evidence` for observed behavior, logs, or benchmark facts that support a decision.  
This is the minimum expansion that makes compaction and retrieval much easier to automate. citeturn51view0turn52view2turn15academia3

For compaction, do not wait for “old age” alone. Use deterministic triggers first, then LLM-assisted consolidation second. Good triggers are: exact or near-duplicate notes, notes that share subject and kind, notes explicitly marked as superseded, inactive task-state notes, and families of notes above a count threshold. Use the LLM only after deterministic candidate selection. The compaction prompt should not ask for freeform summarization; it should ask for a **merge decision** in schema form: `keep`, `merge`, `supersede`, `split`, with output fields for canonical text, dropped IDs, retained evidence, confidence, and whether human review is needed. That follows the broader evidence that structured outputs and tightly scoped example-driven prompts are more reliable than unconstrained prose. citeturn52view5turn43view0turn44view4turn24academia0

For context injection, pin only a very small amount. My recommended order is: **stable core constraints first, current project profile second, current handoff/goal summary last, and retrieved evidence immediately before the user’s active request**. Put anything long and archival outside the middle of the prompt unless it is truly necessary. This design is directly motivated by long-context positional bias findings. citeturn14academia0turn48view0

### Caveats and open questions

There is still no universally accepted ontology for agent memory in coding systems. The research trend is toward layered, adaptive memory rather than a fixed taxonomy, so you should expect your schema to evolve. A related open question is whether graph links between notes are worth the added complexity at your expected scale; the literature suggests they help, especially for temporal and relational reasoning, but the implementation cost is non-trivial. citeturn15academia0turn49academia1turn15academia3

## Local search with SQLite FTS5 and alternatives

### Key findings

At your target scale of roughly **1K to 50K notes**, the evidence I found points toward **SQLite FTS5 as the best default**, especially because it is local, file-backed, mature, and already part of your architecture. SQLite’s WAL mode allows readers and writers to proceed concurrently in the usual case, which is a practical advantage for a memory system that is indexing while agents are searching. citeturn4view6turn4view7

For mixed prose and code, tokenizer choice matters more than raw engine choice. SQLite’s `unicode61` tokenizer supports `tokenchars`, which lets you treat punctuation like `_` or `-` as part of tokens; that is exactly the lever you want for code-ish identifiers. By contrast, DuckDB’s FTS defaults are stemmer-centric and ignore non-alphabetic lowercase characters by default, which is a strong hint that its out-of-the-box settings are tuned for natural language, not code search. citeturn4view5turn20view0turn20view1turn20view2

You probably do **not** need a separate BM25 implementation beside FTS5. DuckDB exposes BM25 explicitly, and SQLite FTS5 also provides BM25 ranking in its full-text subsystem; more importantly, the literature on hybrid retrieval shows that the main gains typically come from combining **lexical retrieval with semantic retrieval or reranking**, not from maintaining two different lexical indexes side by side. citeturn22view0turn13academia1turn12academia3

The alternatives are viable, but each violates one of your design preferences. Tantivy is powerful and Lucene-like, with background segment merging and strong search-engine ergonomics, but it implies a Rust/PyO3 boundary or sidecar process. Whoosh exposes useful field types including N-gram indexing and remains easy to hack on, but it is its own index stack rather than a built-in extension to your SQLite data model. DuckDB FTS is attractive if you are already standardizing on DuckDB, but its FTS index does not auto-update when the underlying table changes, which is a real operational drawback for a live note store. MiniSearch is light and resource-friendly, but it is in-memory JavaScript, so it fits much better as a browser/mobile helper than as the canonical index for your Python module. citeturn20view8turn20view9turn21view2turn21view3turn22view2turn22view0turn20view7turn20view5

### Recommendation

Use **SQLite FTS5 as the primary lexical index** and keep the system simple. For your corpus size, I would not introduce Tantivy, DuckDB FTS, or a separate BM25 library unless you hit a real retrieval-quality wall. The biggest quality win is more likely to come from **query design and ranking strategy** than from a different local search engine. citeturn13academia1turn12academia3turn4view6

For tokenizer settings, I would start with a **code-aware `unicode61` configuration** rather than stemming. The practical goal is to preserve identifiers and paths as searchable units. In implementation terms, that means treating underscore and selected punctuation as token characters, avoiding stemming on code-heavy fields, and separating “identifier-like” content from pure prose where helpful. The DuckDB defaults are a good reminder of what *not* to do for code-first search: a Porter stemmer plus non-alphabetic stripping is exactly the wrong bias for filenames, snake_case identifiers, flags, and stack traces. citeturn4view5turn20view1turn20view2

I would also avoid making substring search your default path. There is a real user need for partial identifier matching, but I did not find a strong primary-source benchmark that cleanly justifies making trigram-style indexing the default for a 1K–50K note corpus. My recommendation is therefore: keep the main FTS index token-based, and if substring matching turns out to be mission-critical, add a **secondary n-gram field or sidecar capability** only for note titles, symbol fields, and identifier-heavy content. That captures the need without paying the write-amplification and index-size cost everywhere. This is an engineering judgment, not a settled benchmark result. Related ecosystems like Whoosh and MiniSearch both expose n-gram, prefix, and fuzzy-style search as targeted features rather than the universal default. citeturn21view3turn20view5turn20view6

For ranking, use a staged pipeline: **FTS5 retrieval first, optional reranking second**. A strong practical design is: retrieve more candidates lexically, optionally fuse with embedding recall later, and rerank the short list using a code-aware model or heuristics. That is the same shape that works well in repository-level code search and in modern hybrid retrievers. citeturn13academia1turn12academia3turn13academia2

### Caveats and open questions

I did not find a high-quality primary source that names a universal note-count threshold where FTS5 “becomes slow,” because performance depends heavily on note length, query patterns, tokenizer settings, storage device, and whether you are doing incremental or batch updates. So my recommendation is confidence-based, not threshold-based: stay with FTS5 until you can demonstrate a concrete bottleneck in latency, index size, or ranking quality. citeturn4view6turn20view9

## LLM-based memory placement classification

### Key findings

For your placement problem, the best framing is not “ask the model a question” but **run a constrained classifier**. LM Studio exposes OpenAI-compatible endpoints and supports structured output via JSON Schema on `/v1/chat/completions`; it explicitly says not all models below 7B are capable of structured output. OpenAI’s own structured-output guidance recommends strict schema-constrained outputs over plain JSON mode because only structured outputs guarantee schema adherence. Recent structured-generation research also shows that constrained decoding has become the dominant approach, while simpler freeform prompting degrades as tasks become structurally more complex. citeturn25view0turn25view1turn44view4turn24academia0turn42academia3

Few-shot prompting remains highly relevant for classification and routing. OpenAI recommends providing a handful of diverse examples for few-shot learning, and Anthropic says examples are one of the most reliable ways to improve accuracy and consistency, with 3–5 relevant, diverse, well-structured examples as a strong default. Anthropic also recommends XML-style segmentation of instructions, context, examples, and input because it reduces misinterpretation, and its guidance on literal instruction following is especially relevant for narrow routing tasks. citeturn46view0turn46view2turn48view1turn48view0turn48view2

For confidence, the most practical route is to ask for it explicitly as part of the output schema rather than relying on hidden model internals. “Language Models Mostly Know What They Know” found that models can estimate the probability that their own answers are correct in the right format, and a more recent calibration study found that **self-reported confidence** outperformed self-consistency voting and token-probability methods on calibration quality in the evaluated grading tasks. That matters here because LM Studio’s documented chat-completions parameter list includes temperature, top_p, top_k, penalties, and seed, but does not document `logprobs`; so if you want a solution that is portable across your local stack, explicit confidence fields are safer than token-level confidence plumbing. The last step is an inference from the docs, not an explicit LM Studio statement. citeturn41academia0turn41academia1turn27view0

On model choice, the best high-confidence evidence I found points to a short list. Llama 3.1 8B Instruct posts strong official instruction-following and tool-use numbers, including IFEval 80.4, API-Bank 82.6, and BFCL 76.1. Gemma 3 12B IT posts even stronger official coding and instruction-style scores in its size range, including HumanEval 85.4, LiveCodeBench 32.0, and IFEval 88.9. Qwen2.5 7B Instruct’s official card explicitly highlights improved instruction following and structured output generation, especially JSON, and Qwen3’s official materials emphasize improved instruction following, agent capabilities, and a controllable thinking/non-thinking mode. Mistral Nemo 12B is a better current Mistral-family choice than older Mistral 7B for local use because it is positioned as a 128K, code-trained, function-calling-capable drop-in replacement for Mistral 7B. citeturn30view8turn35view0turn30view4turn37view0turn38view0turn36view0

### Recommendation

Treat placement as a **strict-schema classification task** with a very small label space and explicit confidence. I would move from your current `"global"` / `"<project-slug>"` plain-text return to a schema like:

```json
{
  "scope": "global | project",
  "project_slug": "string | null",
  "confidence": 0.0,
  "reason_code": "cross_project_preference | repo_specific_fact | environment_fact | workflow_rule | unclear",
  "needs_user_confirmation": false
}
```

That is the best fit for LM Studio’s structured-output support and for the broader evidence that schema-constrained outputs are more reliable than free text. citeturn25view1turn44view4turn24academia0

Prompt-wise, I would use **deterministic pre-rules first**, then a short few-shot classifier prompt second. In other words: if a note explicitly names files, repo paths, package names, branch names, project-only conventions, or bug IDs tied to a single repo, force `project`. If it describes preferences, global tooling habits, cross-project workflow rules, or OS/runtime constraints that recur across repos, strongly bias `global`. Only hand ambiguous cases to the LLM. When you do, include 3–5 examples with mixed edge cases, and separate `<instructions>`, `<examples>`, `<candidate_note>`, and `<known_projects>` blocks. Keep decoding conservative. citeturn46view2turn48view1turn48view0

For automation policy, I would set a **selective threshold** rather than a single binary trust rule. A good starting point is:
- `confidence >= 0.85`: auto-apply
- `0.60–0.84`: apply only if a deterministic heuristic agrees
- `< 0.60`: require user confirmation  
That thresholding policy is an engineering recommendation supported by the calibration literature, not a published universal standard. citeturn41academia0turn41academia1

If you want one clear model choice for this job on an RTX 5090, my primary recommendation is **Gemma 3 12B IT** if latency is acceptable, because its official numbers in this size band are particularly strong for coding and instruction reliability. If you want a faster classifier with especially strong vendor messaging around JSON/structured outputs and agent workflows, use **Qwen3-8B with thinking disabled** or **Qwen2.5-7B Instruct**. Llama 3.1 8B is the conservative fallback when you care about broad ecosystem support and solid official tool-use metrics. citeturn35view0turn30view4turn37view0turn38view0turn30view8

### Caveats and open questions

I did not find a primary-source benchmark specifically for “memory placement classification in multi-project coding environments,” so the routing design above is a best-practice synthesis rather than a benchmarked standard task. The other caveat is that some open local models behave differently under constrained decoding depending on quantization and runtime; you should therefore evaluate the exact quantized model/runtime combination you plan to deploy, not just the base model family. citeturn24academia0turn25view1

## Multi-agent context handoff patterns

### Key findings

The ecosystem increasingly treats **handoffs as a first-class orchestration pattern**, not just a prompt trick. OpenAI’s Agents SDK has explicit handoff support, AutoGen documents handoffs as a design pattern, and Letta’s memory-block model explicitly calls out multi-agent coordination use cases where agents observe and update shared blocks. citeturn6view0turn6view3turn51view0

What tends to get lost in handoffs is not just facts, but **temporal order, rationale, and unresolved uncertainty**. Zep argues for temporal knowledge graphs because enterprise memory needs historical relationships, not just static retrieval; Reflective Memory Management flags overly rigid memory granularity and retrieval mismatch as failure modes; and D-Mem argues that retrieval-only memory is often too lossy for fine-grained contextual understanding, which is exactly the kind of loss that ruins agent handoffs. citeturn49academia1turn16academia3turn15academia3

For serialization, the strongest cross-vendor pattern is to separate **machine-critical structure** from **human-readable narrative**. OpenAI and LM Studio both support strict JSON schemas for structured outputs; Anthropic recommends XML-style structure when prompts mix instructions, examples, metadata, and inputs. In practice, that makes a hybrid format the most robust: a compact JSON envelope for the receiving agent’s parser, plus a short Markdown body for humans. citeturn44view4turn25view1turn48view0

Token-budget management is now a discipline of its own. Anthropic’s prompt caching reuses shared prompt prefixes, and its context-editing tools can clear old tool results while preserving local full history on the client side. OpenAI’s prompt guidance also recommends keeping reused content at the beginning of prompts to maximize prompt-caching benefit. On the research side, LongLLMLingua shows that prompt compression can reduce latency and cost while sometimes preserving or even improving long-context performance. citeturn8view0turn9view1turn46view2turn10academia1

### Recommendation

For your `agent_sync` handoff note, I would standardize on a **two-part artifact**.

The first part should be a strict JSON header with fields such as `goal`, `current_status`, `completed_steps`, `pending_steps`, `changed_files`, `test_results`, `known_blockers`, `decisions`, `assumptions`, `requested_next_action`, and `confidence`. The second part should be a short Markdown narrative that explains the “why” behind the decisions. This gives Codex/Gemini/Claude/local models a structure they can parse, while leaving humans with a readable handoff note in git. citeturn44view4turn25view1turn48view0

The content of the handoff should emphasize **what is likely to be lost** if omitted:
- the exact task boundary,
- what was already tried,
- what changed in files or state,
- what remains uncertain,
- what decision was made and why,
- what evidence supports that decision,
- and what the next agent is expected to do first.  
The literature on temporal and reflective memory suggests that rationale and sequence are just as important as facts. citeturn49academia1turn16academia3turn15academia3

To minimize cold-start cost, maintain a stable “project charter” prefix that is shared across sessions and agents, and keep it at the start of the prompt so caching works in your favor. Then keep the current handoff summary small and near the end, where the active query sits. If the handoff becomes too large, compact it aggressively into a “current state” summary and move detailed traces into archival memory. Use prompt caching wherever the provider supports it, and consider compression only for long, repetitive contexts. citeturn8view0turn9view1turn46view2turn10academia1

For verification, add a mandatory **handoff acknowledgment step** before the receiving agent starts editing. I recommend a structured ACK that restates the goal, enumerates the files or modules it believes are in scope, names blockers and assumptions, and states the first planned action. I did not find a formal universal standard for this in the papers, so this is an engineering recommendation, but it is strongly aligned with the evidence that literal prompts, structured outputs, and explicit examples improve reliable execution. citeturn48view2turn44view4turn46view2

### Caveats and open questions

The main open question is how far to centralize shared state. Shared memory blocks are attractive for coordination, but they also increase coupling between agents. You may want one immutable shared project profile and one mutable current-handoff state, rather than many mutable shared documents. The literature supports richer memory structures, but does not yet resolve the synchronization trade-off cleanly for heterogeneous CLI-agent workflows. citeturn51view0turn49academia1

## Markdown with YAML frontmatter as a long-term memory format

### Key findings

Markdown plus YAML frontmatter remains a very defensible long-term format for **human-editable, version-controlled notes**. Jekyll’s docs are a useful canonical example: a file is treated specially when valid YAML front matter appears at the very top between triple-dashed lines, and custom variables are entirely normal in that model. citeturn56view0

The main failure mode is not Markdown. It is **YAML ambiguity**. YAML 1.2.2’s core schema resolves many plain scalars automatically; booleans like `true`/`false` and null-like values such as `null` or `~` are typed, and numeric-looking values may also resolve away from strings. That is great for humans when it works, but it is exactly the sort of thing that produces brittle agent parsing if a person edits frontmatter casually. Jekyll also documents a very practical Windows-centric failure mode: UTF-8 BOM characters at the start of a file can break processing. citeturn57view4turn57view3turn57view5

Git itself can handle large working trees, but the bottleneck in note-heavy repositories is often **working-tree scanning**, not frontmatter as such. Git’s own documentation points to `core.untrackedCache` and `core.fsmonitor` as performance features aimed at reducing or avoiding expensive scans, especially for commands like `git status`; it also notes index path-prefix compression in `index.version=4`. That suggests that directory layout and repo settings matter, but the raw existence of many `.md` files is not, by itself, the decisive problem. citeturn57view0turn57view1turn57view2

### Recommendation

Keep **Markdown + YAML frontmatter** as the canonical source format. For your use case, it is the best balance between human editability, git friendliness, and agent interoperability. I would not migrate to a more exotic format unless you discover a concrete failure mode that frontmatter cannot address. That is my architectural recommendation rather than a settled literature consensus. citeturn56view0turn57view4

The important move is to **constrain YAML aggressively**. Keep frontmatter flat and small. Store only stable metadata there: `schema_version`, `id`, `kind`, `scope`, `project`, `created_at`, `updated_at`, `status`, `supersedes`, `tags`, and perhaps a short `title`. Put all rich prose, rationale, and evidence in the Markdown body. Quote ambiguous scalars, especially anything that could be parsed as a boolean, null, or number. Validate every file on read and on write, and fail into a recovery mode that preserves the body content even when the frontmatter is invalid. YAML’s core-schema typing rules are the reason for that advice. citeturn57view4turn57view3

For schema evolution, add a required `schema_version` and use **migrations that are additive first**. Jekyll’s support for custom variables and defaults is a nice reminder that frontmatter systems age best when new fields can be introduced gradually rather than by breaking every older file at once. So if you need a new required field, the migration pattern should be: infer it when possible, provide a safe default when inference is acceptable, mark legacy files for later normalization, and only then tighten validation. citeturn56view0

For repository layout, I would shard by **project first, then date or note prefix**, primarily for human and tooling ergonomics. I do not have a primary-source threshold that says “Git gets slow at X markdown files in one directory,” so I would not claim one. What the Git docs do show is that scan-related performance can often be improved by enabling `core.untrackedCache`, `core.fsmonitor`, and modern index features. That means repo settings are a worthwhile part of your performance plan, independent of whatever sharding scheme you choose. citeturn57view0turn57view1turn57view2

### Caveats and open questions

I did not complete a source-backed comparison of every competing human-editable alternative you listed, such as Org-mode, Dendron-style linking, Logseq blocks, or JSON sidecars, so I would not claim that Markdown+frontmatter is universally superior to all of them. My conclusion is narrower: given your current requirements and the evidence I gathered, there is **no strong reason to leave** Markdown+YAML, but there is a strong reason to harden validation, versioning, and recovery around it. citeturn56view0turn57view4
