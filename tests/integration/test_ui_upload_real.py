"""The UI's batch logic against the REAL FastAPI application (in memory)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import routes
from src.api.app import create_app
from src.models.schemas import ExtractedInvoice, InvoiceLineItem
from src.ui.api_client import ApiClient
from src.ui.upload_logic import Candidate, process_batch

pytestmark = pytest.mark.integration

TOKEN = "b" * 43
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def _invoice() -> ExtractedInvoice:
    return ExtractedInvoice(
        invoice_number="F-1",
        date="2026-09-10",
        supplier="Orange SA",
        lines=[InvoiceLineItem(description="Forfait", quantity=1, unit_price=100.0, total=100.0)],
        subtotal_ht=100.0,
        tva_rate=0.2,
        total_ttc=120.0,
    )


@pytest.fixture(autouse=True)
def _config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", TOKEN)
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")  # smaller than the UI's own 10 MB limit
    monkeypatch.setattr(routes, "process_invoice", lambda _path, _mime: _invoice())


def _client(**env: str):
    return TestClient(create_app(), headers={"Authorization": f"Bearer {TOKEN}"})


def test_a_mixed_batch_gives_one_honest_outcome_per_file() -> None:
    too_big_for_the_server = PDF + b"0" * (3 * 1024 * 1024)  # passes the UI's 10 MB precheck
    candidates = [
        Candidate("ok.pdf", PDF),
        Candidate("fake.pdf", b"MZ\x90\x00 an executable"),  # skipped by the UI, never sent
        Candidate("big.pdf", too_big_for_the_server),  # refused by the server (413)
        Candidate("ok2.pdf", PDF),
    ]
    with _client() as http:
        api = ApiClient(http)
        outcomes = process_batch(api, candidates)
        stored = api.list_invoices()

    assert [o.kind for o in outcomes] == ["ok", "skipped", "error", "ok"]
    assert outcomes[0].record.invoice.supplier == "Orange SA"
    assert outcomes[2].message == "Fichier trop volumineux."
    assert len(stored) == 2  # only the two valid files were stored


def test_the_rate_limit_stops_the_batch_and_the_rest_is_never_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPLOAD_RATE_LIMIT_PER_MINUTE", "2")
    with _client() as http:
        api = ApiClient(http)
        outcomes = process_batch(api, [Candidate(f"f{i}.pdf", PDF) for i in range(5)])
        stored = api.list_invoices()

    assert [o.kind for o in outcomes] == ["ok", "ok", "error", "not_run", "not_run"]
    assert outcomes[2].retry_after and 1 <= outcomes[2].retry_after <= 60
    assert len(stored) == 2
    assert "Non traité" in outcomes[3].message


def test_a_wrong_token_stops_everything_with_a_configuration_hint() -> None:
    with TestClient(create_app(), headers={"Authorization": "Bearer " + "x" * 43}) as http:
        outcomes = process_batch(
            ApiClient(http), [Candidate("a.pdf", PDF), Candidate("b.pdf", PDF)]
        )
    assert [o.kind for o in outcomes] == ["error", "not_run"]
    assert "API_TOKEN" in outcomes[0].message
