"""
Test URL collection for real download tests.
Mix of valid and invalid URLs to test error handling.
"""

# Known good AEBN URLs (verified accessible)
GOOD_URLS = [
    "https://straight.aebn.com/straight/movies/218561/share-my-boyfriend-4#scene-989545",
    "https://straight.aebn.com/straight/movies/305642/a-day-with-agatha-vega#scene-1260129",
    "https://straight.aebn.com/straight/movies/309021/hot-and-mean-37",
]

# Known bad/invalid URLs for error testing
BAD_URLS = [
    "https://straight.aebn.com/straight/movies/999999999/nonexistent-movie",
    "https://straight.aebn.com/straight/movies/invalid/bad-format",
    "https://invalid-domain.aebn.com/straight/movies/123/test",
]

# URLs with specific characteristics for testing
SCENE_URL = "https://straight.aebn.com/straight/movies/218561/share-my-boyfriend-4#scene-989545"
FULL_MOVIE_URL = "https://straight.aebn.com/straight/movies/305642/a-day-with-agatha-vega"
