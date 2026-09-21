from __future__ import annotations

import os

from cryptography.fernet import Fernet

from src.core.env import load_env
from src.core.exceptions import StorageError

_KEY_ENV = "CACHE_ENCRYPTION_KEY"


def get_cipher() -> Fernet:
    """Build the cipher used for everything stored at rest (cache entries, invoice records).

    Fernet = AES-128-CBC + HMAC-SHA256: data is both confidential AND tamper-proof, and each
    token carries an authenticated timestamp. One key serves the cache and the database: they
    share the same trust boundary (the same machine and the same `.env`).

    Fails closed: without a valid key we refuse to write personal data in clear text.

    Raises:
        StorageError: If CACHE_ENCRYPTION_KEY is missing or not a valid Fernet key.
    """
    load_env()
    key = os.getenv(_KEY_ENV)
    if not key:
        raise StorageError(
            f"{_KEY_ENV} is not set (generate one with scripts/generate_cache_key.py)"
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise StorageError(f"{_KEY_ENV} is not a valid Fernet key") from exc
