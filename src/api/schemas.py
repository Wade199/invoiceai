from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.schemas import (
    MAX_LINES,
    Amount,
    ExtractedInvoice,
    InvoiceLineItem,
    NameText,
    Rate,
    ShortText,
)
from src.services.repository import StoredInvoice

# Responses are explicit models: a field that is not declared here (the PDF hash, for
# instance) can never leak by accident.


class InvoiceOut(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    display_name: str
    status: Literal["high", "low"]
    invoice: ExtractedInvoice

    @classmethod
    def from_stored(cls, stored: StoredInvoice) -> InvoiceOut:
        return cls(
            id=stored.id,
            created_at=stored.created_at,
            expires_at=stored.expires_at,
            display_name=stored.display_name,
            status=stored.invoice.extraction_confidence,
            invoice=stored.invoice,
        )


class InvoiceSummary(BaseModel):
    """One row of the history screen."""

    id: str
    created_at: datetime
    display_name: str
    status: Literal["high", "low"]
    invoice_number: str | None
    date: str | None
    supplier: str | None
    client: str | None
    total_ttc: float | None

    @classmethod
    def from_stored(cls, stored: StoredInvoice) -> InvoiceSummary:
        invoice = stored.invoice
        return cls(
            id=stored.id,
            created_at=stored.created_at,
            display_name=stored.display_name,
            status=invoice.extraction_confidence,
            invoice_number=invoice.invoice_number,
            date=invoice.date,
            supplier=invoice.supplier,
            client=invoice.client,
            total_ttc=invoice.total_ttc,
        )


class InvoiceUpdate(BaseModel):
    """What a user may change: the extracted data, nothing else.

    `extra="forbid"`: fields such as `extraction_confidence`, `warnings`, `id` or `pdf_hash`
    are rejected, not ignored. The server recomputes reliability and warnings itself, so a
    client cannot mark its own edit "high confidence" (mass assignment).
    """

    model_config = ConfigDict(extra="forbid")

    invoice_number: ShortText | None = None
    date: ShortText | None = None
    supplier: NameText | None = None
    client: NameText | None = None
    lines: list[InvoiceLineItem] = Field(default_factory=list, max_length=MAX_LINES)
    subtotal_ht: Amount | None = None
    tva_rate: Rate | None = None
    total_ttc: Amount | None = None

    def to_invoice(self) -> ExtractedInvoice:
        return ExtractedInvoice(**self.model_dump())
