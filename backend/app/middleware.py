"""ASGI middleware: request-scoped client context + unified access log."""

from __future__ import annotations

import logging
import time

from .config import client_addr_var

access_logger = logging.getLogger("app.access")


class AccessLogMiddleware:
    """Pure ASGI middleware (registered via ``app.add_middleware``).

    - Stashes the client ``ip:port`` into ``client_addr_var`` for the whole
      request, so every log line emitted during it (including inside SSE
      streaming generators) carries the client in the unified format.
    - Emits one access log line via the ``app.access`` logger after the
      response completes, reusing the same unified format.

    Being a raw ASGI wrapper (not BaseHTTPMiddleware) avoids task-group context
    copies, so the context var stays live for StreamingResponse generators.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        addr = f"{client[0]}:{client[1]}" if client else "-"
        token = client_addr_var.set(addr)

        status_code: int | None = None

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        start = time.perf_counter()
        error = False
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            error = True
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            method = scope.get("method", "-")
            path = scope.get("path", "-")
            status = status_code or (500 if error else 0)
            access_logger.info("%s %s %d %.0fms", method, path, status, duration_ms)
            client_addr_var.reset(token)