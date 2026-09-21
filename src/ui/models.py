from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Read-side models of the API's answers. Deliberately independent of the backend code
# (src/api, src/services): the interface only knows the HTTP contract.
Status = Literal["high", "low"]


class _View(BaseModel):
    model_config = ConfigDict(extra="ignore")  # a field added by the API must not break the UI


class LineView(_View):
    description: str
    quantity: float
    unit_price: float
    total: float


class InvoiceData(_View):
    invoice_number: str | None = None
    date: str | None = None
    supplier: str | None = None
    client: str | None = None
    lines: list[LineView] = Field(default_factory=list)
    subtotal_ht: float | None = None
    tva_rate: float | None = None
    total_ttc: float | None = None
    extraction_confidence: Status = "high"
    warnings: list[str] = Field(default_factory=list)


class InvoiceView(_View):
    id: str
    created_at: datetime
    expires_at: datetime
    display_name: str
    status: Status
    invoice: InvoiceData


class SummaryView(_View):
    id: str
    created_at: datetime
    display_name: str
    status: Status
    invoice_number: str | None = None
    date: str | None = None
    supplier: str | None = None
    client: str | None = None
    total_ttc: float | None = None


class ExportFile(_View):
    filename: str
    content: bytes
