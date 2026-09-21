from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, field_validator

from src.core.sanitize import clean_text

# The LLM output is UNTRUSTED (the PDF may have steered it, see docs/security): every string
# is stripped of control / invisible characters and length-capped, every number is bounded
# and finite, lists are capped. Anything outside these bounds fails validation.
_MAX_AMOUNT = 1_000_000_000.0
MAX_LINES = 200


def _safe(max_length: int):
    return AfterValidator(lambda value: clean_text(value, max_length))


ShortText = Annotated[str, _safe(100)]  # invoice number, date
NameText = Annotated[str, _safe(200)]  # supplier, client
DescriptionText = Annotated[str, _safe(500)]  # line description
WarningText = Annotated[str, _safe(300)]

Amount = Annotated[float, Field(allow_inf_nan=False, ge=-_MAX_AMOUNT, le=_MAX_AMOUNT)]
# A rate is a fraction (0.20); 20 is tolerated here and flagged by validate_invoice.
Rate = Annotated[float, Field(allow_inf_nan=False, ge=0, le=100)]


class InvoiceLineItem(BaseModel):
    """A single line item of an invoice or quote.

    Attributes:
        description: Free-text description of the product/service.
        quantity: Number of units.
        unit_price: Price per unit, excluding tax (HT).
        total: quantity * unit_price, excluding tax (HT).
    """

    description: DescriptionText
    quantity: Amount
    unit_price: Amount
    total: Amount


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

    invoice_number: ShortText | None = None
    date: ShortText | None = None
    supplier: NameText | None = None
    client: NameText | None = None
    lines: list[InvoiceLineItem] = Field(default_factory=list)
    subtotal_ht: Amount | None = None
    tva_rate: Rate | None = None
    total_ttc: Amount | None = None
    extraction_confidence: Literal["high", "low"] = "high"
    warnings: list[WarningText] = Field(default_factory=list, max_length=50)

    @field_validator("lines")
    @classmethod
    def _cap_lines(cls, lines: list[InvoiceLineItem]) -> list[InvoiceLineItem]:
        # Not `Field(max_length=...)`: that adds "maxItems" to the JSON schema sent to Gemini,
        # which rejects it on arrays of objects (400 INVALID_ARGUMENT, found on the real API).
        if len(lines) > MAX_LINES:
            raise ValueError(f"more than {MAX_LINES} invoice lines")
        return lines
