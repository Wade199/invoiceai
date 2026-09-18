from __future__ import annotations

from pathlib import Path

import pytest

from src.core.exceptions import EmptyDocumentError, PDFCorruptedError, UnsupportedPDFError
from src.ocr.extractor import extract_text_from_pdf

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "pdfs"


def test_extract_text_from_pdf_returns_document_for_valid_pdf(sample_invoice_pdf):
    document = extract_text_from_pdf(sample_invoice_pdf)

    assert document.text.strip() != ""
    assert document.page_count == 1
    assert document.warnings == []
    assert document.source_file == sample_invoice_pdf
    assert "FACTURE" in document.text


def test_extract_text_from_pdf_raises_file_not_found_for_missing_file(tmp_path):
    missing_path = tmp_path / "does_not_exist.pdf"

    with pytest.raises(FileNotFoundError):
        extract_text_from_pdf(missing_path)


def test_extract_text_from_pdf_raises_pdf_corrupted_for_invalid_file():
    corrupted_path = FIXTURES_DIR / "corrupted.pdf"

    with pytest.raises(PDFCorruptedError):
        extract_text_from_pdf(corrupted_path)


def test_extract_text_from_pdf_raises_empty_document_for_blank_pdf():
    empty_path = FIXTURES_DIR / "empty_invoice.pdf"

    with pytest.raises(EmptyDocumentError):
        extract_text_from_pdf(empty_path)


def test_extract_text_from_pdf_raises_unsupported_for_short_text_pdf():
    short_text_path = FIXTURES_DIR / "short_text.pdf"

    with pytest.raises(UnsupportedPDFError):
        extract_text_from_pdf(short_text_path)
