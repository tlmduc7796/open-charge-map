import httpx
import pytest

from backend.app.domain.provider_http import get_with_retry


def test_provider_get_retries_transient_status_once() -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                503, headers={"Retry-After": "0"}, request=request
            )
        return httpx.Response(200, request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        response = get_with_retry(client, "https://provider.test/route", params={})

    assert response.status_code == 200
    assert calls == 2


def test_provider_get_does_not_retry_non_transient_status() -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            get_with_retry(client, "https://provider.test/route", params={})

    assert calls == 1
