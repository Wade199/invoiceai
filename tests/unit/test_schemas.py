from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.schemas import ExtractedInvoice, InvoiceLineItem


def test_extracted_invoice_defaults_to_empty_lines_and_high_confidence():
    invoice = ExtractedInvoice()

    assert invoice.lines == []
    assert invoice.warnings == []
    assert invoice.extraction_confidence == "high"
    assert invoice.invoice_number is None


def test_extracted_invoice_accepts_line_items():
    line = InvoiceLineItem(description="Consulting", quantity=2, unit_price=100.0, total=200.0)
    invoice = ExtractedInvoice(invoice_number="INV-42", lines=[line])

    assert invoice.lines[0].total == 200.0


def test_extracted_invoice_rejects_invalid_confidence_value():
    with pytest.raises(ValidationError):
        ExtractedInvoice(extraction_confidence="medium")


def test_invoice_line_item_requires_all_fields():
    with pytest.raises(ValidationError):
        InvoiceLineItem(description="Missing numbers")


def _walk(node):
    """Yield every dict of a JSON schema, recursively."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_schema_sent_to_gemini_has_no_maxitems_on_object_arrays() -> None:
    """Regression: Gemini answers 400 INVALID_ARGUMENT on `maxItems` for arrays of objects.

    Found on the real API (mocked tests cannot see it); size caps go in validators instead.
    """
    schema = ExtractedInvoice.model_json_schema()
    for node in _walk(schema):
        if node.get("type") == "array" and "$ref" in node.get("items", {}):
            assert "maxItems" not in node, node
