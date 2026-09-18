from __future__ import annotations


class InvoiceAIError(Exception):
    """Base exception for all InvoiceAI errors."""


class OCRError(InvoiceAIError):
    """Base exception for the OCR module (src/ocr)."""


class PDFCorruptedError(OCRError):
    """Raised when a PDF file cannot be opened or parsed (includes encrypted PDFs in V1)."""


class EmptyDocumentError(OCRError):
    """Raised when a valid PDF contains zero extractable text on any page."""


class UnsupportedPDFError(OCRError):
    """Raised when a PDF appears to be a scanned image with no text layer."""
