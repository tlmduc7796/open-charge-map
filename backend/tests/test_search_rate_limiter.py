from backend.app.search_store import SearchRateLimiter


def test_rate_limit_is_per_client_and_resets_after_window() -> None:
    limiter = SearchRateLimiter(limit=2, window_s=60)

    assert limiter.allow("client-a", now=0)
    assert limiter.allow("client-a", now=1)
    assert not limiter.allow("client-a", now=2)
    assert limiter.allow("client-b", now=2)
    assert limiter.allow("client-a", now=60)
