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


class PDFTooLargeError(OCRError):
    """Raised when a PDF exceeds the size / page / text / time limits (DoS protection)."""


class LLMError(InvoiceAIError):
    """Base exception for the LLM module (src/llm)."""


class ExtractionFailedError(LLMError):
    """Raised when the LLM response cannot be parsed into the expected schema."""


class LLMAuthError(LLMError):
    """Raised when the API key is missing, invalid or lacks permission. Never retried."""


class RateLimitError(LLMError):
    """Raised when a Gemini rate limit is exceeded (per-minute limits: retried with backoff)."""


class ProviderTimeoutError(LLMError):
    """Raised when the Gemini API times out or is temporarily unavailable."""


class StorageError(InvoiceAIError):
    """Base exception for persistence (cache, database) failures."""


class DailyQuotaExceededError(RateLimitError):
    """Raised when the Gemini per-day quota is exhausted (free tier: 20 requests/day/model).

    Retrying within seconds cannot help, so this one is never retried.
    """


class APIError(InvoiceAIError):
    """Base exception for the API layer (src/api): uploads, auth, limits, configuration."""


class UploadTooLargeError(APIError):
    """Raised when an uploaded file exceeds MAX_UPLOAD_SIZE_MB."""


class InvalidUploadError(APIError):
    """Raised when an upload is not a non-empty PDF (wrong MIME type or magic bytes)."""


class UploadRateLimitedError(APIError):
    """Raised when a client sends too many uploads in a time window."""

    def __init__(self, message: str, retry_after: int = 60) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ServerBusyError(APIError):
    """Raised when too many extractions are already running."""

    def __init__(self, message: str, retry_after: int = 5) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class APIConfigError(APIError):
    """Raised when the API is misconfigured (e.g. missing or too short API_TOKEN)."""
