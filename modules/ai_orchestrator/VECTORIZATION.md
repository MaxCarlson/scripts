# Vectorization for AI Planning and Memory

## Overview

This document outlines the planned vectorization support for the AI Orchestrator to enable semantic search, long-term memory, and intelligent planning.

## Goals

1. **Semantic Search**: Find related projects/tasks based on meaning, not just keywords
2. **AI Memory**: Allow AI agents to store and retrieve context across sessions
3. **Planning Intelligence**: Enable AI to understand project relationships and dependencies
4. **Knowledge Base**: Build a searchable knowledge base from all projects/tasks/notes

## Architecture

### Components

1. **Embedding Generator**
   - Use sentence-transformers or similar for local embedding
   - Support for API-based embeddings (OpenAI, Anthropic, etc.)
   - Batch processing for efficiency
   - Cache embeddings to avoid recomputation

2. **Vector Store**
   - SQLite with vector extension (sqlite-vss or similar)
   - Or external vector DB (ChromaDB, Qdrant, Milvus)
   - Store embeddings alongside metadata

3. **Indexing Pipeline**
   - Automatically embed new projects/tasks/notes
   - Update embeddings when content changes
   - Background processing to avoid blocking

4. **Search Interface**
   - Semantic search API
   - Hybrid search (semantic + keyword)
   - Filtered search (by project, status, date, etc.)

### Schema Extension

Add to knowledge_manager database:

```sql
CREATE TABLE embeddings (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,  -- 'project', 'task', 'note'
    entity_id TEXT NOT NULL,
    embedding BLOB NOT NULL,  -- Serialized vector
    embedding_model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (entity_id) REFERENCES projects(id) OR tasks(id) OR notes(id)
);

CREATE INDEX idx_embeddings_entity ON embeddings(entity_type, entity_id);
```

### API Design

```python
from ai_orchestrator import VectorStore

# Initialize vector store
vs = VectorStore()

# Index a project
vs.index_project(project_id="...")

# Semantic search
results = vs.search(
    query="authentication system implementation",
    entity_types=["project", "task"],
    limit=10,
    filters={"status": "active"}
)

# Find similar items
similar = vs.find_similar(
    entity_id="task-uuid-here",
    limit=5
)

# Hybrid search (semantic + keyword)
results = vs.hybrid_search(
    query="API security",
    keywords=["auth", "jwt"],
    limit=10
)
```

## Implementation Plan

### Phase 1: Basic Embedding (Local)
- [x] Install sentence-transformers
- [ ] Create EmbeddingGenerator class
- [ ] Add embeddings table to database
- [ ] Implement basic indexing for projects/tasks
- [ ] Add simple similarity search

### Phase 2: Vector Store Integration
- [ ] Evaluate vector DB options (sqlite-vss vs ChromaDB)
- [ ] Implement vector store adapter
- [ ] Add batch indexing
- [ ] Implement filtered search

### Phase 3: API Embeddings
- [ ] Support OpenAI embeddings
- [ ] Support Anthropic embeddings (when available)
- [ ] Add embedding model switching
- [ ] Implement embedding caching

### Phase 4: Advanced Features
- [ ] Hybrid search (semantic + keyword)
- [ ] Automatic re-indexing on updates
- [ ] Background indexing worker
- [ ] Embedding quality metrics
- [ ] Dimension reduction for storage efficiency

### Phase 5: AI Memory Layer
- [ ] Conversation context storage
- [ ] Memory retrieval for AI agents
- [ ] Long-term memory consolidation
- [ ] Memory importance scoring
- [ ] Automatic memory pruning

## Model Selection

### Local Embedding Models
- **all-MiniLM-L6-v2**: Fast, small (384 dim), good for general use
- **all-mpnet-base-v2**: Better quality (768 dim), slower
- **multi-qa-mpnet-base-dot-v1**: Optimized for Q&A
- **code-search-net**: Specialized for code

### API Embedding Models
- **text-embedding-3-small** (OpenAI): 1536 dim, fast, affordable
- **text-embedding-3-large** (OpenAI): 3072 dim, highest quality
- **Voyage AI**: Optimized for search/retrieval

## Storage Considerations

### Embedding Dimensions
- 384 dim (MiniLM): ~1.5 KB per embedding (float32)
- 768 dim (MPNet): ~3 KB per embedding
- 1536 dim (OpenAI): ~6 KB per embedding

### Database Size Estimates
For 1000 projects + 5000 tasks + 10000 notes:
- MiniLM (384): ~24 MB
- MPNet (768): ~48 MB
- OpenAI (1536): ~96 MB

With metadata and indices: multiply by ~1.5x

## Use Cases

### 1. Intelligent Task Suggestions
When creating a new task, suggest related tasks from similar projects:
```bash
aio suggest-related --task "Implement OAuth2 login"
# Returns similar tasks from other projects with auth
```

### 2. Project Discovery
Find projects related to a concept:
```bash
aio search "machine learning pipeline"
# Returns all projects/tasks related to ML pipelines
```

### 3. Knowledge Reuse
Find code/notes from past projects:
```bash
aio find-knowledge "how did we handle rate limiting?"
# Searches notes and task descriptions
```

### 4. Dependency Detection
Automatically detect task dependencies based on semantic similarity:
```bash
aio analyze-dependencies --project "API Redesign"
# Suggests which tasks should be done first based on content
```

### 5. AI Agent Memory
Store and retrieve context for AI agents:
```python
# AI stores memory
memory.store(
    content="User prefers TypeScript over JavaScript",
    category="preference",
    importance=0.8
)

# AI retrieves relevant memory
context = memory.retrieve("What language should I use?")
# Returns: "User prefers TypeScript over JavaScript"
```

## Performance Optimization

1. **Batch Processing**: Embed multiple items at once
2. **Caching**: Store embeddings in memory for frequently accessed items
3. **Lazy Loading**: Only load embeddings when needed
4. **Approximate Search**: Use HNSW or similar for fast approximate NN
5. **Quantization**: Reduce precision to save space (float16 or int8)

## Security & Privacy

1. **Local-first**: Default to local embedding models
2. **API Key Management**: Secure storage for API keys
3. **Data Sanitization**: Remove sensitive info before embedding
4. **Encryption**: Encrypt embeddings at rest (optional)

## Future Enhancements

1. **Multi-modal Embeddings**: Support images, code, diagrams
2. **Temporal Embeddings**: Weight recent items higher
3. **User Feedback**: Learn from search interactions
4. **Automatic Summarization**: Generate summaries for long tasks
5. **Graph Embeddings**: Embed task relationships as a graph

## References

- sentence-transformers: https://www.sbert.net/
- ChromaDB: https://www.trychroma.com/
- sqlite-vss: https://github.com/asg017/sqlite-vss
- FAISS: https://github.com/facebookresearch/faiss

## Timeline

- **Phase 1**: 1-2 weeks (basic local embedding)
- **Phase 2**: 1 week (vector store integration)
- **Phase 3**: 1 week (API embeddings)
- **Phase 4**: 2 weeks (advanced features)
- **Phase 5**: 2-3 weeks (AI memory layer)

**Total**: ~7-9 weeks for full implementation
