RETRYABLE_STATUSES = (429, 503)


def retry_count(status):
    if status in RETRYABLE_STATUSES:
        return 3
    return 0
