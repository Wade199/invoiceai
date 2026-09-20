from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path

from pydantic import ValidationError

from src.core.exceptions import StorageError
from src.models.schemas import ExtractedInvoice

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path("data/cache")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_CHUNK_SIZE = 1024 * 1024


def _cache_dir() -> Path:
    # Read at call time (not import time) so tests / deployments can override it.
    return Path(os.getenv("CACHE_DIR", str(_DEFAULT_CACHE_DIR)))


def _entry_path(pdf_hash: str) -> Path:
    # The hash becomes a filename: reject anything but 64 hex chars to rule out
    # path traversal ("../../x") if a caller ever passes user-controlled input.
    if not _SHA256_HEX.fullmatch(pdf_hash):
        raise ValueError(f"Invalid SHA-256 hash: {pdf_hash!r}")
    return _cache_dir() / f"{pdf_hash}.json"


def hash_pdf(pdf_path: Path) -> str:
    """Return the SHA-256 hex digest of a file's binary content.

    Hashing the bytes (not the extracted text) means two identical uploads hit
    the cache even before any OCR work is done.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    digest = hashlib.sha256()
    with pdf_path.open("rb") as file:
        while chunk := file.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def get_cached(pdf_hash: str) -> ExtractedInvoice | None:
    """Return the cached extraction for this hash, or None on a miss.

    A corrupted or outdated entry (invalid JSON, schema changed) is treated as
    a miss and removed: the worst case is one extra Gemini call, never a crash.

    Raises:
        ValueError: If `pdf_hash` is not a valid SHA-256 hex digest.
    """
    path = _entry_path(pdf_hash)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StorageError(f"Cannot read cache entry {path.name}: {exc}") from exc

    try:
        return ExtractedInvoice.model_validate_json(raw)
    except ValidationError:
        logger.warning("Discarding unreadable cache entry %s", path.name)
        path.unlink(missing_ok=True)
        return None


def store_cache(pdf_hash: str, invoice: ExtractedInvoice) -> None:
    """Persist an extraction under its PDF hash (overwrites any existing entry).

    Raises:
        ValueError: If `pdf_hash` is not a valid SHA-256 hex digest.
        StorageError: If the entry cannot be written.
    """
    path = _entry_path(pdf_hash)
    tmp_path = path.with_suffix(".json.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file then rename: a crash mid-write can never leave a
        # half-written JSON that a later get_cached() would read.
        tmp_path.write_text(invoice.model_dump_json(), encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError as exc:
        raise StorageError(f"Cannot write cache entry {path.name}: {exc}") from exc


def delete_cached(pdf_hash: str) -> bool:
    """Delete one cache entry (RGPD: cached data may contain personal data).

    Returns:
        True if an entry was deleted, False if there was none.

    Raises:
        ValueError: If `pdf_hash` is not a valid SHA-256 hex digest.
    """
    path = _entry_path(pdf_hash)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StorageError(f"Cannot delete cache entry {path.name}: {exc}") from exc
    return True
