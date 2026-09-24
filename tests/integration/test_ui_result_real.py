"""The Result page and its logic against the REAL FastAPI application (in memory)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from src.api import routes
from src.api.app import create_app
from src.models.schemas import ExtractedInvoice, InvoiceLineItem
from src.ui import services
from src.ui.api_client import ApiClient
from src.ui.errors import ApiError
from src.ui.result_logic import delete_invoice, form_from_view, validate_and_build

pytestmark = pytest.mark.integration

TOKEN = "p" * 43
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
PAGE = str(Path(__file__).resolve().parents[2] / "src" / "ui" / "pages" / "result.py")


def _invoice() -> ExtractedInvoice:
    return ExtractedInvoice(
        invoice_number="F-2026-001",
        date="2026-09-10",
        supplier="Orange SA",
        client="Dupont SARL",
        lines=[InvoiceLineItem(description="Forfait", quantity=2, unit_price=50.0, total=100.0)],
        subtotal_ht=100.0,
        tva_rate=0.2,
        total_ttc=120.0,
    )


@pytest.fixture(autouse=True)
def _config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", TOKEN)
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")
    monkeypatch.setattr(routes, "process_invoice", lambda _path, _mime: _invoice())


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    with TestClient(create_app(), headers={"Authorization": f"Bearer {TOKEN}"}) as http:
        client = ApiClient(http)
        monkeypatch.setattr(services, "get_client", lambda: client)
        yield client


def _page(record_id: str) -> AppTest:
    app = AppTest.from_file(PAGE, default_timeout=30)
    app.session_state["current_record_id"] = record_id
    return app.run()


def _field(app: AppTest, label: str):
    return next(w for w in [*app.text_input, *app.number_input] if w.label == label)


def test_an_untouched_form_survives_the_round_trip_through_the_real_api(api: ApiClient) -> None:
    created = api.upload("f.pdf", PDF)
    payload, problems = validate_and_build(form_from_view(created))
    assert problems == []
    updated = api.update(created.id, payload)  # the API validates the payload for real
    assert updated.invoice == created.invoice  # 20 % -> 0.2 -> 20 %: nothing drifted
    assert updated.status == "high"


def test_the_server_recomputes_reliability_after_a_correction(api: ApiClient) -> None:
    created = api.upload("f.pdf", PDF)
    form = form_from_view(created)
    payload, _ = validate_and_build(type(form)(**{**form.__dict__, "total_ttc": 999.0}))
    updated = api.update(created.id, payload)
    assert updated.status == "low" and updated.invoice.warnings  # the server decided, not the UI


def test_every_payload_the_ui_builds_is_accepted_by_the_api(api: ApiClient) -> None:
    """Credit note, no VAT, no lines, empty texts: the UI's validation must not disagree."""
    created = api.upload("f.pdf", PDF)
    base = form_from_view(created)
    cases = [
        type(base)(**{**base.__dict__, "subtotal_ht": -100.0, "total_ttc": -120.0}),
        type(base)(**{**base.__dict__, "tva_percent": None}),
        type(base)(**{**base.__dict__, "lines": []}),
        type(base)(
            **{**base.__dict__, "supplier": "", "client": "", "invoice_number": "", "date": ""}
        ),
        type(base)(**{**base.__dict__, "tva_percent": 5.5, "date": "2026-02-28"}),
    ]
    for form in cases:
        payload, problems = validate_and_build(form)
        assert problems == []
        api.update(created.id, payload)  # would raise ApiError(422) on any disagreement


def test_the_page_shows_a_real_record_and_saves_a_correction(api: ApiClient) -> None:
    created = api.upload("f.pdf", PDF)
    app = _page(created.id)
    assert not app.exception and _field(app, "Fournisseur").value == "Orange SA"

    _field(app, "Montant TTC (€)").set_value(999.0)  # makes the amounts inconsistent
    next(b for b in app.button if b.label == "💾 Sauvegarder").click().run()

    assert not app.exception
    assert any("Modifications enregistrées" in s.value for s in app.success)
    after = api.get(created.id)
    assert after.invoice.total_ttc == 999.0 and after.status == "low"
    # the page reloaded from the server: it now warns about the inconsistency
    # (shown escaped by safe(), so "total_ttc" reads "total\\_ttc": look for the figure)
    assert any("999" in w.value for w in app.warning)


def test_deleting_through_the_real_api_erases_the_record(api: ApiClient) -> None:
    created = api.upload("f.pdf", PDF)
    state = {"current_record_id": created.id}
    assert delete_invoice(api, created.id, state) is None
    with pytest.raises(ApiError) as gone:
        api.get(created.id)
    assert gone.value.status == 404
    assert (
        delete_invoice(api, created.id, {"current_record_id": created.id}) == "Facture introuvable."
    )

    app = _page(created.id)  # a page still pointing at it says so, instead of crashing
    assert not app.exception and "n'existe plus" in app.warning[0].value
