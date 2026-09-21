from __future__ import annotations

import hmac
import logging
import math
import os
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import HTTPException, Request

from src.core.env import load_env
from src.core.exceptions import (
    APIConfigError,
    DailyQuotaExceededError,
    EmptyDocumentError,
    ExtractionFailedError,
    InvalidUploadError,
    InvoiceAIError,
    LLMAuthError,
    PDFCorruptedError,
    PDFTooLargeError,
    ProviderTimeoutError,
    RateLimitError,
    ServerBusyError,
    StorageError,
    UnsupportedPDFError,
    UploadRateLimitedError,
    UploadTooLargeError,
)

logger = logging.getLogger(__name__)

_MIN_TOKEN_LENGTH = 32
_MAX_RATE_LIMIT_KEYS = 1_000


# --- Authentication (V1: one local user, one shared secret) -----------------------------
def load_api_token() -> str:
    """Return API_TOKEN, refusing a missing or weak one (fail closed).

    Raises:
        APIConfigError: If API_TOKEN is unset or shorter than 32 characters.
    """
    load_env()
    token = os.getenv("API_TOKEN", "")
    if len(token) < _MIN_TOKEN_LENGTH:
        raise APIConfigError(
            f"API_TOKEN is missing or shorter than {_MIN_TOKEN_LENGTH} characters "
            "(generate one with scripts/generate_api_token.py)"
        )
    return token


def require_token(request: Request) -> None:
    """FastAPI dependency: only requests carrying `Authorization: Bearer <API_TOKEN>` pass.

    The comparison is constant-time. Without a valid server-side token the API refuses
    everything: a misconfiguration must never turn into an open door.
    """
    try:
        expected = load_api_token()
    except APIConfigError as exc:
        logger.error("%s", exc)
        raise HTTPException(status_code=500, detail="Configuration du serveur invalide.") from exc

    scheme, _, provided = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401,
            detail="Authentification requise.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def client_key(request: Request) -> str:
    """Identify the caller for rate limiting: the socket address.

    `X-Forwarded-For` is deliberately NOT read: any client can forge it.
    """
    return request.client.host if request.client else "unknown"


# --- Limits ----------------------------------------------------------------------------
class ConcurrencyLimiter:
    """Refuse (do not queue) work beyond `limit` simultaneous operations.

    Not thread-safe on purpose: it is meant to be used from the asyncio event loop, where
    `slot()` runs without yielding between the check and the increment.
    """

    def __init__(self, limit: int, retry_after: int = 5) -> None:
        self._limit = limit
        self._retry_after = retry_after
        self._active = 0

    @contextmanager
    def slot(self) -> Iterator[None]:
        if self._active >= self._limit:
            raise ServerBusyError("Too many extractions in progress", self._retry_after)
        self._active += 1
        try:
            yield
        finally:
            self._active -= 1


class SlidingWindowRateLimiter:
    """At most `max_events` per `window_seconds` and per key, kept in memory.

    The number of tracked keys is capped so that a flood of distinct keys cannot grow the
    memory without bound; when the cap is hit the limiter fails closed.
    """

    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        *,
        max_keys: int = _MAX_RATE_LIMIT_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_events = max_events
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._events: dict[str, deque[float]] = {}

    def check(self, key: str) -> None:
        """Record one event for `key`, or refuse it.

        Raises:
            UploadRateLimitedError: If the key already used its quota in the window.
        """
        now = self._clock()
        events = self._events.get(key)
        if events is None:
            if len(self._events) >= self._max_keys:
                self._drop_expired(now)
            if len(self._events) >= self._max_keys:
                raise UploadRateLimitedError("Rate limiter is full", math.ceil(self._window))
            events = self._events[key] = deque()

        while events and now - events[0] >= self._window:
            events.popleft()
        if len(events) >= self._max_events:
            retry_after = max(1, math.ceil(self._window - (now - events[0])))
            raise UploadRateLimitedError("Too many uploads", retry_after)
        events.append(now)

    def _drop_expired(self, now: float) -> None:
        for key in [
            key
            for key, events in self._events.items()
            if not events or now - events[-1] >= self._window
        ]:
            del self._events[key]


# --- Error translation -----------------------------------------------------------------
@dataclass(frozen=True)
class HttpError:
    """What the client may see: never the exception text (it can contain server paths)."""

    status: int
    message: str
    retry_after: int | None = None


# Order matters: subclasses (DailyQuotaExceededError) before their parents (RateLimitError).
_HTTP_ERRORS: tuple[tuple[type[InvoiceAIError], int, str], ...] = (
    (UploadTooLargeError, 413, "Fichier trop volumineux."),
    (InvalidUploadError, 415, "Fichier invalide : seul un PDF non vide est accepté."),
    (UploadRateLimitedError, 429, "Trop de requêtes, réessayez dans quelques instants."),
    (ServerBusyError, 503, "Serveur occupé, réessayez dans quelques instants."),
    (APIConfigError, 500, "Configuration du serveur invalide."),
    (PDFTooLargeError, 413, "PDF trop volumineux ou trop complexe à analyser."),
    (PDFCorruptedError, 422, "Le PDF est illisible ou corrompu."),
    (EmptyDocumentError, 422, "Le PDF ne contient aucun texte."),
    (UnsupportedPDFError, 422, "PDF scanné non supporté : il ne contient pas de texte."),
    (DailyQuotaExceededError, 429, "Quota d'analyse du jour atteint, réessayez demain."),
    (RateLimitError, 429, "Service d'analyse saturé, réessayez dans une minute."),
    (LLMAuthError, 503, "Service d'analyse indisponible."),
    (ProviderTimeoutError, 504, "Le service d'analyse ne répond pas, réessayez."),
    (ExtractionFailedError, 502, "L'analyse a échoué pour ce document."),
    (StorageError, 500, "Erreur de stockage interne."),
)
_DEFAULT_RETRY_AFTER = {RateLimitError: 60}


def to_http_error(exc: BaseException) -> HttpError:
    """Translate any exception into a status code and a fixed, safe French message."""
    for exc_type, status, message in _HTTP_ERRORS:
        if isinstance(exc, exc_type):
            retry_after = getattr(exc, "retry_after", None)
            if retry_after is None and not isinstance(exc, DailyQuotaExceededError):
                retry_after = next(
                    (v for t, v in _DEFAULT_RETRY_AFTER.items() if isinstance(exc, t)), None
                )
            return HttpError(status, message, retry_after)
    if not isinstance(exc, InvoiceAIError):
        logger.error("Unexpected error: %s", type(exc).__name__)
    return HttpError(500, "Erreur interne.")
