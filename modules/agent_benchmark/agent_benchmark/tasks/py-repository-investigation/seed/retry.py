MAX_DELAY = 8


def exponential_backoff(attempt):
    return 2 ** max(attempt - 1, 0)
