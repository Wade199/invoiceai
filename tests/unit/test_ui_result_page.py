from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.ui import services
from src.ui.errors import ApiError, ApiUnavailableError
from src.ui.models import InvoiceData, InvoiceView, LineView
from src.ui.result_logic import delete_invoice
from src.ui.safe import safe

ROOT = Path(__file__).resolve().parents[2]
PAGE = str(ROOT / "src" / "ui" / "pages" / "result.py")
APP = str(ROOT / "src" / "ui" / "app.py")
RECORD_ID = "3f9a1c2e-7b4d-4e8a-9c31-5d2f0a6b8e14"
HOSTILE = "![x](http://evil.example/?d=secret) <script>alert(1)</script>"


def _view(*, status: str = "high", warnings=(), **invoice_overrides) -> InvoiceView:
    now = datetime.now(UTC)
    invoice = {
        "invoice_number": "F-2026-001",
        "date": "2026-09-10",
        "supplier": "Orange SA",
        "client": "Dupont SARL",
        "subtotal_ht": 100.0,
        "tva_rate": 0.2,
        "total_ttc": 120.0,
        "lines": [LineView(description="Forfait", quantity=1, unit_price=100.0, total=100.0)],
        "warnings": list(warnings),
        "extraction_confidence": status,
    }
    invoice.update(invoice_overrides)
    return InvoiceView(
        id=RECORD_ID,
        created_at=now,
        expires_at=now + timedelta(days=30, hours=1),
        display_name="facture.pdf",
        status=status,
        invoice=InvoiceData(**invoice),
    )


class FakeClient:
    def __init__(self, view: InvoiceView | Exception | None = None, update_error=None) -> None:
        self.view = view if view is not None else _view()
        self.update_error = update_error
        self.updates: list[tuple[str, dict]] = []
        self.deleted: list[str] = []

    def check(self) -> None:
        return None

    def get(self, record_id: str) -> InvoiceView:
        if isinstance(self.view, Exception):
            raise self.view
        return self.view

    def update(self, record_id: str, data: dict) -> InvoiceView:
        if self.update_error:
            raise self.update_error
        self.updates.append((record_id, data))
        return self.view

    def delete(self, record_id: str) -> None:
        self.deleted.append(record_id)


def _open(monkeypatch: pytest.MonkeyPatch, client: FakeClient, *, selected: bool = True) -> AppTest:
    monkeypatch.setattr(services, "get_client", lambda: client)
    app = AppTest.from_file(PAGE, default_timeout=30)
    if selected:
        app.session_state["current_record_id"] = RECORD_ID
    return app.run()


def _field(app: AppTest, label: str):
    return next(w for w in [*app.text_input, *app.number_input] if w.label == label)


def _button(app: AppTest, label: str):
    return next(b for b in app.button if b.label == label)


# --- nothing to show ---
def test_without_a_selected_invoice_the_page_guides_the_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _open(monkeypatch, FakeClient(), selected=False)
    assert not app.exception and "Aucune facture sélectionnée" in app.info[0].value
    assert not app.text_input  # no form


def test_an_invoice_that_no_longer_exists_is_reported_and_forgotten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _open(monkeypatch, FakeClient(ApiError(404, "Facture introuvable.")))
    assert not app.exception and "n'existe plus" in app.warning[0].value
    assert "current_record_id" not in app.session_state and not app.text_input


@pytest.mark.parametrize(
    "error", [ApiError(503, "Serveur occupé."), ApiUnavailableError("API injoignable.")]
)
def test_an_api_problem_is_shown_as_a_message(monkeypatch: pytest.MonkeyPatch, error) -> None:
    app = _open(monkeypatch, FakeClient(error))
    assert not app.exception and len(app.error) == 1 and not app.text_input


# --- what the page shows ---
def test_the_left_column_shows_the_file_dates_reliability_and_automatic_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _open(monkeypatch, FakeClient())
    assert not app.exception
    assert [t.value for t in app.text][0] == "facture.pdf"
    assert any(
        "Suppression automatique" in i.value and "dans 30 jours" in i.value for i in app.info
    )
    assert any("Fiable" in m.value for m in app.markdown)
    assert any("cohérents" in s.value for s in app.success)


def test_a_record_to_check_lists_the_servers_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _view(status="low", warnings=["Line 1: quantity * unit_price = 20.00 but total = 25.00"])
    app = _open(monkeypatch, FakeClient(view))
    assert any("Line 1" in w.value for w in app.warning)
    assert not app.success  # no "amounts are consistent" reassurance


