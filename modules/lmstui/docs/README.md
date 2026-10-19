# LM Studio Client (`lmstui` / `lmst`) Documentation

## Overview

The `lmstui` package provides a lightweight, dependency-free, cross-platform command-line client for interacting directly with locally loaded LLMs running in LM Studio (or any OpenAI-compatible server).

Key components:
- `lmst`: Primary console CLI for model discovery, one-shot requests, and interactive streaming chat.
- `lmstui`: Backward-compatible console CLI supporting legacy server status, model inspection, embeddings, and log streaming commands.
- `lmstui.api`: Unified API client managing both OpenAI `/v1` endpoints and LM Studio REST `/api/v0` endpoints.
- `lmstui.http_client`: Standard-library HTTP client (`urllib.request`) supporting synchronous JSON requests and chunked/SSE streaming with zero third-party dependencies.
- `lmstui.defaults`: Persistent configuration for global and model-specific defaults stored in module JSON.

## Documentation Index

- [HANDOFF.md](HANDOFF.md): Immediate state, branch, staged/unstaged state, and active work pointers.
- [plans/HANDOFF.md](plans/HANDOFF.md): Plan index and active/recent implementation plans.
