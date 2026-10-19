# Implementation Plan: Repair and Consolidate LM Studio Console Client

**Goal:** Implement a reliable, convenient, cross-platform command-line client (`lmst`) with backward-compatible `lmstui` support for directly interacting with locally loaded LLMs in LM Studio without external dependencies.

**Architecture:** Use Python standard library (`urllib.request`) for zero-dependency HTTP transport and SSE stream parsing. Consolidate `lmst.py` and `lmstui` into a unified backend supporting both `/v1` (OpenAI compatible) and `/api/v0` (REST) endpoints. Provide model auto-selection from loaded models, JSON-based persistent defaults per-model and globally, clean stdout piping, stderr statistics, and interactive REPL.

**Tech Stack:** Python 3.10+, `urllib.request`, `argparse`, `pytest`, `json`.

## Root Cause Analysis of Existing Failures

1. `api.py` imports `now_seconds` from `lmstui.http_client`, but `http_client.py` never defined it.
2. `api.py` imports `iter_sse_events` from `lmstui.sse`, but `sse.py` defines `parse_sse_events`.
3. `cli.py` imports `LmStudioApi`, but `api.py` defined `LMStudioAPI`.
4. `cli.py` and `repl.py` call methods like `chat_rest`, `iter_stream_text_from_lines`, and `embeddings_rest` which were missing or had mismatched signatures in `api.py`.
5. `api.py` called `post_json_stream` on `HttpClient`, which only implemented `stream_lines`.
6. `lmst.py` was a standalone script outside the package relying on `httpx` (not declared in `pyproject.toml`), while `pyproject.toml` only exposed `lmstui = "lmstui.cli:main"` rather than `lmst`.

## Key Architectural Decisions

1. **Zero External Dependencies**:
   - Rely strictly on Python standard library (`urllib.request`, `json`, `argparse`, `dataclasses`, `typing`).
   - Ensures seamless operation on Windows, WSL2, macOS, Linux, and Termux without requiring pip installation of third-party wheels.
2. **Unified Core Engine**:
   - `lmstui.http_client`: Synchronous requests + line-based generator for SSE streaming. Provides `now_seconds() -> float` helper.
   - `lmstui.sse`: Parse SSE lines into structured events and stream chunks, extracting delta content and reasoning deltas.
   - `lmstui.api`: Unified `LMStudioAPI` (aliased as `LmStudioApi` and `LMStudioClient`), handling `/v1/chat/completions`, `/v1/models`, `/v1/responses`, and `/api/v0/*` fallback.
3. **Loaded Model Resolution**:
   - Query `/api/v0/models` and `/v1/models`.
   - Identify loaded models (`state == "loaded"` in REST, or listed models in OpenAI mode).
   - If user doesn't pass `-m/--model`:
     - If exactly 1 loaded model -> pick it.
     - If multiple loaded models -> pick deterministically (first sorted by ID), and warn user on stderr with list of other loaded models.
     - If 0 loaded models -> raise informative error.
   - Print model info on stderr before requests unless `-S/--silent` is passed.
4. **Persistent Defaults**:
   - Store settings in `modules/lmstui/lmstui/defaults.json`.
   - Structure:
     ```json
     {
       "global": {},
       "models": {}
     }
     ```
   - Flags:
     - `-D, --set-default KEY=VALUE`
     - `-d, --show-defaults`
     - `-C, --clear-defaults`
     - `-M, --per-model`
5. **Output and CLI Conventions**:
   - Standard stdout: Assistant answer only (suitable for piping).
   - `--stats / -a`: Detailed token counts, reasoning tokens (not double counted), elapsed time, tokens/sec to stderr.
   - `--json / -j`: Full raw JSON response to stdout.
   - Stdin piping: If `-p` is omitted and stdin is piped (`not sys.stdin.isatty()`), read prompt from stdin.
   - Every CLI option has short and long flags.
6. **Packaging and Discovery**:
   - `[project.scripts]` exposes `lmst = "lmstui.cli:main_lmst"` and `lmstui = "lmstui.cli:main_lmstui"`.
   - Bump version from `0.1.0` to `1.0.0` (MAJOR bump for console script change).
