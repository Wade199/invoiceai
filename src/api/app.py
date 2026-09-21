from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.api.middleware import (
    MULTIPART_MARGIN_BYTES,
    SECURITY_HEADERS,
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from src.api.routes import router
from src.api.security import (
    ConcurrencyLimiter,
    SlidingWindowRateLimiter,
    load_api_token,
    to_http_error,
)
from src.api.upload import max_upload_bytes, purge_stale_uploads
from src.core.crypto import get_cipher
from src.core.database import get_engine, session_scope
from src.core.env import get_int_env, load_env
from src.core.exceptions import InvoiceAIError
from src.services.cache import purge_expired as purge_expired_cache
from src.services.repository import InvoiceRepository

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_HOSTS = "127.0.0.1,localhost"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Refuse to start misconfigured, then apply the retention rules."""
    load_api_token()  # APIConfigError if missing / weak: the server does not start
    get_cipher()  # StorageError if the encryption key is missing / invalid
    get_engine()  # opens the database and creates the tables

    with session_scope() as session:
        purged_records = InvoiceRepository(session).purge_expired()
    logger.info(
        "Startup purge: %d invoice(s), %d cache file(s), %d orphan upload(s)",
        purged_records,
        purge_expired_cache(),
        purge_stale_uploads(),
    )
    yield


def _secure(response: JSONResponse) -> JSONResponse:
    """Responses built by ServerErrorMiddleware sit outside our middlewares: add the headers."""
    for name, value in SECURITY_HEADERS:
        response.headers.setdefault(name.decode(), value.decode())
    return response


def create_app() -> FastAPI:
    """Build the API. Settings are read from the environment when this is called."""
    load_env()
    docs_enabled = os.getenv("API_DOCS") == "1"  # the API map is not published by default
    app = FastAPI(
        title="InvoiceAI",
        lifespan=_lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    # Shared by the routes through app.state; used from the event loop only (see security.py).
    app.state.rate_limiter = SlidingWindowRateLimiter(
        get_int_env("UPLOAD_RATE_LIMIT_PER_MINUTE", 10), 60
    )
    app.state.concurrency = ConcurrencyLimiter(get_int_env("MAX_CONCURRENT_EXTRACTIONS", 2))

    # add_middleware puts the LAST added outermost: security headers wrap everything, then the
    # Host check (DNS rebinding), then the body size limit closest to the application.
    app.add_middleware(
        BodySizeLimitMiddleware, max_bytes=max_upload_bytes() + MULTIPART_MARGIN_BYTES
    )
    allowed_hosts = [
        host.strip()
        for host in os.getenv("ALLOWED_HOSTS", _DEFAULT_ALLOWED_HOSTS).split(",")
        if host.strip()
    ]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.exception_handler(InvoiceAIError)
    async def _domain_error(_request: Request, error: InvoiceAIError) -> JSONResponse:
        info = to_http_error(error)
        # Operators need to know WHAT failed: the type and the status, never the message
        # (it can hold paths or content).
        logger.warning("Request failed: %s -> %d", type(error).__name__, info.status)
        headers = {"Retry-After": str(info.retry_after)} if info.retry_after else None
        return _secure(JSONResponse({"detail": info.message}, info.status, headers))

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_request: Request, error: RequestValidationError) -> JSONResponse:
        # FastAPI's default answer echoes the received value ("input"): keep only where and why.
        errors = [{"loc": list(item["loc"]), "msg": item["msg"]} for item in error.errors()]
        return _secure(JSONResponse({"detail": "Requête invalide.", "errors": errors}, 422))

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, error: Exception) -> JSONResponse:
        logger.error("Unhandled error: %s", type(error).__name__)  # never the message
        return _secure(JSONResponse({"detail": "Erreur interne."}, 500))

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness only: no token, and no data."""
        return {"status": "ok"}

    app.include_router(router)
    return app


# No module-level `app`: creating it at import time would read the real .env (every key)
# into whatever process merely imports this module. Run it with `uvicorn --factory`.
