"""History and Export logic against the REAL FastAPI application (in memory)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.api import routes
from src.api.app import create_app
from src.models.schemas import ExtractedInvoice, InvoiceLineItem
from src.ui.api_client import ApiClient
from src.ui.errors import ApiError
from src.ui.export_logic import COLUMN_CHOICES, build_request, prepare_export
from src.ui.history_logic import STATUS_CHOICES, delete_many, ids_for_selection, to_frame

pytestmark = pytest.mark.integration

TOKEN = "h" * 43
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
HOSTILE_SUPPLIER = "=cmd|' /C calc'!A0"


def _invoice(
    supplier: str, day: str, ttc: float = 120.0, number: str = "F-1", confidence: str = "high"
) -> ExtractedInvoice:
    return ExtractedInvoice(
        invoice_number=number,
        date=day,
        supplier=supplier,
        client="Dupont",
        lines=[InvoiceLineItem(description="Forfait", quantity=1, unit_price=100.0, total=100.0)],
        subtotal_ht=100.0,
        tva_rate=0.2,
        total_ttc=ttc,
        extraction_confidence=confidence,
    )


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("UPLOAD_RATE_LIMIT_PER_MINUTE", "100")
    queue = [
        _invoice("Orange SA", "2026-09-10"),
        _invoice("EDF", "2026-08-20", number="E-77"),
        # process_invoice is faked, so the reliability validate_invoice would set is explicit
        _invoice("Boulangerie Lune", "2026-09-15", ttc=999.0, number="B-3", confidence="low"),
    ]
    monkeypatch.setattr(routes, "process_invoice", lambda _path, _mime: queue.pop(0))
    with TestClient(create_app(), headers={"Authorization": f"Bearer {TOKEN}"}) as http:
        client = ApiClient(http)
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            client.upload(name, PDF)
        yield client


def test_the_history_table_shows_what_the_api_returns(api: ApiClient) -> None:
    rows = api.list_invoices()
    frame = to_frame(rows)
    assert len(frame) == 3
    assert set(frame["Fournisseur"]) == {"Orange SA", "EDF", "Boulangerie Lune"}
    assert set(frame["Fiabilité"]) == {"✅ Fiable", "⚠️ À vérifier"}


def test_each_filter_of_the_page_reaches_the_real_search(api: ApiClient) -> None:
    assert [r.supplier for r in api.list_invoices(query="edf")] == ["EDF"]
    assert [r.supplier for r in api.list_invoices(status=STATUS_CHOICES["⚠️ À vérifier"])] == [
        "Boulangerie Lune"
    ]
    august = api.list_invoices(date_from=date(2026, 8, 1), date_to=date(2026, 8, 31))
    assert [r.supplier for r in august] == ["EDF"]
    assert api.list_invoices(query="nothing-like-this") == []


def test_selected_rows_map_back_to_the_right_invoices(api: ApiClient) -> None:
    rows = api.list_invoices()
    frame = to_frame(rows)
    position = int(frame.index[frame["Fournisseur"] == "EDF"][0])
    assert api.get(ids_for_selection(rows, [position])[0]).invoice.supplier == "EDF"


def test_export_of_a_selection_through_the_ui_logic(api: ApiClient) -> None:
    rows = api.list_invoices()
    request, problems = build_request(
        scope="selection",
        ids=[r.id for r in rows[:2]],
        kind="invoices",
        locale="fr",
        columns=["supplier", "total_ttc"],
        date_from=None,
        date_to=None,
        status=None,
    )
    assert problems == []
    exported = prepare_export(api, request)
    lines = exported.content.decode("utf-8-sig").splitlines()
    assert lines[0] == "Fournisseur;Montant TTC" and len(lines) == 3
    assert exported.filename.startswith("invoices_") and exported.filename.endswith(".csv")


def test_every_column_the_page_offers_is_accepted_by_the_api(api: ApiClient) -> None:
    request, _ = build_request(
        scope="filters",
        ids=[],
        kind="invoices",
        locale="intl",
        columns=list(COLUMN_CHOICES),
        date_from=None,
        date_to=None,
        status=None,
    )
    exported = prepare_export(api, request)  # would raise ApiError(422) on any drift
    header = exported.content.decode("utf-8-sig").splitlines()[0].split(",")
    assert header == list(COLUMN_CHOICES.values())


def test_the_lines_file_and_the_period_filter(api: ApiClient) -> None:
    request, _ = build_request(
        scope="filters",
        ids=[],
        kind="lines",
        locale="fr",
        columns=[],
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        status=None,
    )
    exported = prepare_export(api, request)
    lines = exported.content.decode("utf-8-sig").splitlines()
    assert len(lines) == 3  # header + one line for each of the two September invoices
    assert exported.filename.startswith("lines_")


def test_a_hostile_supplier_cannot_plant_a_formula_through_the_whole_chain(api: ApiClient) -> None:
    """Corrected in the UI, exported through the UI logic: the CSV must stay inert."""
    record = api.list_invoices()[0]
    fixed = api.get(record.id).invoice.model_dump(exclude={"extraction_confidence", "warnings"})
    api.update(record.id, {**fixed, "supplier": HOSTILE_SUPPLIER})
    request, _ = build_request(
        scope="selection",
        ids=[record.id],
        kind="invoices",
        locale="fr",
        columns=["supplier"],
        date_from=None,
        date_to=None,
        status=None,
    )
    csv = prepare_export(api, request).content.decode("utf-8-sig").splitlines()
    assert csv[1] == "'" + HOSTILE_SUPPLIER  # neutralised by the server


def test_deleting_several_invoices_really_erases_them(api: ApiClient) -> None:
    rows = api.list_invoices()
    state = {"current_record_id": rows[0].id}
    report = delete_many(api, [r.id for r in rows[:2]], state)
    assert report.deleted == 2 and "current_record_id" not in state
    assert len(api.list_invoices()) == 1
    again = delete_many(api, [r.id for r in rows[:2]])  # already gone: counts as done
    assert again.already_gone == 2 and again.deleted == 0
    with pytest.raises(ApiError) as gone:
        api.get(rows[0].id)
    assert gone.value.status == 404
