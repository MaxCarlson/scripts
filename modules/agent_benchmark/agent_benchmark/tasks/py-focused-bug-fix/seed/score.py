def clamp_score(score):
    """Return a score capped at the upper bound."""
    return min(score, 100)
