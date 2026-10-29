# Investigate retry behavior

Inspect `retry.py` and `client.py`. Create `answer.json` with exactly these keys: `retryable_statuses` (integer array) and `delay_rule` (string). Report the statuses accepted by `should_retry` and describe the delay calculation as `min(exponential_backoff, max_delay)`. Do not change source files.
