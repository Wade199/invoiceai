from __future__ import annotations

import json

import httpx
import pytest

from src.ui.api_client import ApiClient
from src.ui.config import UiSettings
from src.ui.errors import ApiError, ApiUnavailableError, UiConfigError

TOKEN = "c" * 43
RECORD_ID = "3f9a1c2e-7b4d-4e8a-9c31-5d2f0a6b8e14"
INVOICE_JSON = {
    "id": RECORD_ID,
    "created_at": "2026-09-21T12:00:00Z",
    "expires_at": "2026-10-21T12:00:00Z",
    "display_name": "facture.pdf",
    "status": "high",
    "invoice": {"supplier": "Orange SA", "total_ttc": 120.0, "lines": []},
}


def _client(handler) -> tuple[ApiClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.Client(
        base_url="http://127.0.0.1:8000",
        headers={"Authorization": f"Bearer {TOKEN}"},
        transport=httpx.MockTransport(recording),
    )
    return ApiClient(http), seen


def _json(status: int, body, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


# --- how errors are shown --------------------------------------------------------------------
def test_401_gives_a_configuration_hint_and_never_the_token() -> None:
    client, _ = _client(lambda r: _json(401, {"detail": "Authentification requise."}))
    with pytest.raises(ApiError) as info:
        client.get(RECORD_ID)
    assert info.value.status == 401 and "API_TOKEN" in str(info.value)
    assert TOKEN not in str(info.value)


def test_the_apis_fixed_message_is_passed_on_and_truncated() -> None:
    client, _ = _client(lambda r: _json(413, {"detail": "Fichier trop volumineux."}))
    with pytest.raises(ApiError) as info:
        client.upload("f.pdf", b"%PDF-")
    assert str(info.value) == "Fichier trop volumineux." and info.value.status == 413

    client, _ = _client(lambda r: _json(500, {"detail": "x" * 1000}))
    with pytest.raises(ApiError) as long_info:
        client.get(RECORD_ID)
    assert len(str(long_info.value)) == 300


def test_retry_after_is_kept() -> None:
    client, _ = _client(
        lambda r: _json(429, {"detail": "Trop de requêtes."}, {"Retry-After": "42"})
    )
    with pytest.raises(ApiError) as info:
        client.upload("f.pdf", b"%PDF-")
    assert info.value.retry_after == 42
    client, _ = _client(lambda r: _json(429, {"detail": "x"}, {"Retry-After": "soon"}))
    with pytest.raises(ApiError) as bad:
        client.upload("f.pdf", b"%PDF-")
    assert bad.value.retry_after is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(502, text="<html>Bad gateway at C:\\secret\\proxy.conf</html>"),
        httpx.Response(500, json={"no": "detail"}),
        httpx.Response(500, json={"detail": ["not", "a", "string"]}),
        httpx.Response(500, json=["a list"]),
        httpx.Response(500, content=b"\xff\xfe binary"),
    ],
)
def test_a_body_that_is_not_the_apis_own_error_is_never_shown(response: httpx.Response) -> None:
    client, _ = _client(lambda r: response)
    with pytest.raises(ApiError) as info:
        client.get(RECORD_ID)
    assert str(info.value) == "L'API a renvoyé une erreur inattendue."
    assert "secret" not in str(info.value) and "html" not in str(info.value).lower()


def test_unreachable_api_and_timeouts_have_clear_messages() -> None:
    def down(request):
        raise httpx.ConnectError("[WinError 10061] refused", request=request)

    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    client, _ = _client(down)
    with pytest.raises(ApiUnavailableError, match="make api"):
        client.check()
    client, _ = _client(slow)
    with pytest.raises(ApiUnavailableError, match="ne répond pas"):
        client.upload("f.pdf", b"%PDF-")


def test_a_successful_answer_that_is_not_what_we_expect_is_an_error() -> None:
    for body in ("not json", {"id": "x"}, [1, 2]):
        client, _ = _client(
            lambda r, b=body: (
                httpx.Response(200, json=b) if b != "not json" else httpx.Response(200, text=b)
            )
        )
        with pytest.raises(ApiError) as info:
            client.get(RECORD_ID)
        assert info.value.status == 502
    client, _ = _client(lambda r: _json(200, {"not": "a list"}))
    with pytest.raises(ApiError):
        client.list_invoices()


def test_health_that_is_not_ok_is_unavailable() -> None:
    client, _ = _client(lambda r: _json(200, {"status": "starting"}))
    with pytest.raises(ApiUnavailableError):
        client.check()
    client, _ = _client(lambda r: _json(200, {"status": "ok"}))
    client.check()


