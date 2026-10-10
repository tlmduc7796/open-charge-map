"""Bounded retry behavior for idempotent external provider requests."""

from __future__ import annotations

import time
from math import isfinite

import httpx

TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}
MAX_PROVIDER_ATTEMPTS = 2


def get_with_retry(
    client: httpx.Client, url: str, *, params: dict[str, str]
) -> httpx.Response:
    """Retry one time on transport errors or transient HTTP responses."""
    for attempt in range(MAX_PROVIDER_ATTEMPTS):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError:
            if attempt + 1 == MAX_PROVIDER_ATTEMPTS:
                raise
            time.sleep(0.2)
            continue

        if response.status_code in TRANSIENT_HTTP_STATUSES:
            if attempt + 1 == MAX_PROVIDER_ATTEMPTS:
                response.raise_for_status()
            retry_after = response.headers.get("Retry-After", "")
            try:
                parsed_delay_s = float(retry_after)
                delay_s = (
                    min(max(parsed_delay_s, 0.0), 0.5)
                    if isfinite(parsed_delay_s)
                    else 0.2
                )
            except ValueError:
                delay_s = 0.2
            time.sleep(delay_s)
            continue

        response.raise_for_status()
        return response

    raise RuntimeError("provider request exhausted retry attempts")
