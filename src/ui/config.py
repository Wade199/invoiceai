from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from src.ui.errors import UiConfigError

DEFAULT_API_URL = "http://127.0.0.1:8000"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_MIN_TOKEN_LENGTH = 32
# The ONLY variables the interface reads. Never load the whole .env into os.environ:
# it also holds CACHE_ENCRYPTION_KEY and GOOGLE_API_KEY, which this process must not carry.
_WANTED = ("API_URL", "API_TOKEN")


@dataclass(frozen=True)
class UiSettings:
    api_url: str
    api_token: str = ""

    def __repr__(self) -> str:  # the token must never end up in a log or a traceback
        return f"UiSettings(api_url={self.api_url!r}, api_token=<hidden>)"


def validate_api_url(url: str) -> str:
    """Refuse an API address that would send the bearer token where it should not go.

    `http` is only accepted towards the local machine; anything else must be `https`. The
    host is extracted with a real URL parser: `http://127.0.0.1@evil.example` has the host
    `evil.example`, not `127.0.0.1`.

    Raises:
        UiConfigError: If the address is unsafe or malformed.
    """
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError as exc:
        raise UiConfigError("API_URL is not a valid address") from exc
    if parts.scheme not in ("http", "https") or not host:
        raise UiConfigError("API_URL must be an http(s) address with a host")
    if parts.username is not None or parts.password is not None:
        raise UiConfigError("API_URL must not contain credentials")
    if parts.scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise UiConfigError(
            "API_URL uses plain http towards a remote host: the token would travel in clear text"
        )
    return url.rstrip("/")


def _read_file_values(root: Path) -> dict[str, str]:
    # .env.ui (only the interface's secrets) wins over .env when both exist.
    for name in (".env.ui", ".env"):
        candidate = root / name
        if candidate.is_file():
            values = dotenv_values(candidate)
            return {key: values[key] for key in _WANTED if values.get(key)}
    return {}


def load_settings(root: Path | None = None) -> UiSettings:
    """Read the interface settings: real environment first, then `.env.ui` / `.env`.

    Raises:
        UiConfigError: If the token is missing or weak, or the address is unsafe.
    """
    values = {**_read_file_values(root or Path.cwd())}
    for key in _WANTED:
        if os.getenv(key):
            values[key] = os.environ[key]
    token = values.get("API_TOKEN", "")
    if len(token) < _MIN_TOKEN_LENGTH:
        raise UiConfigError(
            f"API_TOKEN is missing or shorter than {_MIN_TOKEN_LENGTH} characters "
            "(python scripts/generate_api_token.py, then put it in .env)"
        )
    return UiSettings(
        api_url=validate_api_url(values.get("API_URL", DEFAULT_API_URL)), api_token=token
    )
