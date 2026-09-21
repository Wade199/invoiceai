from __future__ import annotations

import csv
import io
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Literal

from src.services.repository import StoredInvoice

_BOM = "﻿"  # makes Excel read the file as UTF-8 (accents) instead of the ANSI code page
_FORMULA_TRIGGERS = ("=", "+", "-", "@")
_LEADING_BLANKS = " \t\r\n"
_STATUS_LABELS = {"high": "élevée", "low": "faible"}

_LOCALES = {
    # French Excel expects ";" as separator and "," as decimal mark: with "," as separator
    # the whole file lands in one column, and "120.00" is read as text.
    "fr": (";", ","),
    "intl": (",", "."),
}
Locale = Literal["fr", "intl"]


def neutralize(value: str) -> str:
    """Make a text cell safe to open in a spreadsheet (CSV / formula injection).

    Excel, LibreOffice and Google Sheets run a cell that starts with `=`, `+`, `-` or `@`
    as a formula, and `=cmd|' /C calc'!A0` can even launch a program. A supplier name on a
    hostile invoice is enough to plant one. OWASP's fix: prefix such cells with an
    apostrophe, which spreadsheets show but never evaluate. Leading blanks are looked past
    (some applications trim them), and a tab or carriage return is a trigger by itself.
    """
    if value.startswith(("\t", "\r")) or value.lstrip(_LEADING_BLANKS).startswith(
        _FORMULA_TRIGGERS
    ):
        return "'" + value
    return value


def _number(value: float | None, decimal_mark: str, min_decimals: int = 2) -> str:
    """Format an amount ourselves (never treated as untrusted text, so `-12.50` stays numeric)."""
    if value is None:
        return ""
    number = Decimal(str(value)).normalize()
    if number.as_tuple().exponent > -min_decimals:  # type: ignore[operator]
        number = number.quantize(Decimal(1).scaleb(-min_decimals))
    return format(number, "f").replace(".", decimal_mark)


def _tva_amount(stored: StoredInvoice) -> float | None:
    invoice = stored.invoice
    if invoice.total_ttc is None or invoice.subtotal_ht is None:
        return None
    return round(invoice.total_ttc - invoice.subtotal_ht, 2)


def _percent(rate: float | None) -> float | None:
    """0.2 and 20 both mean 20 %: validate_invoice flags the second form."""
    if rate is None:
        return None
    return rate * 100 if rate <= 1 else rate


# Each column: (header, extractor returning either a text or a number). Headers are fixed
# constants; only the values come from the (untrusted) invoice.
_Cell = str | float | None
INVOICE_COLUMNS: dict[str, tuple[str, Callable[[StoredInvoice], _Cell]]] = {
    "date": ("Date", lambda s: s.invoice.date or ""),
    "invoice_number": ("N° facture", lambda s: s.invoice.invoice_number or ""),
    "supplier": ("Fournisseur", lambda s: s.invoice.supplier or ""),
    "client": ("Client", lambda s: s.invoice.client or ""),
    "subtotal_ht": ("Montant HT", lambda s: s.invoice.subtotal_ht),
    "tva_amount": ("Montant TVA", _tva_amount),
    "tva_rate": ("Taux TVA (%)", lambda s: _percent(s.invoice.tva_rate)),
    "total_ttc": ("Montant TTC", lambda s: s.invoice.total_ttc),
    "status": ("Fiabilité", lambda s: _STATUS_LABELS[s.invoice.extraction_confidence]),
    "warnings": ("Avertissements", lambda s: " | ".join(s.invoice.warnings)),
    "file": ("Fichier", lambda s: s.display_name),
    "processed_at": ("Traité le", lambda s: s.created_at.strftime("%Y-%m-%d %H:%M")),
}
DEFAULT_INVOICE_COLUMNS = (
    "date",
    "invoice_number",
    "supplier",
    "subtotal_ht",
    "tva_amount",
    "total_ttc",
)
_NUMERIC_COLUMNS = {"subtotal_ht", "tva_amount", "tva_rate", "total_ttc"}


def _write(header: Sequence[str], rows: Sequence[Sequence[str]], separator: str) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=separator, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return (_BOM + buffer.getvalue()).encode("utf-8")


def _locale(locale: str) -> tuple[str, str]:
    try:
        return _LOCALES[locale]
    except KeyError:
        raise ValueError(f"locale must be one of {sorted(_LOCALES)}") from None


def invoices_csv(
    invoices: Sequence[StoredInvoice],
    *,
    columns: Sequence[str] = DEFAULT_INVOICE_COLUMNS,
    locale: Locale = "fr",
) -> bytes:
    """One row per invoice, with the chosen columns, as UTF-8 (BOM) CSV bytes.

    Raises:
        ValueError: If `columns` is empty or names an unknown column, or `locale` is unknown.
    """
    separator, decimal_mark = _locale(locale)
    if not columns:
        raise ValueError("at least one column is required")
    unknown = [name for name in columns if name not in INVOICE_COLUMNS]
    if unknown:
        raise ValueError(f"unknown columns: {unknown}")

    header = [INVOICE_COLUMNS[name][0] for name in columns]
    rows = []
    for stored in invoices:
        row = []
        for name in columns:
            value = INVOICE_COLUMNS[name][1](stored)
            if name in _NUMERIC_COLUMNS:
                row.append(_number(value, decimal_mark))  # type: ignore[arg-type]
            else:
                row.append(neutralize(value or ""))  # type: ignore[arg-type]
        rows.append(row)
    return _write(header, rows, separator)


def lines_csv(invoices: Sequence[StoredInvoice], *, locale: Locale = "fr") -> bytes:
    """One row per invoice line (the invoice's number, date and supplier are repeated)."""
    separator, decimal_mark = _locale(locale)
    header = [
        "N° facture",
        "Date",
        "Fournisseur",
        "Désignation",
        "Quantité",
        "Prix unitaire HT",
        "Total HT",
    ]
    rows = []
    for stored in invoices:
        invoice = stored.invoice
        for line in invoice.lines:
            rows.append(
                [
                    neutralize(invoice.invoice_number or ""),
                    neutralize(invoice.date or ""),
                    neutralize(invoice.supplier or ""),
                    neutralize(line.description),
                    _number(line.quantity, decimal_mark, min_decimals=0),
                    _number(line.unit_price, decimal_mark),
                    _number(line.total, decimal_mark),
                ]
            )
    return _write(header, rows, separator)


def suggested_filename(
    invoices: Sequence[StoredInvoice], kind: Literal["invoices", "lines"] = "invoices"
) -> str:
    """`invoices_2026-08-01_to_2026-09-18.csv`: built from dates only, never from user text."""
    if not invoices:
        return f"{kind}.csv"
    dates = [stored.effective_date for stored in invoices]
    return f"{kind}_{min(dates).isoformat()}_to_{max(dates).isoformat()}.csv"
