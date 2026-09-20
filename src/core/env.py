from __future__ import annotations

import os

from dotenv import load_dotenv


def load_env() -> None:
    """Load the local, gitignored `.env` without overriding real environment variables.

    Real variables (e.g. secrets injected by a deployment) always win; `.env` only
    fills the gaps. Idempotent and cheap, so callers can invoke it freely.
    """
    load_dotenv()


def get_int_env(name: str, default: int) -> int:
    """Read a positive integer setting from the environment.

    Falls back to `default` on a missing, malformed or non-positive value: a typo in
    a limit must never disable the limit (fail safe, not fail open).
    """
    load_env()
    try:
        value = int(os.getenv(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default
