from retry import MAX_DELAY, exponential_backoff

RETRYABLE_STATUSES = (429, 503)


def should_retry(status, attempt):
    return status in RETRYABLE_STATUSES and min(exponential_backoff(attempt), MAX_DELAY) <= MAX_DELAY
