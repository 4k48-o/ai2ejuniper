"""Per-request ID for log correlation and client tracing (X-Request-ID)."""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the current HTTP request id, if running inside a request."""
    return _request_id_ctx.get()


def _header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1").strip()
    return None


def _sanitize_incoming_request_id(raw: str) -> str | None:
    """Reject empty / control chars; cap length for logs and headers."""
    s = raw.strip()[:128]
    if not s:
        return None
    if any(c in s for c in "\n\r\x00"):
        return None
    return s


class RequestIdFilter(logging.Filter):
    """Inject ``record.request_id`` from context for format strings."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = get_request_id()
        record.request_id = rid if rid else "-"
        return True


class RequestIDMiddleware:
    """ASGI: set request id context, append ``X-Request-ID`` on responses.

    Accepts ``X-Request-ID`` or ``X-Correlation-ID`` from the client; otherwise
    generates a UUID. Uses ASGI (not ``BaseHTTPMiddleware``) so streaming/SSE
    responses are not fully buffered.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = list(scope.get("headers") or [])
        raw = (
            _header_value(headers, b"x-request-id")
            or _header_value(headers, b"x-correlation-id")
        )
        rid = _sanitize_incoming_request_id(raw) if raw else None
        if not rid:
            rid = str(uuid.uuid4())

        token = _request_id_ctx.set(rid)

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                out_headers = list(message.get("headers") or [])
                out_headers = [h for h in out_headers if h[0].lower() != b"x-request-id"]
                out_headers.append((b"x-request-id", rid.encode("utf-8")))
                message = {**message, "headers": out_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _request_id_ctx.reset(token)
