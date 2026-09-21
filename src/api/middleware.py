from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Extra bytes allowed on top of the file limit: multipart boundaries and part headers.
MULTIPART_MARGIN_BYTES = 64 * 1024

_TOO_LARGE_BODY = json.dumps({"detail": "Fichier trop volumineux."}).encode("utf-8")


class BodySizeLimitMiddleware:
    """Reject request bodies larger than `max_bytes`, *while* they are being received.

    Why a middleware and not a check in the endpoint: Starlette parses the whole
    multipart body into a temporary file BEFORE the endpoint runs. Without this, a 5 GB
    upload is already on disk when our code first sees the file size.

    Two layers: a declared `Content-Length` over the limit is refused immediately, and
    the bytes actually received are counted (the header can be missing or lie, e.g.
    chunked transfer encoding).

    When the limit is crossed mid-stream the application is told the client disconnected
    (so it stops reading), whatever it answers afterwards is dropped, and the client gets
    a 413. Raising an exception instead does not work: FastAPI turns any error raised
    while reading the body into a generic 400.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            await _reject(send)
            return

        received = 0
        too_large = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            if too_large:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if too_large:
                return  # the application's answer (a generic 400) is replaced by our 413
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not too_large:
                raise
        # If the application already started answering before the limit was crossed, the
        # status cannot change any more: the server closes the connection.
        if too_large and not response_started:
            await _reject(send)


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None  # malformed: fall back to counting the received bytes
    return None


async def _reject(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_TOO_LARGE_BODY)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _TOO_LARGE_BODY})
