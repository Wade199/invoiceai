from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_invoice_pdf() -> Path:
    """Path to a valid, text-based fake invoice PDF (1 page)."""
    return Path(__file__).parent / "fixtures" / "pdfs" / "sample_invoice.pdf"
