from __future__ import annotations

import asyncio

import pytest

from src.api.middleware import BodySizeLimitMiddleware

CHUNK = b"x" * 1000


def _run(chunks, max_bytes, *, headers=None, scope_type="http", app_error=None):
    """Drive the middleware with a fake ASGI stream and report what happened."""
    state = {"received": 0, "app_called": False, "sent": [], "app_saw_disconnect": False}
    messages = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]

    async def receive():
        state["received"] += 1
        return messages.pop(0)

    async def send(message):
        state["sent"].append(message)

    async def app(scope, receive, send):
        state["app_called"] = True
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                state["app_saw_disconnect"] = True
                # what FastAPI does when the body cannot be read: answer a generic 400
                await send({"type": "http.response.start", "status": 400, "headers": []})
                await send({"type": "http.response.body", "body": b"parse error"})
                if app_error:
                    raise app_error
                return
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope = {"type": scope_type, "headers": headers or []}
    asyncio.run(BodySizeLimitMiddleware(app, max_bytes)(scope, receive, send))
    statuses = [m["status"] for m in state["sent"] if m["type"] == "http.response.start"]
    return state, statuses


def test_body_within_the_limit_passes_through() -> None:
    state, statuses = _run([CHUNK] * 3, max_bytes=3000)
    assert statuses == [200] and not state["app_saw_disconnect"]


def test_body_exactly_at_the_limit_is_accepted() -> None:
    assert _run([CHUNK] * 3, max_bytes=3000)[1] == [200]
    assert _run([CHUNK] * 3, max_bytes=2999)[1] == [413]


def test_streaming_body_is_cut_as_soon_as_the_limit_is_crossed() -> None:
    state, statuses = _run([CHUNK] * 1000, max_bytes=3500)
    assert statuses == [413]  # only OUR answer: the app's generic 400 was dropped
    assert state["app_saw_disconnect"]
    assert state["received"] == 4  # stopped reading after the 4th chunk, not 1000


def test_declared_content_length_over_the_limit_never_reaches_the_app() -> None:
    state, statuses = _run([CHUNK], 500, headers=[(b"content-length", b"999999")])
    assert statuses == [413] and not state["app_called"] and state["received"] == 0


def test_lying_content_length_is_not_trusted() -> None:
    """Header says 10 bytes, the body is 100 KB: the bytes actually received decide."""
    state, statuses = _run([CHUNK] * 100, 5000, headers=[(b"content-length", b"10")])
    assert statuses == [413]


def test_malformed_content_length_falls_back_to_counting() -> None:
    assert _run([CHUNK] * 100, 5000, headers=[(b"content-length", b"abc")])[1] == [413]
    assert _run([CHUNK], 5000, headers=[(b"content-length", b"abc")])[1] == [200]


def test_non_http_scopes_are_left_alone() -> None:
    state, _ = _run([CHUNK], 1, scope_type="lifespan")
    assert state["app_called"]


def test_error_raised_by_the_app_after_the_cut_is_swallowed_and_413_sent() -> None:
    _, statuses = _run([CHUNK] * 100, 3000, app_error=RuntimeError("parse failure"))
    assert statuses == [413]


def test_unrelated_app_errors_still_propagate() -> None:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        pass

    async def broken_app(scope, receive, send):
        raise ValueError("real bug")

    middleware = BodySizeLimitMiddleware(broken_app, 1000)
    with pytest.raises(ValueError, match="real bug"):
        asyncio.run(middleware({"type": "http", "headers": []}, receive, send))
