from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from src.ui.config import UiSettings, load_settings, validate_api_url
from src.ui.errors import ApiError, ApiUnavailableError
from src.ui.models import ExportFile, InvoiceView, SummaryView

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_SAFE_CSV_NAME = re.compile(r'filename="([A-Za-z0-9_.-]{1,80}\.csv)"')
_DEFAULT_EXPORT_NAME = "export.csv"
_QUICK_TIMEOUT = 30.0
# An extraction takes 7 to 33 s on the free tier, plus the API's own retries.
_UPLOAD_TIMEOUT = 180.0
_MAX_MESSAGE = 300

_UNAUTHORIZED = (
    "Accès refusé par l'API : vérifiez API_TOKEN (même valeur dans l'API et l'interface)."
)
_GENERIC = "L'API a renvoyé une erreur inattendue."


class ApiClient:
    """Talks to the InvoiceAI API. Everything it raises is a `UiError` safe to display.

    It never surfaces a raw response body, a stack trace or the token: an error message is
    either the API's own fixed text (`detail`, truncated) or one of ours.
    """

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    @classmethod
    def from_settings(cls, settings: UiSettings | None = None) -> ApiClient:
        """Build a client with the safeguards for a bearer token.

        No redirect is followed (it could carry the token to another host) and proxy
        variables from the environment are ignored (they could route the token through one).
        """
        settings = settings or load_settings()
        return cls(
            httpx.Client(
                base_url=validate_api_url(settings.api_url),
                headers={"Authorization": f"Bearer {settings.api_token}"},
                timeout=_QUICK_TIMEOUT,
                follow_redirects=False,
                trust_env=False,
            )
        )

    # --- transport ------------------------------------------------------------------------
    def _request(self, method: str, path: str, *, timeout: float | None = None, **kwargs: Any):
        if timeout is not None:  # otherwise the client's own default applies
            kwargs["timeout"] = timeout
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ApiUnavailableError("L'API ne répond pas (délai dépassé).") from exc
        except httpx.HTTPError as exc:
            raise ApiUnavailableError(
                "API injoignable : lancez-la avec `make api` (par défaut 127.0.0.1:8000)."
            ) from exc
        if response.status_code >= 400:
            raise _error_from(response)
        return response

    @staticmethod
    def _parse(model: type, payload: Any):
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise ApiError(502, "Réponse inattendue de l'API.") from exc

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(502, "Réponse inattendue de l'API.") from exc

    # --- endpoints ------------------------------------------------------------------------
    def check(self) -> None:
        """Raise `ApiUnavailableError` if the API does not answer `/health`."""
        response = self._request("GET", "/health")
        if self._json(response).get("status") != "ok":
            raise ApiUnavailableError("L'API répond, mais son état n'est pas « ok ».")

    def upload(self, filename: str, data: bytes, mime: str = "application/pdf") -> InvoiceView:
        """Send one file (PDF, JPEG or PNG): extraction takes several seconds. The API deletes
        it afterwards."""
        response = self._request(
            "POST",
            "/invoices",
            timeout=_UPLOAD_TIMEOUT,
            files={"file": (filename, data, mime)},
        )
        return self._parse(InvoiceView, self._json(response))

    def list_invoices(
        self,
        *,
        query: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        status: Literal["high", "low"] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SummaryView]:
        params = _clean(
            q=query or None,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
            status=status,
            limit=limit,
            offset=offset,
        )
        payload = self._json(self._request("GET", "/invoices", params=params))
        if not isinstance(payload, list):
            raise ApiError(502, "Réponse inattendue de l'API.")
        return [self._parse(SummaryView, item) for item in payload]

    def get(self, record_id: str) -> InvoiceView:
        response = self._request("GET", f"/invoices/{_checked(record_id)}")
        return self._parse(InvoiceView, self._json(response))

    def update(self, record_id: str, data: dict[str, Any]) -> InvoiceView:
        response = self._request("PUT", f"/invoices/{_checked(record_id)}", json=data)
        return self._parse(InvoiceView, self._json(response))

    def delete(self, record_id: str) -> None:
        self._request("DELETE", f"/invoices/{_checked(record_id)}")

    def export_csv(
        self,
        *,
        ids: Sequence[str] | None = None,
        kind: Literal["invoices", "lines"] = "invoices",
        columns: Sequence[str] | None = None,
        locale: Literal["fr", "intl"] = "fr",
        query: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        status: Literal["high", "low"] | None = None,
    ) -> ExportFile:
        params: dict[str, Any] = _clean(
            ids=[_checked(record_id) for record_id in ids] if ids else None,
            columns=list(columns) if columns else None,
            kind=kind,
            locale=locale,
            q=query or None,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
            status=status,
        )
        response = self._request("GET", "/invoices/export.csv", params=params)
        match = _SAFE_CSV_NAME.search(response.headers.get("content-disposition", ""))
        return ExportFile(
            filename=match.group(1) if match else _DEFAULT_EXPORT_NAME, content=response.content
        )


def _checked(record_id: str) -> str:
    """An id only ever comes from the API; still, it must not be able to alter the URL path."""
    if not _UUID.fullmatch(record_id):
        raise ValueError("invalid invoice id")
    return record_id


def _clean(**params: Any) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None}


def _error_from(response: httpx.Response) -> ApiError:
    status = response.status_code
    retry_after: int | None = None
    try:
        retry_after = int(response.headers["retry-after"])
    except (KeyError, ValueError):
        pass
    if status == 401:
        return ApiError(status, _UNAUTHORIZED)
    message = _GENERIC
    try:
        detail = response.json().get("detail")
        if isinstance(detail, str) and detail.strip():
            message = detail.strip()[:_MAX_MESSAGE]
    except (ValueError, AttributeError):
        pass  # not JSON (proxy page, HTML): keep the generic text, never show the body
    return ApiError(status, message, retry_after)