def test_the_form_is_filled_with_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _open(monkeypatch, FakeClient())
    assert _field(app, "Fournisseur").value == "Orange SA"
    assert _field(app, "N° facture").value == "F-2026-001"
    assert _field(app, "Date de la facture").value == "2026-09-10"
    assert _field(app, "Montant HT (€)").value == 100.0
    assert _field(app, "Taux de TVA (%)").value == 20.0  # 0.2 on the wire, 20 % on screen
    assert _field(app, "Montant TTC (€)").value == 120.0


def test_missing_values_leave_empty_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _open(
        monkeypatch, FakeClient(_view(supplier=None, tva_rate=None, total_ttc=None, lines=[]))
    )
    assert _field(app, "Fournisseur").value == ""
    assert (
        _field(app, "Taux de TVA (%)").value is None
        and _field(app, "Montant TTC (€)").value is None
    )


# --- saving ---
def test_saving_untouched_sends_the_same_data_and_confirms(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, client)
    _button(app, "💾 Sauvegarder").click().run()

    assert not app.exception and len(client.updates) == 1
    record_id, payload = client.updates[0]
    assert record_id == RECORD_ID
    assert payload["supplier"] == "Orange SA" and payload["tva_rate"] == 0.2
    assert payload["lines"] == [
        {"description": "Forfait", "quantity": 1.0, "unit_price": 100.0, "total": 100.0}
    ]
    assert any("Modifications enregistrées" in s.value for s in app.success)


def test_edited_fields_are_what_gets_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, client)
    _field(app, "Fournisseur").set_value("Orange (corrigé)")
    _field(app, "Client").set_value("")
    _field(app, "Taux de TVA (%)").set_value(5.5)
    _field(app, "Montant TTC (€)").set_value(105.5)
    _button(app, "💾 Sauvegarder").click().run()

    _, payload = client.updates[0]
    assert payload["supplier"] == "Orange (corrigé)" and payload["client"] is None
    assert payload["tva_rate"] == 0.055 and payload["total_ttc"] == 105.5
    assert set(payload) == {
        "invoice_number",
        "date",
        "supplier",
        "client",
        "lines",
        "subtotal_ht",
        "tva_rate",
        "total_ttc",
    }


def test_an_invalid_form_is_explained_and_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, client)
    _field(app, "Date de la facture").set_value("10/09/2026")
    _field(app, "Taux de TVA (%)").set_value(150.0)
    _button(app, "💾 Sauvegarder").click().run()

    assert client.updates == []
    messages = " ".join(e.value for e in app.error)
    assert "AAAA-MM-JJ" in messages and "TVA" in messages


def test_a_refusal_by_the_api_is_shown_and_nothing_is_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _open(monkeypatch, FakeClient(update_error=ApiError(422, HOSTILE)))
    _button(app, "💾 Sauvegarder").click().run()
    assert app.error[0].value == safe(HOSTILE)  # escaped: never becomes markup
    assert not any("enregistrées" in s.value for s in app.success)


# --- hostile content ---
def test_hostile_extracted_text_is_shown_as_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _view(status="low", supplier=HOSTILE, warnings=[HOSTILE])
    app = _open(monkeypatch, FakeClient(view))
    assert _field(app, "Fournisseur").value == HOSTILE  # an input shows its value literally
    assert app.warning[0].value == safe(HOSTILE)  # a message is escaped first
    assert "<script>" not in app.warning[0].value


# --- deleting ---
def test_deleting_asks_for_confirmation_before_doing_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    app = _open(monkeypatch, client)
    _button(app, "🗑 Supprimer cette facture").click().run()
    assert client.deleted == []  # nothing happens on the first click
    assert not app.exception


def test_the_confirmation_explains_what_will_be_erased(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _open(monkeypatch, FakeClient())
    _button(app, "🗑 Supprimer cette facture").click().run()
    assert any("définitive" in m.value for m in app.markdown)
    assert any(b.label == "Oui, supprimer" for b in app.button)


def test_delete_invoice_erases_and_forgets_it() -> None:
    client, state = FakeClient(), {"current_record_id": RECORD_ID}
    assert delete_invoice(client, RECORD_ID, state) is None
    assert client.deleted == [RECORD_ID]
    assert "current_record_id" not in state and state["result_flash"] == "Facture supprimée."


def test_a_failed_deletion_keeps_the_invoice_selected_and_returns_the_message() -> None:
    client, state = FakeClient(), {"current_record_id": RECORD_ID}

    def failing(_record_id: str) -> None:
        raise ApiError(500, "Erreur de stockage interne.")

    client.delete = failing
    assert delete_invoice(client, RECORD_ID, state) == "Erreur de stockage interne."
    assert state == {"current_record_id": RECORD_ID}  # nothing forgotten: the user can retry
