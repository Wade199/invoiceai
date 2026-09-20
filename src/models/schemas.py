from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class InvoiceLineItem(BaseModel):
    """A single line item of an invoice or quote.

    Attributes:
        description: Free-text description of the product/service.
        quantity: Number of units.
        unit_price: Price per unit, excluding tax (HT).
        total: quantity * unit_price, excluding tax (HT).
    """

    description: str
    quantity: float
    unit_price: float
    total: float


class ExtractedInvoice(BaseModel):
    """Structured data extracted from an invoice/quote by the LLM.

    All fields except `lines` and `warnings` are nullable: the LLM is
    instructed to return `null` rather than guess when a value is unclear.

    Attributes:
        invoice_number: Invoice/quote reference number.
        date: Invoice date in ISO 8601 format (YYYY-MM-DD).
        supplier: Name of the company issuing the invoice.
        client: Name of the company/person being billed.
        lines: List of line items.
        subtotal_ht: Total excluding tax, before VAT.
        tva_rate: VAT rate applied (e.g. 0.20 for 20%).
        total_ttc: Total including tax.
        extraction_confidence: "low" when business validation rules
            (src/services/validate_invoice.py) detect an inconsistency
            (e.g. totals don't add up), "high" otherwise.
        warnings: Non-blocking messages about the extraction.
    """

    invoice_number: str | None = None
    date: str | None = None
    supplier: str | None = None
    client: str | None = None
    lines: list[InvoiceLineItem] = Field(default_factory=list)
    subtotal_ht: float | None = None
    tva_rate: float | None = None
    total_ttc: float | None = None
    extraction_confidence: Literal["high", "low"] = "high"
    warnings: list[str] = Field(default_factory=list)
