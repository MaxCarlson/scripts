# Make retry attempts configurable

Coordinate changes in `retry_config.py` and `client.py`: set the default `MAX_RETRIES` to 5, and have `retry_count(status)` return that configured limit for retryable HTTP statuses 429 and 503, otherwise return 0. Do not hardcode 5 in `client.py`; import the shared setting. Only edit the two allowed Python files.
