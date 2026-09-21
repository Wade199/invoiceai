from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from src.ui.models import InvoiceData, InvoiceView, LineView
from src.ui.result_logic import (
    MAX_LINES,
    FormValues,
    LineValues,
    form_from_view,
    to_percent,
    validate_and_build,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
ALLOWED_KEYS = {
    "invoice_number",
    "date",
    "supplier",
    "client",
    "lines",
    "subtotal_ht",
    "tva_rate",
    "total_ttc",
}


def _view() -> InvoiceView:
    return InvoiceView(
        id="3f9a1c2e-7b4d-4e8a-9c31-5d2f0a6b8e14",
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
        display_name="facture.pdf",
        status="high",
        invoice=InvoiceData(
            invoice_number="F-2026-001",
            date="2026-09-10",
            supplier="Orange SA",
            client="Dupont SARL",
            subtotal_ht=100.0,
            tva_rate=0.2,
            total_ttc=120.0,
            lines=[LineView(description="Forfait", quantity=2, unit_price=50.0, total=100.0)],
        ),
    )


def _values(**overrides) -> FormValues:
    data = {
        "invoice_number": "F-1",
        "date": "2026-09-10",
        "supplier": "Orange",
        "client": "Dupont",
        "subtotal_ht": 100.0,
        "tva_percent": 20.0,
        "total_ttc": 120.0,
        "lines": [LineValues("Forfait", 1.0, 100.0, 100.0)],
    }
    data.update(overrides)
    return FormValues(**data)


# --- VAT rate: a percentage in the form, a fraction on the wire ---
@pytest.mark.parametrize(
    ("rate", "expected"),
    [(0.2, 20.0), (20, 20.0), (0.055, 5.5), (0.0, 0.0), (0.07, 7.0), (5.5, 5.5), (None, None)],
)
def test_to_percent_accepts_a_fraction_or_a_percentage(rate, expected) -> None:
    assert to_percent(rate) == expected


def test_the_form_starts_from_the_record() -> None:
    form = form_from_view(_view())
    assert (form.invoice_number, form.date, form.supplier, form.client) == (
        "F-2026-001",
        "2026-09-10",
        "Orange SA",
        "Dupont SARL",
    )
    assert (form.subtotal_ht, form.tva_percent, form.total_ttc) == (100.0, 20.0, 120.0)
    assert form.lines == [LineValues("Forfait", 2.0, 50.0, 100.0)]


def test_missing_values_become_empty_fields_not_the_text_none() -> None:
    view = _view()
    view.invoice.supplier = None
    view.invoice.tva_rate = None
    form = form_from_view(view)
    assert form.supplier == "" and form.tva_percent is None


def test_saving_an_untouched_form_sends_back_exactly_what_was_received() -> None:
    payload, problems = validate_and_build(form_from_view(_view()))
    assert problems == []
    assert payload == {
        "invoice_number": "F-2026-001",
        "date": "2026-09-10",
        "supplier": "Orange SA",
        "client": "Dupont SARL",
        "lines": [{"description": "Forfait", "quantity": 2.0, "unit_price": 50.0, "total": 100.0}],
        "subtotal_ht": 100.0,
        "tva_rate": 0.2,  # 20 % in the form, 0.2 on the wire
        "total_ttc": 120.0,
    }


# --- what may be sent ---
def test_the_payload_only_ever_holds_the_fields_a_user_may_change() -> None:
    payload, _ = validate_and_build(_values())
    assert set(payload) == ALLOWED_KEYS  # never extraction_confidence, warnings, id, pdf_hash


def test_blank_and_padded_text_is_cleaned() -> None:
    payload, _ = validate_and_build(
        _values(invoice_number="   ", supplier="  Orange  ", client="", date=" 2026-09-10 ")
    )
    assert payload["invoice_number"] is None and payload["client"] is None
    assert payload["supplier"] == "Orange" and payload["date"] == "2026-09-10"


def test_empty_optional_amounts_are_sent_as_null() -> None:
    payload, problems = validate_and_build(
        _values(subtotal_ht=None, tva_percent=None, total_ttc=None, lines=[], date="")
    )
    assert problems == []
    assert payload["subtotal_ht"] is payload["tva_rate"] is payload["total_ttc"] is None
    assert payload["lines"] == [] and payload["date"] is None


@pytest.mark.parametrize("percent", [0.0, 5.5, 20.0, 100.0])
def test_vat_rates_in_range_are_accepted(percent: float) -> None:
    payload, problems = validate_and_build(_values(tva_percent=percent))
    assert problems == [] and payload["tva_rate"] == percent / 100


def test_a_credit_note_with_negative_amounts_is_allowed() -> None:
    payload, problems = validate_and_build(
        _values(
            subtotal_ht=-100.0, total_ttc=-120.0, lines=[LineValues("Avoir", 1.0, -100.0, -100.0)]
        )
    )
    assert problems == [] and payload["subtotal_ht"] == -100.0


# --- what is refused, with a clear message ---
@pytest.mark.parametrize(
    "bad_date", ["10/09/2026", "2026-13-01", "2026-9-1x", "hier", "2026/09/10"]
)
def test_a_date_must_be_iso(bad_date: str) -> None:
    payload, problems = validate_and_build(_values(date=bad_date))
    assert payload is None and any("AAAA-MM-JJ" in problem for problem in problems)


@pytest.mark.parametrize(
    "overrides",
    [
        {"subtotal_ht": 1e12},
        {"total_ttc": -1e12},
        {"subtotal_ht": math.inf},
        {"total_ttc": math.nan},
    ],
)
def test_absurd_amounts_are_refused(overrides: dict) -> None:
    payload, problems = validate_and_build(_values(**overrides))
    assert payload is None and any("hors limites" in problem for problem in problems)


@pytest.mark.parametrize("percent", [-0.5, 100.5, 1000.0, math.nan, math.inf])
def test_a_vat_rate_outside_0_100_is_refused(percent: float) -> None:
    payload, problems = validate_and_build(_values(tva_percent=percent))
    assert payload is None and any("TVA" in problem for problem in problems)


def test_texts_that_are_too_long_are_refused() -> None:
    payload, problems = validate_and_build(
        _values(invoice_number="x" * 101, supplier="s" * 201, client="c" * 201)
    )
    assert payload is None and len(problems) == 3


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (LineValues("", 1.0, 1.0, 1.0), "désignation est obligatoire"),
        (LineValues("   ", 1.0, 1.0, 1.0), "désignation est obligatoire"),
        (LineValues("x" * 501, 1.0, 1.0, 1.0), "trop longue"),
        (LineValues("ok", math.nan, 1.0, 1.0), "doivent être des nombres"),
        (LineValues("ok", 1.0, math.inf, 1.0), "doivent être des nombres"),
        (LineValues("ok", 1.0, 1.0, 1e12), "doivent être des nombres"),
    ],
)
def test_a_bad_line_is_reported_with_its_number(line: LineValues, expected: str) -> None:
    payload, problems = validate_and_build(_values(lines=[LineValues("ok", 1, 1, 1), line]))
    assert payload is None
    assert len(problems) == 1 and problems[0].startswith("Ligne 2") and expected in problems[0]


def test_the_number_of_lines_is_capped() -> None:
    line = LineValues("x", 1.0, 1.0, 1.0)
    assert validate_and_build(_values(lines=[line] * MAX_LINES))[1] == []
    payload, problems = validate_and_build(_values(lines=[line] * (MAX_LINES + 1)))
    assert payload is None and any(str(MAX_LINES) in problem for problem in problems)


def test_every_problem_is_reported_at_once() -> None:
    payload, problems = validate_and_build(
        _values(date="hier", tva_percent=200.0, lines=[LineValues("", 1.0, 1.0, 1.0)])
    )
    assert payload is None and len(problems) == 3
