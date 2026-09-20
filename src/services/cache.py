from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError

from src.core.env import get_int_env, load_env
from src.core.exceptions import StorageError
from src.models.schemas import ExtractedInvoice

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path("data/cache")
_DEFAULT_TTL_DAYS = 30  # GDPR retention, same default as DEFAULT_RETENTION_DAYS in the brief
_SECONDS_PER_DAY = 86_400
_STALE_TMP_SECONDS = 3_600
_ENTRY_SUFFIX = ".enc"
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_CHUNK_SIZE = 1024 * 1024
_REPLACE_ATTEMPTS = 5


def _cache_dir() -> Path:
    # Read at call time (not import time) so tests / deployments can override it.
    return Path(os.getenv("CACHE_DIR", str(_DEFAULT_CACHE_DIR)))


def _fernet() -> Fernet:
    """Build the cipher from CACHE_ENCRYPTION_KEY.

    Fernet = AES-128-CBC + HMAC-SHA256: entries are both confidential AND tamper-proof,
    and carry an authenticated timestamp used for the retention limit.
    Fails closed: without a key we refuse to write personal data in clear text.
    """
    load_env()
    key = os.getenv("CACHE_ENCRYPTION_KEY")
    if not key:
        raise StorageError(
            "CACHE_ENCRYPTION_KEY is not set (generate one with scripts/generate_cache_key.py)"
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise StorageError("CACHE_ENCRYPTION_KEY is not a valid Fernet key") from exc


def _ttl_seconds() -> int:
    return get_int_env("CACHE_TTL_DAYS", _DEFAULT_TTL_DAYS) * _SECONDS_PER_DAY


def _entry_path(pdf_hash: str) -> Path:
    # The hash becomes a filename: reject anything but 64 hex chars to rule out
    # path traversal ("../../x") if a caller ever passes user-controlled input.
    if not _SHA256_HEX.fullmatch(pdf_hash):
        raise ValueError(f"Invalid SHA-256 hash: {pdf_hash!r}")
    return _cache_dir() / f"{pdf_hash}{_ENTRY_SUFFIX}"


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


def _decode_entry(cipher: Fernet, token: bytes, expected_hash: str) -> ExtractedInvoice | None:
    """Decrypt and validate one entry; None if tampered, expired, swapped or obsolete."""
    try:
        plaintext = cipher.decrypt(token)  # verifies the HMAC: any modification fails here
    except InvalidToken:
        logger.warning(
            "Cache entry %s failed authentication (tampered or wrong key)", expected_hash
        )
        return None

    # The timestamp is inside the authenticated token, so the retention limit cannot be
    # extended by touching the file.
    if time.time() - cipher.extract_timestamp(token) > _ttl_seconds():
        logger.info("Cache entry %s expired", expected_hash)
        return None

    try:
        payload = json.loads(plaintext)
        # An attacker who can write files could copy a valid entry onto another hash's
        # file name: authenticated, but the wrong invoice. The hash is inside the payload.
        if payload["hash"] != expected_hash:
            logger.warning("Cache entry %s holds another document's data", expected_hash)
            return None
        return ExtractedInvoice.model_validate(payload["invoice"])
    except (ValueError, KeyError, TypeError, ValidationError):
        logger.warning("Cache entry %s is unreadable or obsolete", expected_hash)
        return None


def get_cached(pdf_hash: str) -> ExtractedInvoice | None:
    """Return the cached extraction for this hash, or None on a miss.

    A tampered, expired, mismatched or obsolete entry is treated as a miss and deleted:
    the worst case is one extra Gemini call, never a crash and never forged data.

    Raises:
        ValueError: If `pdf_hash` is not a valid SHA-256 hex digest.
        StorageError: If the key is missing/invalid or the entry cannot be read.
    """
    path = _entry_path(pdf_hash)
    cipher = _fernet()
    try:
        token = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StorageError(f"Cannot read cache entry {path.name}: {exc}") from exc

    invoice = _decode_entry(cipher, token, pdf_hash)
    if invoice is None:
        path.unlink(missing_ok=True)
    return invoice


def _replace_with_retry(source: str, destination: Path) -> None:
    """`os.replace` with a short retry: on Windows it raises PermissionError when another
    thread is replacing/reading the same file at that very instant. Entries are
    content-addressed (same hash = same PDF), so retrying a few ms later is safe."""
    for attempt in range(1, _REPLACE_ATTEMPTS + 1):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS:
                raise
            time.sleep(0.01 * attempt)


def store_cache(pdf_hash: str, invoice: ExtractedInvoice) -> None:
    """Persist an extraction, encrypted, under its PDF hash (overwrites any existing entry).

    Raises:
        ValueError: If `pdf_hash` is not a valid SHA-256 hex digest.
        StorageError: If the key is missing/invalid or the entry cannot be written.
    """
    path = _entry_path(pdf_hash)
    cipher = _fernet()
    payload = json.dumps({"hash": pdf_hash, "invoice": invoice.model_dump(mode="json")})
    token = cipher.encrypt(payload.encode("utf-8"))

    tmp_name: str | None = None
    try:
        # 0o700 / 0o600 on POSIX (ignored on Windows, where the user-profile ACL and the
        # encryption are what protect the file).
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Write to a *unique* temp file then rename: a crash mid-write can never leave a
        # half-written entry, and two concurrent stores of the same hash (Streamlit
        # threads) cannot clobber each other's temp file.
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as tmp:
            tmp_name = tmp.name
            tmp.write(token)
        _replace_with_retry(tmp_name, path)
    except OSError as exc:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
        raise StorageError(f"Cannot write cache entry {path.name}: {exc}") from exc


def delete_cached(pdf_hash: str) -> bool:
    """Delete one cache entry (GDPR erasure: entries contain personal data).

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


def purge_expired() -> int:
    """Delete every expired or invalid entry (GDPR retention). To run at startup / daily.

    Also removes leftovers that must not stay on disk: plaintext `.json` entries written
    by the pre-encryption version, and stale temporary files.

    Returns:
        Number of files deleted.

    Raises:
        StorageError: If the encryption key is missing or invalid.
    """
    directory = _cache_dir()
    if not directory.is_dir():
        return 0
    cipher = _fernet()
    deleted = 0
    for entry in directory.iterdir():
        try:
            if entry.suffix == ".json":  # legacy plaintext entry
                stale = True
            elif entry.suffix == ".tmp":
                stale = time.time() - entry.stat().st_mtime > _STALE_TMP_SECONDS
            elif entry.suffix == _ENTRY_SUFFIX:
                stale = _decode_entry(cipher, entry.read_bytes(), entry.stem) is None
            else:
                continue
            if stale:
                entry.unlink(missing_ok=True)
                deleted += 1
        except OSError as exc:
            logger.warning("Cannot purge %s: %s", entry.name, exc)
    return deleted
