from __future__ import annotations

from pathlib import Path

import pytest
from google.genai.errors import ClientError, ServerError

from src.core.exceptions import ExtractionFailedError, ProviderTimeoutError, RateLimitError
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
