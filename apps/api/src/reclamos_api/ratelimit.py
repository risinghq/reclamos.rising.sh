"""Limits how often one client address may search.

Each search embeds the query on the API's CPU, so one client sending many
could slow every other visitor. The limit lives in the process: with one API
task it is exact, and with several each task counts on its own.
"""

import math
import time
from collections import OrderedDict
from collections.abc import Callable

from fastapi import HTTPException, Request

# Past this many addresses the least recently seen one is forgotten, which
# only gives it a full bucket again.
MAX_CLIENTS = 10_000


class RateLimiter:
    """A token bucket per client: `per_minute` requests, refilled evenly."""

    def __init__(
        self,
        per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        max_clients: int = MAX_CLIENTS,
    ) -> None:
        self._capacity = float(per_minute)
        self._refill = per_minute / 60
        self._clock = clock
        self._max_clients = max_clients
        # client -> (tokens, when they were counted), least recently seen first.
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def wait(self, client: str) -> float:
        """Spend one request for `client`, or return the seconds until it may."""
        now = self._clock()
        tokens, counted = self._buckets.pop(client, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - counted) * self._refill)
        if tokens >= 1:
            tokens -= 1
            wait = 0.0
        else:
            wait = (1 - tokens) / self._refill
        self._buckets[client] = (tokens, now)
        if len(self._buckets) > self._max_clients:
            self._buckets.popitem(last=False)
        return wait


async def rate_limited(request: Request) -> None:
    """Refuse the request with 429 when its client is over the limit.

    The client is the address uvicorn resolved, which honours
    `X-Forwarded-For` only from the hosts in `FORWARDED_ALLOW_IPS`.
    """
    limiter: RateLimiter | None = request.app.state.rate_limiter
    if limiter is None:
        return
    client = request.client.host if request.client else "unknown"
    wait = limiter.wait(client)
    if wait:
        raise HTTPException(
            status_code=429,
            detail="too many searches; try again shortly",
            headers={"Retry-After": str(math.ceil(wait))},
        )
