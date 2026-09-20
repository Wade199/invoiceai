from __future__ import annotations

import logging
from pathlib import Path

from src.llm.gemini_adapter import extract_invoice_data
from src.models.schemas import ExtractedInvoice
from src.ocr.extractor import extract_text_from_pdf
from src.services.cache import get_cached, hash_pdf, store_cache
from src.services.validate_invoice import validate_invoice

logger = logging.getLogger(__name__)


def process_invoice(pdf_path: Path) -> ExtractedInvoice:
    """Run the full extraction pipeline on one PDF: cache -> OCR -> LLM -> validation.

    The *validated* result is cached, so a cache hit skips OCR, Gemini and
    validation. Errors are deliberately not caught here: they propagate as
    InvoiceAIError subclasses and the caller (API/UI) translates them.

    Args:
        pdf_path: Path to the invoice PDF.

    Returns:
        The extracted invoice, with `extraction_confidence="low"` and warnings
        if the amounts are inconsistent.

    Raises:
        FileNotFoundError: If `pdf_path` does not exist.
        OCRError: If the PDF is corrupted, empty or a scanned image.
        LLMError: If the Gemini call fails (rate limit, timeout, bad response).
        StorageError: If the cache cannot be read or written.
    """
    pdf_hash = hash_pdf(pdf_path)

    cached = get_cached(pdf_hash)
    if cached is not None:
        logger.info("Cache hit for %s", pdf_path.name)
        return cached

    document = extract_text_from_pdf(pdf_path)
    invoice = validate_invoice(extract_invoice_data(document))
    store_cache(pdf_hash, invoice)
    return invoice
