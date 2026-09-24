"""End-to-end pipeline tests against the REAL Gemini API, using the 5 fake invoices.

Deselected by default; run with `pytest -m slow`. Unlike test_gemini_real.py (which calls
the LLM adapter directly on synthetic text), this exercises the full chain `process_invoice`
is responsible for: hash -> cache -> real OCR on a real PDF -> Gemini -> validation -> cache
write. `data/fake_invoices/` is not committed; generate it first with
`python scripts/generate_fake_invoices.py`.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values

from src.services.pipeline import process_invoice

pytestmark = pytest.mark.slow

_FAKE_INVOICES_DIR = Path(__file__).resolve().parents[2] / "data" / "fake_invoices"
_FAKE_INVOICES = sorted(_FAKE_INVOICES_DIR.glob("*.pdf")) if _FAKE_INVOICES_DIR.is_dir() else []
_NO_FIXTURES_REASON = "data/fake_invoices/ is empty — run scripts/generate_fake_invoices.py first"


@pytest.fixture(autouse=True)
def _real_key(monkeypatch: pytest.MonkeyPatch) -> None:
    key = dotenv_values(".env").get("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        pytest.skip("GOOGLE_API_KEY not available")
    monkeypatch.setenv("GOOGLE_API_KEY", key)


@pytest.mark.parametrize(
    "pdf_path", _FAKE_INVOICES or [None], ids=lambda p: p.name if p else "none"
)
def test_process_invoice_extracts_a_plausible_invoice(pdf_path: Path | None) -> None:
    if pdf_path is None:
        pytest.skip(_NO_FIXTURES_REASON)
    invoice = process_invoice(pdf_path)
    assert invoice.invoice_number
    assert invoice.supplier
    assert invoice.total_ttc is not None and invoice.total_ttc > 0
    assert invoice.lines, "expected at least one line item"


def test_process_invoice_uses_the_cache_on_a_second_call() -> None:
    """A 2nd call on the same file must hit the cache: near-instant, no 2nd Gemini request."""
    if not _FAKE_INVOICES:
        pytest.skip(_NO_FIXTURES_REASON)
    pdf_path = _FAKE_INVOICES[0]
    first = process_invoice(pdf_path)
    start = time.monotonic()
    second = process_invoice(pdf_path)
    elapsed = time.monotonic() - start
    assert second == first
    assert elapsed < 1.0, f"expected a cache hit (<1s), took {elapsed:.2f}s — is caching broken?"
