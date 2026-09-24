from __future__ import annotations

import logging
from pathlib import Path

from src.core.exceptions import StorageError
from src.llm.gemini_adapter import extract_invoice_data, extract_invoice_data_from_image
from src.models.schemas import ExtractedInvoice
from src.ocr.extractor import extract_text_from_pdf
from src.services.cache import get_cached, hash_pdf, store_cache
from src.services.validate_invoice import validate_invoice

logger = logging.getLogger(__name__)

_IMAGE_MIMES = {"image/jpeg", "image/png"}


def process_invoice(file_path: Path, mime: str = "application/pdf") -> ExtractedInvoice:
    """Run the full extraction pipeline: cache -> OCR or Gemini image -> LLM -> validation.

    A PDF goes through local text extraction first (`extract_text_from_pdf`), then Gemini
    gets the text. A photo/scan (`image/jpeg`, `image/png`) has no embedded text: the file
    goes to Gemini directly (`extract_invoice_data_from_image`) — which also means IBAN/
    e-mail/phone masking (`prepare_text_for_llm`, PDF path only) does not apply to it; see
    that function's docstring.

    The *validated* result is cached, so a cache hit skips OCR/Gemini and validation. Errors
    are deliberately not caught here: they propagate as InvoiceAIError subclasses and the
    caller (API/UI) translates them.

    Args:
        file_path: Path to the uploaded invoice file.
        mime: Its validated content type (`src.api.upload._ALLOWED_TYPES`). Defaults to
            `"application/pdf"` for backward compatibility with existing callers/tests.

    Returns:
        The extracted invoice, with `extraction_confidence="low"` and warnings
        if the amounts are inconsistent.

    Raises:
        FileNotFoundError: If `file_path` does not exist.
        OCRError: If the PDF is corrupted, empty or a scanned image (PDF path only).
        LLMError: If the Gemini call fails (rate limit, timeout, bad response).
        StorageError: If the cache cannot be read (or its key is missing / invalid).
            A failure to WRITE the cache is logged and ignored.
    """
    file_hash = hash_pdf(file_path)

    cached = get_cached(file_hash)
    if cached is not None:
        logger.info("Cache hit for %r", file_path.name)
        return cached

    if mime in _IMAGE_MIMES:
        extracted = extract_invoice_data_from_image(file_path.read_bytes(), mime, file_path)
    else:
        extracted = extract_invoice_data(extract_text_from_pdf(file_path))
    invoice = validate_invoice(extracted)
    try:
        store_cache(file_hash, invoice)
    except StorageError:
        # The cache is an optimisation: a disk problem must not throw away an answer the LLM
        # just gave (each call costs quota). A missing / invalid key never gets here: it
        # already failed, before the LLM call, in get_cached().
        logger.warning("Extraction of %r could not be cached", file_path.name)
    return invoice
