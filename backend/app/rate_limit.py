"""Redis-backed fixed-window request limiting shared by API workers."""

from __future__ import annotations

import hashlib
import time
from typing import Protocol

WINDOW_SECONDS = 60
RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('TTL', KEYS[1])}
"""


class RedisEvaluator(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> list[int]: ...


async def consume_request(
    redis_client: RedisEvaluator,
    client_identity: str,
    request_class: str,
    limit: int,
    *,
    now: float | None = None,
) -> tuple[bool, int, int]:
    """Return allowed, remaining quota, and seconds until the window resets."""
    current = time.time() if now is None else now
    window = int(current // WINDOW_SECONDS)
    identity_hash = hashlib.sha256(client_identity.encode("utf-8")).hexdigest()
    key = f"smart-ev:ratelimit:v1:{request_class}:{identity_hash}:{window}"
    count, ttl = await redis_client.eval(
        RATE_LIMIT_SCRIPT,
        1,
        key,
        str(WINDOW_SECONDS),
    )
    return count <= limit, max(0, limit - count), max(1, ttl)
