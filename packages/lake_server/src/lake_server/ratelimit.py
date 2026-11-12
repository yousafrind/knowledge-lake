"""Fixed-window rate limit per bearer token (per client address without one). Stage C only."""

import time

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RateLimit:
    # ponytail: in-process counters; a second API replica would need a shared store
    def __init__(self, app: ASGIApp, per_minute: int) -> None:
        self.app, self.limit = app, per_minute
        self.hits: dict[str, tuple[int, int]] = {}  # key -> (minute, count)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.limit <= 0:
            return await self.app(scope, receive, send)
        req = Request(scope)
        key = req.headers.get("authorization") or (req.client.host if req.client else "?")
        minute = int(time.time() // 60)
        m, n = self.hits.get(key, (minute, 0))
        n = n + 1 if m == minute else 1
        self.hits[key] = (minute, n)
        if n > self.limit:
            return await PlainTextResponse("rate limit", 429, {"Retry-After": "60"})(
                scope, receive, send
            )
        await self.app(scope, receive, send)
