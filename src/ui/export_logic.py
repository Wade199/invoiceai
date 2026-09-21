from __future__ import annotations

from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from src.ui.models import ExportFile

MAX_EXPORT_IDS = 200  # the API refuses more
READY_KEY = "export_ready"  # session key holding (request, file) once a file is prepared
# Contract with the API: these keys are the API's allowlist of columns (a test compares them
# with the backend so a drift is caught). The labels are what the user sees.
COLUMN_CHOICES: dict[str, str] = {
    "date": "Date",
    "invoice_number": "N° facture",
    "supplier": "Fournisseur",
    "client": "Client",
    "subtotal_ht": "Montant HT",
    "tva_amount": "Montant TVA",
    "tva_rate": "Taux TVA (%)",
    "total_ttc": "Montant TTC",
    "status": "Fiabilité",
    "warnings": "Avertissements",
    "file": "Fichier",
    "processed_at": "Traité le",
}
DEFAULT_COLUMNS = ("date", "invoice_number", "supplier", "subtotal_ht", "tva_amount", "total_ttc")

Kind = Literal["invoices", "lines"]
Locale = Literal["fr", "intl"]
Scope = Literal["selection", "filters"]

KIND_CHOICES: dict[str, Kind] = {
    "Factures (une ligne par facture)": "invoices",
    "Lignes de facturation (une ligne par ligne)": "lines",
}
LOCALE_CHOICES: dict[str, Locale] = {
    "Excel français (séparateur « ; », virgule décimale)": "fr",
    "International (séparateur « , », point décimal)": "intl",
}


@dataclass(frozen=True)
class ExportRequest:
    kind: Kind
    locale: Locale
    columns: tuple[str, ...]
    ids: tuple[str, ...] | None
    date_from: date | None
    date_to: date | None
    status: Literal["high", "low"] | None

    def to_kwargs(self) -> dict[str, Any]:
        """Arguments for `ApiClient.export_csv`. Columns only matter for the invoices file."""
        kwargs: dict[str, Any] = {"kind": self.kind, "locale": self.locale}
        if self.kind == "invoices":
            kwargs["columns"] = list(self.columns)
        if self.ids is not None:
            kwargs["ids"] = list(self.ids)
        else:
            kwargs.update(date_from=self.date_from, date_to=self.date_to, status=self.status)
        return kwargs


def build_request(
    *,
    scope: Scope,
    ids: Sequence[str],
    kind: Kind,
    locale: Locale,
    columns: Sequence[str],
    date_from: date | None,
    date_to: date | None,
    status: Literal["high", "low"] | None,
) -> tuple[ExportRequest | None, list[str]]:
    """Check what the user asked for and build the request, or explain what is wrong."""
    problems: list[str] = []

    if scope == "selection":
        if not ids:
            problems.append("Aucune facture sélectionnée.")
        elif len(ids) > MAX_EXPORT_IDS:
            problems.append(f"{MAX_EXPORT_IDS} factures maximum par export de sélection.")
    elif date_from and date_to and date_from > date_to:
        problems.append("La date de début doit précéder la date de fin.")

    if kind == "invoices":
        if not columns:
            problems.append("Choisissez au moins une colonne.")
        elif any(name not in COLUMN_CHOICES for name in columns):
            problems.append("Colonne d'export inconnue.")

    if problems:
        return None, problems
    return ExportRequest(
        kind=kind,
        locale=locale,
        columns=tuple(columns),
        ids=tuple(dict.fromkeys(ids)) if scope == "selection" else None,
        date_from=None if scope == "selection" else date_from,
        date_to=None if scope == "selection" else date_to,
        status=None if scope == "selection" else status,
    ), []


class _Exporter(Protocol):
    def export_csv(self, **kwargs: Any) -> ExportFile: ...


def prepare_export(client: _Exporter, request: ExportRequest) -> ExportFile:
    return client.export_csv(**request.to_kwargs())


def forget_prepared_file(state: MutableMapping[str, Any]) -> None:
    """Drop the prepared CSV from the session.

    It holds personal data in clear text: it must not stay in the server's memory once the
    user has taken it. Called when the download button is clicked.
    """
    state.pop(READY_KEY, None)
