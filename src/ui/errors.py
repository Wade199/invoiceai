from __future__ import annotations


class UiError(Exception):
    """Base of the errors the interface knows how to show. `str(error)` is safe to display."""


class UiConfigError(UiError):
    """The interface is misconfigured (missing token, unsafe API address)."""


class ApiUnavailableError(UiError):
    """The API cannot be reached (not started, wrong port, timeout)."""


class ApiError(UiError):
    """The API answered with an error. The message is the API's own fixed text (or ours)."""

    def __init__(self, status: int, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
