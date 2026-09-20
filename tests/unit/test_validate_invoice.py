from __future__ import annotations

import pytest

from src.models.schemas import ExtractedInvoice, InvoiceLineItem
from src.services.validate_invoice import validate_invoice


def _invoice(**overrides) -> ExtractedInvoice:
    data = {
        "invoice_number": "F-001",
        "lines": [
            InvoiceLineItem(description="A", quantity=2, unit_price=10.0, total=20.0),
            InvoiceLineItem(description="B", quantity=1, unit_price=30.0, total=30.0),
        ],
        "subtotal_ht": 50.0,
        "tva_rate": 0.20,
        "total_ttc": 60.0,
    }
    data.update(overrides)
    return ExtractedInvoice(**data)


def test_consistent_invoice_stays_high_confidence() -> None:
    result = validate_invoice(_invoice())
    assert result.extraction_confidence == "high"
    assert result.warnings == []


def test_line_total_mismatch_flagged() -> None:
    bad_line = InvoiceLineItem(description="A", quantity=2, unit_price=10.0, total=25.0)
    result = validate_invoice(_invoice(lines=[bad_line], subtotal_ht=25.0, total_ttc=30.0))
    assert result.extraction_confidence == "low"
    assert any("Line 1" in w for w in result.warnings)


def test_subtotal_mismatch_flagged() -> None:
    result = validate_invoice(_invoice(subtotal_ht=80.0, total_ttc=96.0))
    assert result.extraction_confidence == "low"
    assert any("Sum of lines" in w for w in result.warnings)


def test_total_ttc_mismatch_flagged() -> None:
    result = validate_invoice(_invoice(total_ttc=75.0))
    assert result.extraction_confidence == "low"
    assert any("total_ttc" in w for w in result.warnings)


def test_multiple_errors_give_multiple_warnings() -> None:
    result = validate_invoice(_invoice(subtotal_ht=80.0, total_ttc=75.0))
    assert len(result.warnings) == 2


@pytest.mark.parametrize("delta", [0.0, 0.01, 0.02, -0.02])
def test_rounding_within_tolerance_is_accepted(delta: float) -> None:
    result = validate_invoice(_invoice(total_ttc=60.0 + delta))
    assert result.extraction_confidence == "high"


def test_just_above_tolerance_is_rejected() -> None:
    result = validate_invoice(_invoice(total_ttc=60.05))
    assert result.extraction_confidence == "low"


def test_missing_fields_skip_rules_without_flagging() -> None:
    empty = ExtractedInvoice()
    assert validate_invoice(empty).extraction_confidence == "high"
    no_tva = _invoice(tva_rate=None)
    assert validate_invoice(no_tva).extraction_confidence == "high"


def test_existing_warnings_preserved_and_input_not_mutated() -> None:
    original = _invoice(total_ttc=75.0, warnings=["from LLM"])
    result = validate_invoice(original)
    assert result.warnings[0] == "from LLM"
    assert len(result.warnings) == 2
    assert original.extraction_confidence == "high"
    assert original.warnings == ["from LLM"]
