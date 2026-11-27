# Inference content recording

The OpenAI-compatible gateway observes normalized Chat Completions messages and
stream deltas. It can capture message content, assistant output, reasoning
fields, and tool-call fragments exposed by the upstream response. This is
semantic capture, not a copy of raw HTTP traffic.

Recording is metadata-only unless content mode is explicitly enabled. Content
mode must be authorized at request start. Switching to metadata mode stops
capturing further content for active requests. Authentication headers and
cookies are not included in transcript segments.

The recorder writes each observed segment to the existing `inference_contents`
table through a bounded background queue. Queue limits apply to both item count
and estimated bytes. If either limit is exceeded or a SQLite write fails, the
recorder reports unhealthy status and the gateway rejects subsequent monitored
dispatches with HTTP 503. Already forwarded response bytes are not rewritten.
The dashboard retains a separate, bounded in-memory transcript; its truncation
does not determine persisted content.

Each append is committed independently. A request that was active when the
monitor process stopped is marked `interrupted` on the next recorder startup;
previously committed segments remain queryable. `flush()` uses a FIFO writer
barrier, and `stop()` returns whether the queue drained before its timeout.

Content is captured only where the gateway observes it. Oversized or malformed
upstream frames may exceed its parser's observation limit, and such gaps are
reported separately. Content mode does not imply access to hidden model
reasoning or content that the upstream did not expose.
