from __future__ import annotations

from pathlib import Path

import pytest
from google.genai.errors import ClientError, ServerError

from src.core.exceptions import (
    ExtractionFailedError,
    LLMAuthError,
    ProviderTimeoutError,
    RateLimitError,
)
from src.llm import gemini_adapter
from src.models.schemas import ExtractedInvoice
from src.ocr.extractor import ExtractedDocument


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Skip tenacity's real backoff sleep so retry tests stay fast."""
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)


class _FakeStructuredLLM:
    """Stand-in for `llm.with_structured_output(...)` in tests.

    Raises `error` on the first `fail_times` calls, then returns `result`.
    """

    def __init__(self, result=None, error=None, fail_times=0):
        self.result = result
        self.error = error
        self.fail_times = fail_times
        self.calls = 0

    def invoke(self, prompt: str):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return self.result


def _sample_document() -> ExtractedDocument:
    return ExtractedDocument(
        text="FACTURE INV-1\nDate: 2026-01-01\nTotal TTC: 100.00",
        page_count=1,
        source_file=Path("tests/fixtures/pdfs/sample_invoice.pdf"),
    )


def test_extract_invoice_data_returns_parsed_invoice(monkeypatch):
    expected = ExtractedInvoice(invoice_number="INV-1", total_ttc=100.0)
    fake_llm = _FakeStructuredLLM(result=expected)
    monkeypatch.setattr(gemini_adapter, "_build_structured_llm", lambda: fake_llm)

    result = gemini_adapter.extract_invoice_data(_sample_document())

    assert result is expected
    assert fake_llm.calls == 1


def test_extract_invoice_data_raises_rate_limit_error_on_429(monkeypatch):
    client_error = ClientError(429, {"error": {"message": "quota exceeded"}})
    fake_llm = _FakeStructuredLLM(error=client_error, fail_times=3)
    monkeypatch.setattr(gemini_adapter, "_build_structured_llm", lambda: fake_llm)

    with pytest.raises(RateLimitError):
        gemini_adapter.extract_invoice_data(_sample_document())

    assert fake_llm.calls == 3


def test_extract_invoice_data_raises_provider_timeout_on_server_error(monkeypatch):
    server_error = ServerError(503, {"error": {"message": "unavailable"}})
    fake_llm = _FakeStructuredLLM(error=server_error, fail_times=3)
    monkeypatch.setattr(gemini_adapter, "_build_structured_llm", lambda: fake_llm)

    with pytest.raises(ProviderTimeoutError):
        gemini_adapter.extract_invoice_data(_sample_document())


def test_extract_invoice_data_raises_extraction_failed_on_bad_client_error(monkeypatch):
    client_error = ClientError(400, {"error": {"message": "bad request"}})
    fake_llm = _FakeStructuredLLM(error=client_error, fail_times=1)
    monkeypatch.setattr(gemini_adapter, "_build_structured_llm", lambda: fake_llm)

    with pytest.raises(ExtractionFailedError):
        gemini_adapter.extract_invoice_data(_sample_document())

    assert fake_llm.calls == 1


def test_extract_invoice_data_retries_then_succeeds(monkeypatch):
    server_error = ServerError(503, {"error": {"message": "unavailable"}})
    expected = ExtractedInvoice(invoice_number="INV-2")
    fake_llm = _FakeStructuredLLM(result=expected, error=server_error, fail_times=1)
    monkeypatch.setattr(gemini_adapter, "_build_structured_llm", lambda: fake_llm)

    result = gemini_adapter.extract_invoice_data(_sample_document())

    assert result is expected
    assert fake_llm.calls == 2


# --- Errors as langchain-google-genai REALLY raises them ------------------------------
# The library re-raises HTTP errors as its own classes (not ClientError subclasses), so the
# tests above (raw ClientError) are not enough: build the errors through its own wrapper.


def _langchain_error(code: int, message: str = "boom") -> Exception:
    from google.genai.errors import ClientError as RawClientError
    from langchain_google_genai.chat_models import _handle_client_error

    try:
        _handle_client_error(RawClientError(code, {"error": {"message": message}}), {"model": "m"})
    except Exception as wrapped:  # noqa: BLE001 - we want whatever langchain raises
        return wrapped
    raise AssertionError("langchain did not raise")


def test_real_langchain_429_maps_to_rate_limit_and_is_retried(monkeypatch):
    fake_llm = _FakeStructuredLLM(error=_langchain_error(429), fail_times=99)
    monkeypatch.setattr(gemini_adapter, "_build_structured_llm", lambda: fake_llm)

    with pytest.raises(RateLimitError):
        gemini_adapter.extract_invoice_data(_sample_document())

    assert fake_llm.calls == 3  # retried up to _MAX_ATTEMPTS


@pytest.mark.parametrize("code", [401, 403])
def test_real_langchain_auth_errors_map_to_llm_auth_error_and_are_not_retried(monkeypatch, code):
    fake_llm = _FakeStructuredLLM(error=_langchain_error(code), fail_times=99)
    monkeypatch.setattr(gemini_adapter, "_build_structured_llm", lambda: fake_llm)

    with pytest.raises(LLMAuthError):
        gemini_adapter.extract_invoice_data(_sample_document())

    assert fake_llm.calls == 1  # retrying a bad key only burns quota


@pytest.mark.parametrize("code", [400, 404])
def test_real_langchain_other_client_errors_map_to_extraction_failed(monkeypatch, code):
    fake_llm = _FakeStructuredLLM(error=_langchain_error(code), fail_times=99)
    monkeypatch.setattr(gemini_adapter, "_build_structured_llm", lambda: fake_llm)

    with pytest.raises(ExtractionFailedError):
        gemini_adapter.extract_invoice_data(_sample_document())

    assert fake_llm.calls == 1


def test_error_message_does_not_echo_provider_response(monkeypatch):
    """The provider's error body could echo request data: keep it out of our message."""
    secret = "SUPER-SECRET-INVOICE-CONTENT"
    fake_llm = _FakeStructuredLLM(error=_langchain_error(400, secret), fail_times=99)
    monkeypatch.setattr(gemini_adapter, "_build_structured_llm", lambda: fake_llm)

    with pytest.raises(ExtractionFailedError) as excinfo:
        gemini_adapter.extract_invoice_data(_sample_document())

    assert secret not in str(excinfo.value)


def test_missing_api_key_fails_closed_with_clear_error(monkeypatch):
    monkeypatch.setattr(gemini_adapter, "load_dotenv", lambda: None)  # don't read the real .env
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(LLMAuthError, match="GOOGLE_API_KEY is not set"):
        gemini_adapter._build_structured_llm()
