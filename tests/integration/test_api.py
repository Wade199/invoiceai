"""The whole API through HTTP: auth, hosts, headers, validation, lifecycle, errors, limits, export.

Real app (`create_app()` with its lifespan), real middleware, real database, real cache and
real OCR on the sample PDF. Only Gemini is replaced (by a fake), and, in the tests about
errors and limits, the whole extraction (to keep them fast).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from src.api import routes
from src.api.app import create_app
from src.api.security import ConcurrencyLimiter
from src.core import exceptions as exc
from src.core.database import session_scope
from src.models.schemas import ExtractedInvoice, InvoiceLineItem
from src.services import cache, pipeline
from src.services.repository import InvoiceRepository

pytestmark = pytest.mark.integration

TOKEN = "s" * 43
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
HASH = "a" * 64
MISSING_ID = "00000000-0000-4000-8000-000000000000"
NOW = datetime.now(UTC)

GOOD = ExtractedInvoice(
    invoice_number="F-2026-001",
    date="2026-09-10",
    supplier="Orange SA",
    client="Dupont SARL",
    lines=[InvoiceLineItem(description="Forfait", quantity=1, unit_price=100.0, total=100.0)],
    subtotal_ht=100.0,
    tva_rate=0.2,
    total_ttc=120.0,
)
SECURITY_HEADERS = {
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


@pytest.fixture(autouse=True)
def _config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", TOKEN)
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def fake_gemini(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def fake(document):
        calls.append(document.source_file.name)
        return GOOD

    monkeypatch.setattr(pipeline, "extract_invoice_data", fake)
    return calls


def _seed(invoice: ExtractedInvoice = GOOD, *, pdf_hash: str = HASH, now: datetime | None = None):
    with session_scope() as session:
        return InvoiceRepository(session).create(
            invoice, pdf_hash=pdf_hash, display_name="facture.pdf", now=now or NOW
        )


def _upload(client: TestClient, data: bytes = PDF, *, name="f.pdf", mime="application/pdf"):
    return client.post("/invoices", files={"file": (name, data, mime)}, headers=AUTH)


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


# --- who can call what ---
def test_health_needs_no_token_and_leaks_nothing(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


PROTECTED = [
    ("POST", "/invoices"),
    ("GET", "/invoices"),
    ("GET", "/invoices/export.csv"),
    ("GET", f"/invoices/{MISSING_ID}"),
    ("PUT", f"/invoices/{MISSING_ID}"),
    ("DELETE", f"/invoices/{MISSING_ID}"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_every_route_refuses_a_missing_or_wrong_token(client: TestClient, method, path) -> None:
    assert client.request(method, path).status_code == 401
    wrong = {"Authorization": "Bearer " + "x" * 43}
    assert client.request(method, path, headers=wrong).status_code == 401


def test_the_route_table_is_protected_by_default(client: TestClient) -> None:
    """A route added later must not be open by accident: only /health and docs may be."""
    open_paths = {"/health"}
    for route in client.app.routes:
        path = getattr(route, "path", "")
        if path in open_paths or not path or path.startswith(("/docs", "/redoc", "/openapi")):
            continue
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
            url = re.sub(r"\{[^}]+\}", MISSING_ID, path)
            assert client.request(method, url).status_code == 401, (method, path)


def test_the_app_refuses_to_start_without_a_valid_api_token(monkeypatch) -> None:
    for bad in (None, "", "short"):
        if bad is None:
            monkeypatch.delenv("API_TOKEN")
        else:
            monkeypatch.setenv("API_TOKEN", bad)
        with pytest.raises(exc.APIConfigError), TestClient(create_app()):
            pass


def test_the_app_refuses_to_start_without_a_valid_encryption_key(monkeypatch) -> None:
    for bad in (None, "not-a-key"):
        if bad is None:
            monkeypatch.delenv("CACHE_ENCRYPTION_KEY")
        else:
            monkeypatch.setenv("CACHE_ENCRYPTION_KEY", bad)
        with pytest.raises(exc.StorageError), TestClient(create_app()):
            pass


def test_foreign_host_header_is_refused_dns_rebinding(client: TestClient) -> None:
    response = client.get("/health", headers={"Host": "evil.example"})
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"  # even this answer is hardened


def test_docs_and_openapi_are_not_published(client: TestClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_docs_can_be_enabled_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_DOCS", "1")
    with TestClient(create_app()) as docs_client:
        assert docs_client.get("/docs").status_code == 200


def test_no_cors_headers_are_ever_sent(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
    preflight = client.options(
        "/invoices",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in preflight.headers


# --- security headers on every kind of response ---
def test_security_headers_are_on_every_kind_of_response(client: TestClient, monkeypatch) -> None:
    seeded = _seed()
    responses = [
        client.get("/health"),  # 200
        client.get("/invoices"),  # 401
        client.get(f"/invoices/{MISSING_ID}", headers=AUTH),  # 404
        client.get("/invoices/not-a-uuid", headers=AUTH),  # 422
        client.get(f"/invoices/{seeded.id}", headers=AUTH),  # 200 with personal data
        _upload(client, PDF + b"0" * (3 * 1024 * 1024)),  # 413 from the middleware
        client.get("/nowhere", headers=AUTH),  # 404 from the router
    ]
    assert [r.status_code for r in responses] == [200, 401, 404, 422, 200, 413, 404]
    for response in responses:
        for name, value in SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, (response.status_code, name)
        assert "default-src 'none'" in response.headers["content-security-policy"]


def test_security_headers_are_on_unexpected_errors_too(monkeypatch) -> None:
    def boom(_path):
        raise RuntimeError("secret C:\\Users\\ibrahima\\data")

    monkeypatch.setattr(routes, "process_invoice", boom)
    with TestClient(create_app(), raise_server_exceptions=False) as quiet:
        response = _upload(quiet)
    assert response.status_code == 500
    assert response.json() == {"detail": "Erreur interne."}
    assert "ibrahima" not in response.text and "secret" not in response.text
    assert response.headers["cache-control"] == "no-store"


# --- the full life of an invoice ---
def test_full_lifecycle(
    client: TestClient, fake_gemini, sample_invoice_pdf: Path, upload_dir
) -> None:
    # upload: real OCR on the sample PDF, fake Gemini
    created = _upload(client, sample_invoice_pdf.read_bytes(), name="../../facture-orange.pdf")
    assert created.status_code == 201
    body = created.json()
    record_id = body["id"]
    assert body["status"] == "high" and body["invoice"]["supplier"] == "Orange SA"
    assert body["display_name"] == "facture-orange.pdf"  # basename only
    assert "pdf_hash" not in body and "pdf_hash" not in str(body)
    assert fake_gemini == [fake_gemini[0]] and fake_gemini[0].endswith(".pdf")
    assert _leftovers(upload_dir) == []  # the PDF was deleted right after processing

    # read
    assert client.get(f"/invoices/{record_id}", headers=AUTH).json() == body
    listed = client.get("/invoices", headers=AUTH).json()
    assert [row["id"] for row in listed] == [record_id]
    assert listed[0]["supplier"] == "Orange SA" and "invoice" not in listed[0]

    # correct: consistent figures stay reliable, inconsistent ones are flagged by the SERVER
    fixed = {**GOOD.model_dump(exclude={"extraction_confidence", "warnings"}), "supplier": "Orange"}
    ok = client.put(f"/invoices/{record_id}", json=fixed, headers=AUTH)
    assert ok.status_code == 200 and ok.json()["status"] == "high"
    assert ok.json()["expires_at"] == body["expires_at"]  # a correction never extends retention
    broken = client.put(f"/invoices/{record_id}", json={**fixed, "total_ttc": 999.0}, headers=AUTH)
    assert broken.json()["status"] == "low" and broken.json()["invoice"]["warnings"]

    # export
    export = client.get("/invoices/export.csv", params={"ids": [record_id]}, headers=AUTH)
    assert export.status_code == 200 and export.content.startswith("\ufeff".encode())
    assert b"Orange" in export.content

    # erase: record AND cache entry
    pdf_hash = cache.hash_pdf(sample_invoice_pdf)
    assert cache.get_cached(pdf_hash) is not None
    assert client.delete(f"/invoices/{record_id}", headers=AUTH).status_code == 204
    assert cache.get_cached(pdf_hash) is None
    assert client.get(f"/invoices/{record_id}", headers=AUTH).status_code == 404
    assert client.get("/invoices", headers=AUTH).json() == []


def test_uploading_the_same_pdf_twice_reuses_the_cache(
    client: TestClient, fake_gemini, sample_invoice_pdf: Path
) -> None:
    data = sample_invoice_pdf.read_bytes()
    assert _upload(client, data).status_code == 201
    assert _upload(client, data).status_code == 201
    assert len(fake_gemini) == 1  # the second extraction came from the encrypted cache
    assert len(client.get("/invoices", headers=AUTH).json()) == 2  # documented: two records


@pytest.mark.parametrize(
    ("data", "mime"),
    [(b"MZ\x90\x00 exe", "application/pdf"), (PDF, "text/html"), (b"", "application/pdf")],
)
def test_non_pdf_uploads_are_refused_and_nothing_is_stored(
    client: TestClient, upload_dir, data: bytes, mime: str
) -> None:
    response = _upload(client, data, mime=mime)
    assert response.status_code == 415
    assert _leftovers(upload_dir) == [] and client.get("/invoices", headers=AUTH).json() == []


def test_oversize_upload_is_refused_with_413(client: TestClient, upload_dir) -> None:
    assert _upload(client, PDF + b"0" * (3 * 1024 * 1024)).status_code == 413
    assert _leftovers(upload_dir) == []


def test_upload_without_a_file_is_a_422(client: TestClient) -> None:
    assert client.post("/invoices", headers=AUTH).status_code == 422


# --- errors are translated, never leaked, and the PDF never survives ---
@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (exc.PDFCorruptedError("C:\\secret\\x.pdf"), 422, "Le PDF est illisible ou corrompu."),
        (exc.PDFTooLargeError("x"), 413, "PDF trop volumineux ou trop complexe à analyser."),
        (
            exc.DailyQuotaExceededError("x"),
            429,
            "Quota d'analyse du jour atteint, réessayez demain.",
        ),
        (exc.LLMAuthError("x"), 503, "Service d'analyse indisponible."),
        (exc.ProviderTimeoutError("x"), 504, "Le service d'analyse ne répond pas, réessayez."),
        (exc.ExtractionFailedError("x"), 502, "L'analyse a échoué pour ce document."),
        (exc.StorageError("/data/invoiceai.db"), 500, "Erreur de stockage interne."),
    ],
)
def test_pipeline_errors_become_safe_http_errors(
    client: TestClient, monkeypatch, upload_dir, error, status, message
) -> None:
    def failing(_path):
        raise error

    monkeypatch.setattr(routes, "process_invoice", failing)
    response = _upload(client)
    assert response.status_code == status and response.json() == {"detail": message}
    assert "secret" not in response.text and "invoiceai.db" not in response.text
    assert _leftovers(upload_dir) == []  # deleted even though the extraction failed


def test_rate_limit_answers_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPLOAD_RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setattr(routes, "process_invoice", lambda _path: GOOD)
    with TestClient(create_app()) as limited:
        assert _upload(limited).status_code == 201
        assert _upload(limited).status_code == 201
        third = _upload(limited)
    assert third.status_code == 429 and 1 <= int(third.headers["retry-after"]) <= 60


def test_concurrency_limit_answers_503_with_retry_after(client: TestClient, upload_dir) -> None:
    client.app.state.concurrency = ConcurrencyLimiter(0)
    response = _upload(client)
    assert response.status_code == 503 and int(response.headers["retry-after"]) >= 1
    assert _leftovers(upload_dir) == []


# --- validation: 422 without echoing the input ---
def test_validation_errors_never_echo_what_was_sent(client: TestClient) -> None:
    secret = "SECRET-SEARCH-TERM-" + "x" * 100
    response = client.get("/invoices", params={"q": secret}, headers=AUTH)
    assert response.status_code == 422
    assert secret not in response.text and "input" not in response.json()["errors"][0]
    assert response.json()["detail"] == "Requête invalide."


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 501},
        {"offset": -1},
        {"status": "medium"},
        {"date_from": "not-a-date"},
        {"q": "x" * 101},
    ],
)
def test_list_parameters_are_bounded(client: TestClient, params: dict) -> None:
    assert client.get("/invoices", params=params, headers=AUTH).status_code == 422


@pytest.mark.parametrize(
    "bad_id", ["abc", "1; DROP TABLE invoices", "A" * 8 + "-0000-4000-8000-" + "0" * 12, "../x"]
)
def test_malformed_ids_are_a_422_before_any_lookup(client: TestClient, bad_id: str) -> None:
    for method in ("GET", "PUT", "DELETE"):
        assert client.request(method, f"/invoices/{bad_id}", headers=AUTH, json={}).status_code in (
            404,
            422,
        )
    assert client.get("/invoices/not-a-uuid", headers=AUTH).status_code == 422


def test_unknown_ids_are_a_404(client: TestClient) -> None:
    body = GOOD.model_dump(exclude={"extraction_confidence", "warnings"})
    assert client.get(f"/invoices/{MISSING_ID}", headers=AUTH).status_code == 404
    assert client.put(f"/invoices/{MISSING_ID}", json=body, headers=AUTH).status_code == 404
    assert client.delete(f"/invoices/{MISSING_ID}", headers=AUTH).status_code == 404


# --- PUT: mass assignment, bounds, sanitising ---
@pytest.mark.parametrize(
    "forbidden",
    [
        {"extraction_confidence": "high"},
        {"warnings": []},
        {"id": MISSING_ID},
        {"pdf_hash": "b" * 64},
        {"expires_at": "2099-01-01T00:00:00Z"},
        {"status": "high"},
    ],
)
def test_put_rejects_fields_a_client_must_not_set(client: TestClient, forbidden: dict) -> None:
    record = _seed()
    body = {**GOOD.model_dump(exclude={"extraction_confidence", "warnings"}), **forbidden}
    assert client.put(f"/invoices/{record.id}", json=body, headers=AUTH).status_code == 422


@pytest.mark.parametrize(
    "bad",
    [{"total_ttc": 1e12}, {"subtotal_ht": -1e12}, {"tva_rate": -1}, {"tva_rate": 101}]
    + [{"lines": [{"description": "x", "quantity": 1, "unit_price": 1, "total": 1}] * 201}],
)
def test_put_bounds_are_enforced(client: TestClient, bad: dict) -> None:
    record = _seed()
    body = {**GOOD.model_dump(exclude={"extraction_confidence", "warnings"}), **bad}
    assert client.put(f"/invoices/{record.id}", json=body, headers=AUTH).status_code == 422


def test_put_sanitises_text_and_a_client_cannot_lie_about_reliability(client: TestClient) -> None:
    record = _seed()
    body = {
        **GOOD.model_dump(exclude={"extraction_confidence", "warnings"}),
        "supplier": "Acme\u202e\x00" + "A" * 500,
        "total_ttc": 5.0,  # inconsistent on purpose
    }
    result = client.put(f"/invoices/{record.id}", json=body, headers=AUTH).json()
    assert (
        "\u202e" not in result["invoice"]["supplier"] and len(result["invoice"]["supplier"]) == 200
    )
    assert result["status"] == "low"  # the server decided, whatever the client would have liked


# --- retention ---
def test_expired_records_are_invisible_everywhere(client: TestClient) -> None:
    old = _seed(now=NOW - timedelta(days=40), pdf_hash="c" * 64)
    assert client.get(f"/invoices/{old.id}", headers=AUTH).status_code == 404
    assert client.get("/invoices", headers=AUTH).json() == []
    assert client.get("/invoices/export.csv", params={"ids": [old.id]}, headers=AUTH).content == (
        client.get("/invoices/export.csv", params={"ids": [MISSING_ID]}, headers=AUTH).content
    )


def test_startup_purges_expired_records_their_cache_entries_and_orphan_uploads(
    monkeypatch, upload_dir: Path
) -> None:
    import os
    import time

    old = _seed(now=NOW - timedelta(days=40), pdf_hash="d" * 64)
    fresh = _seed(pdf_hash="e" * 64)
    cache.store_cache("d" * 64, GOOD)
    cache.store_cache("e" * 64, GOOD)
    upload_dir.mkdir(parents=True, exist_ok=True)
    orphan, recent = upload_dir / "orphan.pdf", upload_dir / "recent.pdf"
    orphan.write_bytes(PDF)
    recent.write_bytes(PDF)
    os.utime(orphan, (time.time() - 7_200,) * 2)

    with TestClient(create_app()) as started:
        assert started.get(f"/invoices/{fresh.id}", headers=AUTH).status_code == 200
    assert cache.get_cached("d" * 64) is None and cache.get_cached("e" * 64) is not None
    assert not orphan.exists() and recent.exists()
    with session_scope() as session:
        assert InvoiceRepository(session).get(old.id, now=NOW - timedelta(days=39)) is None


# --- delete ---
def test_delete_erases_the_cache_entry_too(client: TestClient) -> None:
    record = _seed()
    cache.store_cache(HASH, GOOD)
    assert client.delete(f"/invoices/{record.id}", headers=AUTH).status_code == 204
    assert cache.get_cached(HASH) is None
    assert client.delete(f"/invoices/{record.id}", headers=AUTH).status_code == 404


# --- list filters ---
def test_list_search_and_filters(client: TestClient) -> None:
    _seed(GOOD, pdf_hash="1" * 64)
    _seed(GOOD.model_copy(update={"supplier": "EDF", "date": "2026-08-20"}), pdf_hash="2" * 64)
    _seed(GOOD.model_copy(update={"extraction_confidence": "low"}), pdf_hash="3" * 64)
    names = lambda **p: sorted(  # noqa: E731
        row["supplier"] for row in client.get("/invoices", params=p, headers=AUTH).json()
    )
    assert names(q="edf") == ["EDF"]
    assert names(status="low") == ["Orange SA"]
    assert names(date_to="2026-08-31") == ["EDF"]
    assert len(names(limit=2)) == 2 and len(names(offset=2)) == 1


# --- export ---
def test_export_response_is_a_safe_attachment(client: TestClient) -> None:
    record = _seed()
    response = client.get("/invoices/export.csv", params={"ids": [record.id]}, headers=AUTH)
    assert response.status_code == 200  # "export.csv" was not read as an id
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="invoices_2026-09-10_to_2026-09-10.csv"'
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    rows = response.content.decode("utf-8-sig").splitlines()
    assert rows[0].split(";")[:3] == ["Date", "N° facture", "Fournisseur"]
    assert rows[1].startswith("2026-09-10;F-2026-001;Orange SA;100,00;20,00;120,00")


def test_export_options(client: TestClient) -> None:
    record = _seed()
    ids = {"ids": [record.id, record.id, MISSING_ID]}  # duplicates and unknown ids are harmless
    lines = client.get("/invoices/export.csv", params={**ids, "kind": "lines"}, headers=AUTH)
    assert lines.headers["content-disposition"].startswith('attachment; filename="lines_')
    assert len(lines.content.decode("utf-8-sig").splitlines()) == 2  # header + 1 line
    intl = client.get("/invoices/export.csv", params={**ids, "locale": "intl"}, headers=AUTH)
    assert "100.00" in intl.text and ";" not in intl.text.splitlines()[0]
    cols = client.get(
        "/invoices/export.csv", params={**ids, "columns": ["supplier", "status"]}, headers=AUTH
    )
    assert cols.content.decode("utf-8-sig").splitlines() == [
        "Fournisseur;Fiabilité",
        "Orange SA;élevée",
    ]
    by_filter = client.get("/invoices/export.csv", params={"q": "orange"}, headers=AUTH)
    assert b"Orange SA" in by_filter.content


@pytest.mark.parametrize(
    "params",
    [
        {"columns": ["nope"]},
        {"columns": ["supplier", "__class__"]},
        {"kind": "everything"},
        {"locale": "de"},
        {"ids": ["not-a-uuid"]},
        {"ids": [MISSING_ID] * 201},
    ],
)
def test_export_parameters_are_bounded(client: TestClient, params: dict) -> None:
    assert client.get("/invoices/export.csv", params=params, headers=AUTH).status_code == 422


def test_a_hostile_supplier_cannot_plant_a_formula_through_the_api(client: TestClient) -> None:
    record = _seed()
    hostile = {
        **GOOD.model_dump(exclude={"extraction_confidence", "warnings"}),
        "supplier": "=cmd|' /C calc'!A0",
        "client": "@SUM(A1)",
        "invoice_number": "-2+3",
    }
    assert client.put(f"/invoices/{record.id}", json=hostile, headers=AUTH).status_code == 200
    columns = ["supplier", "client", "invoice_number"]
    csv = client.get(
        "/invoices/export.csv", params={"ids": [record.id], "columns": columns}, headers=AUTH
    ).content.decode("utf-8-sig")
    assert csv.splitlines()[1] == "'=cmd|' /C calc'!A0;'@SUM(A1);'-2+3"
    lines = client.get(
        "/invoices/export.csv", params={"ids": [record.id], "kind": "lines"}, headers=AUTH
    ).content.decode("utf-8-sig")
    assert "'=cmd" in lines and ";=cmd" not in lines


def test_export_file_name_never_contains_user_text(client: TestClient) -> None:
    record = _seed(GOOD.model_copy(update={"supplier": '"; evil=1; x="'}))
    response = client.get("/invoices/export.csv", params={"ids": [record.id]}, headers=AUTH)
    assert re.fullmatch(
        r'attachment; filename="invoices_\d{4}-\d{2}-\d{2}_to_\d{4}-\d{2}-\d{2}\.csv"',
        response.headers["content-disposition"],
    )


def test_the_key_used_at_startup_is_the_one_that_reads_the_data(monkeypatch) -> None:
    record = _seed()
    monkeypatch.setenv("CACHE_ENCRYPTION_KEY", Fernet.generate_key().decode())  # key changed
    with TestClient(create_app(), raise_server_exceptions=False) as rotated:
        # unreadable, never a crash and never someone else's data
        assert rotated.get("/invoices", headers=AUTH).json() == []
        assert rotated.get(f"/invoices/{record.id}", headers=AUTH).status_code == 500
