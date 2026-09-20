from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from src.core.exceptions import EmptyDocumentError, PDFCorruptedError, UnsupportedPDFError

logger = logging.getLogger(__name__)

_SCANNED_PDF_CHAR_THRESHOLD = 100
_MANY_PAGES_THRESHOLD = 10
_PAGE_SEPARATOR = "\n\n---PAGE {page_number}---\n\n"


@dataclass(frozen=True)
class ExtractedDocument:
    """Result of an OCR extraction on a PDF.

    Attributes:
        text: Concatenated text of all pages, separated by
            "\n\n---PAGE {n}---\n\n" between each page.
        page_count: Total number of pages in the PDF.
        source_file: Absolute path of the source PDF (traceability).
        warnings: Non-blocking messages (e.g. "page 2 sans texte extractible",
            "PDF long (12 pages), extraction complète mais performance dégradée").
        metadata: Raw PDF metadata (author, creation date, producer...).
    """

    text: str
    page_count: int
    source_file: Path
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


def extract_text_from_pdf(pdf_path: Path) -> ExtractedDocument:
    """Extract text content from a PDF invoice/quote file.

    Args:
        pdf_path: Absolute path to the PDF file to process.

    Returns:
        ExtractedDocument containing text, page count, warnings, and metadata.

    Raises:
        FileNotFoundError: If pdf_path does not exist (Python native, not wrapped).
        PDFCorruptedError: If the file cannot be opened as a valid PDF
            (includes encrypted PDFs in V1).
        EmptyDocumentError: If the PDF is valid but contains zero extractable text.
        UnsupportedPDFError: If the PDF appears to be a scanned image (no text layer).
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    logger.info("Starting OCR extraction: %r", pdf_path)

    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_texts = [_clean_page_text(page.extract_text() or "") for page in pdf.pages]
            page_count = len(pdf.pages)
            raw_metadata = pdf.metadata or {}
    except Exception as exc:
        raise PDFCorruptedError(f"Cannot open PDF: {pdf_path}") from exc

    warnings = _collect_warnings(page_texts, page_count)
    full_text = _join_pages(page_texts)

    if not full_text.strip():
        raise EmptyDocumentError(f"No extractable text in PDF: {pdf_path}")

    if len(full_text.strip()) < _SCANNED_PDF_CHAR_THRESHOLD:
        raise UnsupportedPDFError(f"PDF appears to be a scanned image: {pdf_path}")

    logger.info(
        "Finished OCR extraction: %r (%d pages, %d chars)", pdf_path, page_count, len(full_text)
    )

    return ExtractedDocument(
        text=full_text,
        page_count=page_count,
        source_file=pdf_path,
        warnings=warnings,
        metadata={str(key): str(value) for key, value in raw_metadata.items()},
    )


def _clean_page_text(text: str) -> str:
    """Collapse whitespace runs and strip a single page's extracted text."""
    return re.sub(r"\s+", " ", text).strip()


def _collect_warnings(page_texts: list[str], page_count: int) -> list[str]:
    """Build the list of non-blocking warnings for an extraction."""
    warnings: list[str] = []

    for page_number, page_text in enumerate(page_texts, start=1):
        if not page_text:
            warnings.append(f"page {page_number} sans texte extractible")

    if page_count > _MANY_PAGES_THRESHOLD:
        warnings.append(
            f"PDF long ({page_count} pages), extraction complète mais performance dégradée"
        )

    for warning in warnings:
        logger.warning("%s", warning)

    return warnings


def _join_pages(page_texts: list[str]) -> str:
    """Concatenate page texts with the "---PAGE {n}---" separator."""
    parts: list[str] = []
    for page_number, text in enumerate(page_texts, start=1):
        if page_number == 1:
            parts.append(text)
        else:
            parts.append(_PAGE_SEPARATOR.format(page_number=page_number) + text)
    return "".join(parts)