# --- what is sent ----------------------------------------------------------------------------
def test_upload_sends_the_pdf_as_multipart_with_a_long_timeout() -> None:
    client, seen = _client(lambda r: _json(201, INVOICE_JSON))
    result = client.upload("../../facture.pdf", b"%PDF-1.4 data")
    request = seen[0]
    assert request.method == "POST" and request.url.path == "/invoices"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert b"%PDF-1.4 data" in request.read() and b"application/pdf" in request.read()
    assert request.extensions["timeout"]["read"] == 180.0  # extraction takes 7-33 s
    assert result.id == RECORD_ID and result.invoice.supplier == "Orange SA"


def test_list_sends_only_the_filters_that_were_given() -> None:
    from datetime import date

    client, seen = _client(lambda r: _json(200, []))
    client.list_invoices()
    assert dict(seen[0].url.params) == {"limit": "100", "offset": "0"}
    client.list_invoices(query="orange", date_from=date(2026, 8, 1), status="low", limit=5)
    assert dict(seen[1].url.params) == {
        "q": "orange",
        "date_from": "2026-08-01",
        "status": "low",
        "limit": "5",
        "offset": "0",
    }


def test_update_and_delete_use_the_right_verbs_and_paths() -> None:
    client, seen = _client(
        lambda r: _json(200, INVOICE_JSON) if r.method == "PUT" else httpx.Response(204)
    )
    client.update(RECORD_ID, {"supplier": "Orange"})
    client.delete(RECORD_ID)
    assert [(r.method, r.url.path) for r in seen] == [
        ("PUT", f"/invoices/{RECORD_ID}"),
        ("DELETE", f"/invoices/{RECORD_ID}"),
    ]
    assert json.loads(seen[0].content) == {"supplier": "Orange"}


@pytest.mark.parametrize(
    "bad_id", ["../health", "..%2f", "abc", "", RECORD_ID.upper(), RECORD_ID + "/x", "x?y=1"]
)
def test_ids_are_validated_before_they_can_alter_the_url(bad_id: str) -> None:
    client, seen = _client(lambda r: _json(200, INVOICE_JSON))
    for call in (
        client.get,
        client.delete,
        lambda i: client.update(i, {}),
        lambda i: client.export_csv(ids=[i]),
    ):
        with pytest.raises(ValueError):
            call(bad_id)
    assert seen == []  # nothing was sent


def test_export_passes_the_selection_and_reads_a_safe_file_name() -> None:
    csv_response = httpx.Response(
        200,
        content=b"\xef\xbb\xbfa;b\r\n",
        headers={
            "content-disposition": 'attachment; filename="invoices_2026-08-01_to_2026-09-18.csv"'
        },
    )
    client, seen = _client(lambda r: csv_response)
    result = client.export_csv(
        ids=[RECORD_ID], columns=["supplier", "status"], kind="lines", locale="intl"
    )
    assert result.filename == "invoices_2026-08-01_to_2026-09-18.csv"
    assert result.content == b"\xef\xbb\xbfa;b\r\n"
    params = seen[0].url.params
    assert params.get_list("ids") == [RECORD_ID] and params.get_list("columns") == [
        "supplier",
        "status",
    ]
    assert params["kind"] == "lines" and params["locale"] == "intl"


@pytest.mark.parametrize(
    "header",
    [
        'attachment; filename="../../evil.exe"',
        'attachment; filename="report.csv.exe"',
        'attachment; filename="a b.csv"',
        "attachment",
        "",
        'attachment; filename="' + "a" * 200 + '.csv"',
    ],
)
def test_a_hostile_file_name_in_the_header_is_replaced(header: str) -> None:
    client, _ = _client(
        lambda r: httpx.Response(200, content=b"x", headers={"content-disposition": header})
    )
    assert client.export_csv().filename == "export.csv"


# --- the safeguards for the token ---------------------------------------------------------------
def test_from_settings_builds_a_client_that_cannot_leak_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.evil.example:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.evil.example:3128")
    client = ApiClient.from_settings(UiSettings("http://127.0.0.1:8000", TOKEN))
    http = client._http
    assert http.follow_redirects is False  # a redirect must not carry the token elsewhere
    assert http._mounts == {}  # environment proxies are ignored
    assert str(http.base_url) == "http://127.0.0.1:8000"
    assert http.headers["authorization"] == f"Bearer {TOKEN}"


def test_from_settings_refuses_an_unsafe_address() -> None:
    with pytest.raises(UiConfigError):
        ApiClient.from_settings(UiSettings("http://evil.example", TOKEN))


def test_a_redirect_is_reported_as_an_error_and_never_followed() -> None:
    requests: list[httpx.Request] = []

    def redirecting(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://evil.example/steal"})

    http = httpx.Client(
        base_url="http://127.0.0.1:8000",
        headers={"Authorization": f"Bearer {TOKEN}"},
        transport=httpx.MockTransport(redirecting),
        follow_redirects=False,
        trust_env=False,
    )
    with pytest.raises(ApiError):
        ApiClient(http).list_invoices()
    assert len(requests) == 1 and all(r.url.host == "127.0.0.1" for r in requests)
