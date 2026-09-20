from __future__ import annotations

from pathlib import Path

import pytest

from src.core.exceptions import PDFCorruptedError
from src.models.schemas import ExtractedInvoice, InvoiceLineItem
from src.services import pipeline

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))


class _FakeGemini:
    """Replaces extract_invoice_data and counts how often the 'LLM' is called."""

    def __init__(self, invoice: ExtractedInvoice) -> None:
        self.invoice = invoice
        self.calls = 0

    def __call__(self, _document) -> ExtractedInvoice:
        self.calls += 1
        return self.invoice


def _invoice(total_ttc: float) -> ExtractedInvoice:
    return ExtractedInvoice(
        invoice_number="F-001",
        lines=[InvoiceLineItem(description="A", quantity=1, unit_price=100.0, total=100.0)],
        subtotal_ht=100.0,
        tva_rate=0.2,
        total_ttc=total_ttc,
    )


def test_full_pipeline_returns_validated_invoice(
    sample_invoice_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "extract_invoice_data", _FakeGemini(_invoice(120.0)))
    result = pipeline.process_invoice(sample_invoice_pdf)
    assert result.extraction_confidence == "high"


def test_inconsistent_amounts_are_flagged_low(
    sample_invoice_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "extract_invoice_data", _FakeGemini(_invoice(999.0)))
    result = pipeline.process_invoice(sample_invoice_pdf)
    assert result.extraction_confidence == "low"
    assert result.warnings


def test_second_call_hits_cache_and_skips_gemini(
    sample_invoice_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeGemini(_invoice(999.0))
    monkeypatch.setattr(pipeline, "extract_invoice_data", fake)
    first = pipeline.process_invoice(sample_invoice_pdf)
    second = pipeline.process_invoice(sample_invoice_pdf)
    assert fake.calls == 1
    assert second == first  # the cached copy keeps the "low" flag and warnings


def test_ocr_error_propagates_and_nothing_is_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeGemini(_invoice(120.0))
    monkeypatch.setattr(pipeline, "extract_invoice_data", fake)
    corrupted = Path(__file__).parent.parent / "fixtures" / "pdfs" / "corrupted.pdf"
    with pytest.raises(PDFCorruptedError):
        pipeline.process_invoice(corrupted)
    assert fake.calls == 0
    assert not (tmp_path / "cache").exists()
