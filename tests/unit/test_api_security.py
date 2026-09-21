from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.api import security
from src.core import exceptions as exc
from src.core.exceptions import APIConfigError, ServerBusyError, UploadRateLimitedError

TOKEN = "t" * 43  # what scripts/generate_api_token.py produces (43 chars)


# --- SlidingWindowRateLimiter ---
class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_rate_limiter_allows_up_to_the_limit_then_refuses() -> None:
    limiter = security.SlidingWindowRateLimiter(3, 60, clock=_Clock())
    for _ in range(3):
        limiter.check("a")
    with pytest.raises(UploadRateLimitedError) as info:
        limiter.check("a")
    assert info.value.retry_after == 60


def test_rate_limiter_window_slides() -> None:
    clock = _Clock()
    limiter = security.SlidingWindowRateLimiter(2, 60, clock=clock)
    limiter.check("a")
    clock.now += 30
    limiter.check("a")
    with pytest.raises(UploadRateLimitedError) as info:
        limiter.check("a")
    assert info.value.retry_after == 30  # the oldest event leaves the window in 30 s
    clock.now += 31
    limiter.check("a")  # the first event expired


def test_rate_limiter_keys_are_independent() -> None:
    limiter = security.SlidingWindowRateLimiter(1, 60, clock=_Clock())
    limiter.check("a")
    limiter.check("b")
    with pytest.raises(UploadRateLimitedError):
        limiter.check("a")


def test_rate_limiter_fails_closed_when_key_table_is_full_then_recovers() -> None:
    clock = _Clock()
    limiter = security.SlidingWindowRateLimiter(1, 60, max_keys=2, clock=clock)
    limiter.check("a")
    limiter.check("b")
    with pytest.raises(UploadRateLimitedError):  # a flood of new keys cannot grow memory
        limiter.check("c")
    clock.now += 61  # a and b expire and are dropped
    limiter.check("c")


# --- ConcurrencyLimiter ---
def test_concurrency_limiter_refuses_beyond_the_limit() -> None:
    limiter = security.ConcurrencyLimiter(2, retry_after=7)
    with limiter.slot(), limiter.slot():
        with pytest.raises(ServerBusyError) as info, limiter.slot():
            pass
        assert info.value.retry_after == 7
    with limiter.slot():  # slots were released
        pass


def test_concurrency_slot_is_released_when_the_work_fails() -> None:
    limiter = security.ConcurrencyLimiter(1)
    with pytest.raises(RuntimeError), limiter.slot():
        raise RuntimeError("boom")
    with limiter.slot():
        pass


# --- API token ---
def _app() -> TestClient:
    app = FastAPI()

    @app.get("/private", dependencies=[Depends(security.require_token)])
    def private() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


@pytest.fixture
def token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("API_TOKEN", TOKEN)
    return TOKEN


def test_valid_token_is_accepted(token: str) -> None:
    response = _app().get("/private", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        f"Bearer {'x' * 43}",  # right length, wrong value
        f"Bearer {TOKEN[:-1]}",  # one character short
        f"Bearer {TOKEN} ",  # trailing space
        f"Basic {TOKEN}",  # wrong scheme
        TOKEN,  # no scheme
    ],
)
def test_missing_or_wrong_token_is_refused(token: str, header: str | None) -> None:
    headers = {"Authorization": header} if header is not None else {}
    response = _app().get("/private", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert TOKEN not in response.text


def test_no_server_token_means_everything_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed: a missing API_TOKEN must never turn into an open API."""
    monkeypatch.delenv("API_TOKEN", raising=False)
    for headers in ({}, {"Authorization": "Bearer "}, {"Authorization": "Bearer anything"}):
        assert _app().get("/private", headers=headers).status_code == 500


def test_weak_server_token_is_refused_even_if_the_client_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_TOKEN", "short")
    response = _app().get("/private", headers={"Authorization": "Bearer short"})
    assert response.status_code == 500
    with pytest.raises(APIConfigError):
        security.load_api_token()


# --- to_http_error ---
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (exc.UploadTooLargeError("x"), 413),
        (exc.InvalidUploadError("x"), 415),
        (exc.UploadRateLimitedError("x", 12), 429),
        (exc.ServerBusyError("x", 5), 503),
        (exc.APIConfigError("x"), 500),
        (exc.PDFTooLargeError("x"), 413),
        (exc.PDFCorruptedError("x"), 422),
        (exc.EmptyDocumentError("x"), 422),
        (exc.UnsupportedPDFError("x"), 422),
        (exc.DailyQuotaExceededError("x"), 429),
        (exc.RateLimitError("x"), 429),
        (exc.LLMAuthError("x"), 503),
        (exc.ProviderTimeoutError("x"), 504),
        (exc.ExtractionFailedError("x"), 502),
        (exc.StorageError("x"), 500),
        (RuntimeError("x"), 500),
    ],
)
def test_error_translation_status_codes(error: BaseException, status: int) -> None:
    assert security.to_http_error(error).status == status


def test_error_translation_never_leaks_the_exception_text() -> None:
    secret = r"C:\Users\ibrahima\projets\data\uploads\3f9a.pdf sk-SECRET"
    for error in (exc.PDFCorruptedError(secret), exc.StorageError(secret), RuntimeError(secret)):
        assert "SECRET" not in security.to_http_error(error).message
        assert "uploads" not in security.to_http_error(error).message


def test_retry_after_is_forwarded_and_daily_quota_has_none() -> None:
    assert security.to_http_error(exc.UploadRateLimitedError("x", 12)).retry_after == 12
    assert security.to_http_error(exc.ServerBusyError("x", 5)).retry_after == 5
    assert security.to_http_error(exc.RateLimitError("x")).retry_after == 60
    assert security.to_http_error(exc.DailyQuotaExceededError("x")).retry_after is None


def _leaf_exceptions() -> list[type[exc.InvoiceAIError]]:
    leaves, stack = [], list(exc.InvoiceAIError.__subclasses__())
    while stack:
        cls = stack.pop()
        children = cls.__subclasses__()
        stack.extend(children)
        if not children:
            leaves.append(cls)
    return leaves


@pytest.mark.parametrize("cls", _leaf_exceptions(), ids=lambda cls: cls.__name__)
def test_every_concrete_exception_has_a_specific_http_mapping(cls: type) -> None:
    """Guard for the future: a new exception must be added to the translation table."""
    error = (
        cls("x")
        if not issubclass(cls, (exc.UploadRateLimitedError, exc.ServerBusyError))
        else cls("x", 1)
    )
    assert security.to_http_error(error).message != "Erreur interne."
