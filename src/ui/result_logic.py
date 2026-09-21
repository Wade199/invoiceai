from __future__ import annotations

import math
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from src.ui.errors import UiError
from src.ui.models import InvoiceView

CURRENT_RECORD_KEY = "current_record_id"  # session key: which invoice the Result page shows
FLASH_KEY = "result_flash"  # one-shot message shown at the top of the next render

# Same bounds as the API (src/models/schemas.py). The server stays the judge: these checks
# only exist to give clear messages BEFORE sending, instead of a bare "Requête invalide".
MAX_LINES = 200
_MAX_AMOUNT = 1_000_000_000.0
_MAX_LENGTHS = {"invoice_number": 100, "supplier": 200, "client": 200}
_MAX_DESCRIPTION = 500
_MAX_DATE_TEXT = 100


@dataclass(frozen=True)
class LineValues:
    description: str
    quantity: float
    unit_price: float
    total: float


@dataclass(frozen=True)
class FormValues:
    """What the form holds. The VAT rate is a percentage here (20), a fraction on the wire (0.2)."""

    invoice_number: str = ""
    date: str = ""
    supplier: str = ""
    client: str = ""
    subtotal_ht: float | None = None
    tva_percent: float | None = None
    total_ttc: float | None = None
    lines: list[LineValues] = field(default_factory=list)


def to_percent(rate: float | None) -> float | None:
    """0.2 and 20 both mean 20 %: the extraction may return either (validate_invoice flags 20)."""
    if rate is None:
        return None
    return round(rate * 100 if rate <= 1 else rate, 4)


def form_from_view(view: InvoiceView) -> FormValues:
    invoice = view.invoice
    return FormValues(
        invoice_number=invoice.invoice_number or "",
        date=invoice.date or "",
        supplier=invoice.supplier or "",
        client=invoice.client or "",
        subtotal_ht=invoice.subtotal_ht,
        tva_percent=to_percent(invoice.tva_rate),
        total_ttc=invoice.total_ttc,
        lines=[
            LineValues(line.description, line.quantity, line.unit_price, line.total)
            for line in invoice.lines
        ],
    )


def _bad_number(value: float | None) -> bool:
    return value is not None and (not math.isfinite(value) or abs(value) > _MAX_AMOUNT)


def validate_and_build(values: FormValues) -> tuple[dict[str, Any] | None, list[str]]:
    """Check the form and build the body of `PUT /invoices/{id}`.

    Returns:
        (payload, []) when valid, or (None, messages in French) when not. Only the fields a
        user may change are ever in the payload (the API refuses anything else).
    """
    errors: list[str] = []

    for name, limit in _MAX_LENGTHS.items():
        if len(getattr(values, name).strip()) > limit:
            errors.append(f"« {_LABELS[name]} » est trop long ({limit} caractères maximum).")

    date_text = values.date.strip()
    if len(date_text) > _MAX_DATE_TEXT:
        errors.append("« Date » est trop longue.")
    elif date_text:
        try:
            date.fromisoformat(date_text)
        except ValueError:
            errors.append("« Date » : format attendu AAAA-MM-JJ (exemple : 2026-09-10).")

    for label, amount in (
        ("Montant HT", values.subtotal_ht),
        ("Montant TTC", values.total_ttc),
    ):
        if _bad_number(amount):
            errors.append(f"« {label} » est hors limites.")
    if values.tva_percent is not None and (
        not math.isfinite(values.tva_percent) or not 0 <= values.tva_percent <= 100
    ):
        errors.append("« Taux de TVA » doit être compris entre 0 et 100 %.")

    if len(values.lines) > MAX_LINES:
        errors.append(f"{MAX_LINES} lignes de facturation maximum.")
    for number, line in enumerate(values.lines, start=1):
        if not line.description.strip():
            errors.append(f"Ligne {number} : la désignation est obligatoire.")
        elif len(line.description.strip()) > _MAX_DESCRIPTION:
            errors.append(f"Ligne {number} : désignation trop longue ({_MAX_DESCRIPTION} max).")
        if any(_bad_number(v) or v is None for v in (line.quantity, line.unit_price, line.total)):
            errors.append(f"Ligne {number} : quantité, prix et total doivent être des nombres.")

    if errors:
        return None, errors

    def text_or_none(value: str) -> str | None:
        return value.strip() or None

    return {
        "invoice_number": text_or_none(values.invoice_number),
        "date": text_or_none(values.date),
        "supplier": text_or_none(values.supplier),
        "client": text_or_none(values.client),
        "lines": [
            {
                "description": line.description.strip(),
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "total": line.total,
            }
            for line in values.lines
        ],
        "subtotal_ht": values.subtotal_ht,
        "tva_rate": None if values.tva_percent is None else values.tva_percent / 100,
        "total_ttc": values.total_ttc,
    }, []


_LABELS = {"invoice_number": "N° facture", "supplier": "Fournisseur", "client": "Client"}


class _Deleter(Protocol):
    def delete(self, record_id: str) -> None: ...


def delete_invoice(client: _Deleter, record_id: str, state: MutableMapping[str, Any]) -> str | None:
    """Erase the invoice (record, cache entry, data in the file) and forget it in the session.

    Kept out of the page so it can be tested: a Streamlit dialog re-runs only its own fragment,
    which the test tool cannot reproduce.

    Returns:
        None on success, or the message to show when the deletion failed (the invoice is then
        left selected, so the user can retry).
    """
    try:
        client.delete(record_id)
    except UiError as error:
        return str(error)
    state.pop(CURRENT_RECORD_KEY, None)
    state[FLASH_KEY] = "Facture supprimée."
    return None
