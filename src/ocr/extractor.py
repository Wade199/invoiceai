from __future__ import annotations

import json
import logging
import os
import re

# The parser runs as a separate command (see _run_isolated), never through a shell.
import subprocess  # nosec B404
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

from src.core.env import SECRET_ENV_KEYS, get_int_env
from src.core.exceptions import (
    EmptyDocumentError,
    PDFCorruptedError,
    PDFTooLargeError,
    UnsupportedPDFError,
)

logger = logging.getLogger(__name__)

_SCANNED_PDF_CHAR_THRESHOLD = 100
_MANY_PAGES_THRESHOLD = 10

# DoS limits (overridable through the environment, see .env.example). A malformed or
# hostile PDF must not be able to exhaust CPU / memory or burn the Gemini quota.
_DEFAULT_MAX_MB = 10
_DEFAULT_MAX_PAGES = 30
_DEFAULT_MAX_TEXT_CHARS = 100_000
_DEFAULT_MAX_SECONDS = 20
_PDF_MAGIC = b"%PDF-"
_MAGIC_SEARCH_WINDOW = 1024  # the PDF spec allows a few junk bytes before the header
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WORKER_MODULE = "src.ocr.worker"
_MAX_WORKER_OUTPUT = 5 * 1024 * 1024  # the worker's answer is already bounded: belt and braces
_MAX_METADATA_ENTRIES = 100
_MAX_METADATA_VALUE = 1000
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
        PDFTooLargeError: If the file is too big, has too many pages / too much text,
            or parsing exceeds the time limit (DoS protection, see MAX_PDF_* settings).
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    _check_file(pdf_path)

    logger.info("Starting OCR extraction: %r", pdf_path)

    # The parsing runs in a separate process: pdfplumber has no timeout, and a hostile PDF
    # can hang or crash the parser. Killing a process is the only reliable way to stop it.
    outcome = _run_isolated(
        _WORKER_MODULE,
        [
            str(pdf_path),
            str(get_int_env("MAX_PDF_PAGES", _DEFAULT_MAX_PAGES)),
            str(get_int_env("MAX_PDF_TEXT_CHARS", _DEFAULT_MAX_TEXT_CHARS)),
        ],
        timeout=get_int_env("MAX_PDF_SECONDS", _DEFAULT_MAX_SECONDS),
    )
    status = outcome[0]
    if status == "too_large":
        raise PDFTooLargeError(f"PDF exceeds a limit ({outcome[1]}): {pdf_path}")
    if status != "ok":
        raise PDFCorruptedError(f"Cannot open PDF: {pdf_path}")
    _, page_texts, page_count, raw_metadata = outcome

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
        metadata=raw_metadata,
    )


def _check_file(pdf_path: Path) -> None:
    """Cheap pre-checks (no parsing): size limit and PDF magic bytes."""
    max_bytes = get_int_env("MAX_UPLOAD_SIZE_MB", _DEFAULT_MAX_MB) * 1024 * 1024
    if pdf_path.stat().st_size > max_bytes:
        raise PDFTooLargeError(f"PDF larger than {max_bytes // (1024 * 1024)} MB: {pdf_path}")
    with pdf_path.open("rb") as file:
        header = file.read(_MAGIC_SEARCH_WINDOW)
    if _PDF_MAGIC not in header:
        raise PDFCorruptedError(f"Not a PDF file (missing %PDF- header): {pdf_path}")


def _read_pdf(path: str, max_pages: int, max_chars: int) -> tuple[Any, ...]:
    """Parse the PDF and return plain picklable data. Runs in the child process.

    Returns:
        ("ok", page_texts, page_count, metadata) | ("too_large", reason) | ("corrupted",).
    """
    try:
        with pdfplumber.open(path) as pdf:
            page_count = len(pdf.pages)
            if page_count > max_pages:
                return ("too_large", f"{page_count} pages > {max_pages}")
            page_texts: list[str] = []
            total_chars = 0
            for page in pdf.pages:
                text = _clean_page_text(page.extract_text() or "")
                total_chars += len(text)
                if total_chars > max_chars:  # stop early: do not parse the remaining pages
                    return ("too_large", f"more than {max_chars} characters")
                page_texts.append(text)
            metadata = {
                str(key)[:_MAX_METADATA_VALUE]: str(value)[:_MAX_METADATA_VALUE]
                for key, value in list((pdf.metadata or {}).items())[:_MAX_METADATA_ENTRIES]
            }
    except Exception:  # noqa: BLE001 - any parser failure means "not a usable PDF"
        return ("corrupted",)
    return ("ok", page_texts, page_count, metadata)


def _child_env() -> dict[str, str]:
    """The environment of the parser: everything except the secrets it has no use for."""
    child = {key: value for key, value in os.environ.items() if key not in SECRET_ENV_KEYS}
    child["PYTHONIOENCODING"] = "utf-8"
    return child


def _run_isolated(module: str, args: Sequence[str], timeout: float) -> tuple[Any, ...]:
    """Run `python -m <module> <args>` as a separate process, kill it after `timeout` seconds.

    A plain command, not `multiprocessing`: `multiprocessing` re-imports the parent's
    `__main__` in the child, which breaks (or re-runs the wrong script) whenever the parent is
    not an ordinary script, e.g. under Streamlit, a test runner or a notebook. The worker
    prints its answer as JSON on stdout.

    Raises:
        PDFTooLargeError: If the worker did not answer in time (it is killed).
        PDFCorruptedError: If it crashed or answered nonsense.
    """
    command = [sys.executable, "-m", module, *args]
    try:
        # The argument list is built from constants, integers and the file path (an argument,
        # never a shell string): nothing user-controlled is interpreted.
        completed = subprocess.run(  # nosec B603
            command,
            cwd=_PROJECT_ROOT,
            env=_child_env(),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:  # `run` has already killed the worker
        raise PDFTooLargeError(f"PDF parsing exceeded {timeout} s and was aborted") from exc
    if completed.returncode != 0:
        raise PDFCorruptedError("PDF parser crashed")
    if len(completed.stdout) > _MAX_WORKER_OUTPUT:
        raise PDFCorruptedError("PDF parser answered with too much data")
    try:
        answer = json.loads(completed.stdout)
    except ValueError as exc:
        raise PDFCorruptedError("PDF parser gave no valid answer") from exc
    if not isinstance(answer, list) or not answer:
        raise PDFCorruptedError("PDF parser gave no valid answer")
    return tuple(answer)


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
