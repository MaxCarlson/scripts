# Defect Analysis: LLM Monitor Persistent Recording Coupled to Live UI In-Memory Buffer

**Date:** 2026-11-02  
**Component:** `modules/llm_monitor` (`gateway.py`, `live_store.py`, `inference_recording.py`)  
**Status:** Documented Defect & Architectural Specification  

---

## 1. Problem Description

During extended multi-task benchmark runs (such as the sequential 10-task `aider-python-10` cohort under OpenCode / `qwen38_23GB` spanning ~53 minutes and 107 inference requests), the LLM Monitor Web UI displays:
- `"Input unavailable · metadata-only observation"`
- `"Content truncated by the observation source"`

Inspection of the persistent SQLite recording database (`reports/agent-bench-suite/monitor-integration-20261102-v2.sqlite3`) revealed that persistent database records were also truncated:
- 22 requests across tasks 9 and 10 contained `truncated=1` segments.
- 222 total content segments were truncated to 0 bytes (`text=""`).
- Tasks 1 through 8 were 100% complete and unclipped (0 truncated segments).
- Truncation began precisely when cumulative session content crossed ~2.0 MB.

---

## 2. Root Cause Analysis

The root cause is a tight architectural coupling between the **Live UI in-memory store** and the **durable SQLite recorder**:

1. **Global In-Memory Content Budget:**  
   In `llm_monitor/live_store.py`:
   ```python
   class LiveInferenceStore:
       def __init__(self, max_requests: int = 500, max_content_bytes: int = 2_000_000, ...):
           self.max_content_bytes = max_content_bytes
   ```
   `LiveInferenceStore` maintains an in-memory ring buffer across up to 500 requests, with a global ceiling of 2,000,000 bytes (2 MB).

2. **Ring Buffer Clipping:**  
   When new content segments are added in `add_request` or `append_content`:
   ```python
   remaining = max(0, self.max_content_bytes - self._content_bytes())
   if len(encoded) <= remaining:
       ...
   clipped = encoded[:remaining].decode("utf-8", errors="ignore")
   content.append(replace(segment, text=clipped, truncated=True))
   ```
   Once cumulative text across all stored requests reaches 2 MB, `remaining` drops to 0. All subsequent segments appended to the store have their text clipped to `""` and flagged `truncated=True`.

3. **Recorder Feeds Directly from Live Store:**  
   In `llm_monitor/gateway.py` (`_terminal`):
   ```python
   existing = next((item for item in self.store.requests() if item.request_id == request_id), None)
   ...
   candidate = InferenceRequest(**{**existing.__dict__, ...})
   ...
   self.recorder.record_request_final(
       updated_record,
       contents=candidate.content,
       hardware_samples=samples,
   )
   ```
   Instead of retaining unclipped request streams for authorized recording, `gateway.py` reads `candidate.content` directly from `self.store` (the live UI ring buffer). Consequently, the persistent SQLite recorder writes the already-clipped segments into `inference_contents`.

---

## 3. Evidence Preservation & Recovery Assessment

A critical investigation was conducted to determine whether complete inference transcripts can be recovered or if benchmark data was permanently lost.

### Finding: Complete native evidence is preserved
Harbor 0.25.0 isolates each trial inside a Docker container and automatically extracts the container's working directories into `harbor-jobs/` upon trial completion:
- **`opencode.db`** (`harbor-jobs/<job>/<task>/agent/opencode/xdg-data/opencode/opencode.db`):  
  Contains OpenCode's authoritative SQLite database, including all `session`, `message`, and `part` records with complete user prompts, assistant reasoning, and tool calls.
- **`trajectory.json`** (`harbor-jobs/<job>/<task>/agent/trajectory.json`):  
  Contains the full, unclipped 16-step execution trajectory for the agent.
- **`opencode.txt`** (`harbor-jobs/<job>/<task>/agent/opencode.txt`):  
  Contains the complete raw stdout/stderr event stream.

**Conclusion:** Although LLM Monitor's SQLite database contains partial content for tasks 9 and 10, **the benchmark run itself suffered zero data loss**. All prompt and response text is independently preserved in the native Harbor job artifacts bundled in the archive.

---

## 4. Minimal Architectural Correction

To prevent persistent recordings from being truncated by the UI ring buffer, persistent recording must be decoupled from `LiveInferenceStore`.

### Proposed Design

1. **Per-Request In-Flight Accumulator in Gateway:**  
   In `InferenceGateway`, maintain an unclipped content buffer keyed by active request ID:
   ```python
   self._active_request_contents: dict[str, list[ContentSegment]] = {}
   ```

2. **Request Lifecycle Decoupling:**
   - **On Request Start (`_handle_chat_completions`):**  
     `self._active_request_contents[request_id] = list(initial_segments)`  
     Forward clipped copy to `self.store` for the UI; retain full copy in `_active_request_contents`.
   - **On Streaming Chunk (`_append_content`):**  
     Append full chunk to `self._active_request_contents[request_id]`.  
     (Optional safety ceiling: 50 MB per individual request to guard against infinite loops).  
     Also forward chunk to `self.store.append_content` (where UI clipping applies).
   - **On Request Termination (`_terminal`):**  
     Pop unclipped contents:  
     ```python
     full_contents = self._active_request_contents.pop(request_id, None) or candidate.content
     self.recorder.record_request_final(
         updated_record,
         contents=full_contents,
         hardware_samples=samples,
     )
     ```

3. **Memory Safety Invariants:**
   - Active memory is proportional strictly to **current concurrent requests** (for benchmark runs, `jobs=1`, so only 1 request is held in memory at any time).
   - Inactive/completed request memory is immediately garbage-collected upon calling `pop()`.
   - The UI dashboard remains protected by `LiveInferenceStore`'s 2 MB budget without starving the durable database.
