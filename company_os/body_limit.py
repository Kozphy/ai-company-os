"""ASGI request-size guard; counts actual streamed bytes, not only headers."""

from collections.abc import Awaitable, Callable
from typing import Any

ASGIApp = Callable[..., Awaitable[None]]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class _BodyTooLarge(Exception):
    """The streamed body exceeded ``max_bytes``."""


class BodyLimitMiddleware:
    """Reject HTTP requests whose body exceeds a byte limit.

    A declared ``Content-Length`` above the limit is rejected before the
    application runs. Streamed bodies are counted as chunks arrive, so a
    missing or low ``Content-Length`` cannot bypass the limit.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = 1_000_000):
        """Store the downstream app and the byte limit.

        Args:
            app: Downstream ASGI application.
            max_bytes: Maximum accepted body size. Defaults to 1,000,000.
        """
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        """Apply the body limit to one ASGI call.

        Non-HTTP scopes are forwarded unchanged.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return
        consumed = 0

        async def limited_receive() -> dict[str, Any]:
            """Return the next ASGI message after counting its body bytes.

            Returns:
                The downstream receive message.

            Raises:
                _BodyTooLarge: The cumulative body is larger than ``max_bytes``.
            """
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await self._reject(send)

    async def _reject(self, send: Send) -> None:
        """Send a 413 JSON response and stop.

        Args:
            send: ASGI send callable.
        """
        body = b'{"detail":"request too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
