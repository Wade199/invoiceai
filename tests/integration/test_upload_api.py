"""The 13a security layer wired together in a small FastAPI app (the real routes are 13b).

Uses the real middleware, token dependency, limiters and upload code over HTTP (Starlette's
test client, real multipart parsing). Only the extraction itself is replaced by a stub.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.api import security, upload
from src.api.middleware import MULTIPART_MARGIN_BYTES, BodySizeLimitMiddleware
from src.core.exceptions import InvoiceAIError, PDFCorruptedError

pytestmark = pytest.mark.integration

TOKEN = "k" * 43
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def _build_app(
    *,
    rate_per_minute: int = 100,
    concurrency: int = 2,
    fail_with: Exception | None = None,
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        BodySizeLimitMiddleware, max_bytes=upload.max_upload_bytes() + MULTIPART_MARGIN_BYTES
    )
    rate_limiter = security.SlidingWindowRateLimiter(rate_per_minute, 60)
    concurrency_limiter = security.ConcurrencyLimiter(concurrency)

    @app.exception_handler(InvoiceAIError)
    async def _handle(_request: Request, error: InvoiceAIError) -> JSONResponse:
        info = security.to_http_error(error)
        headers = {"Retry-After": str(info.retry_after)} if info.retry_after else {}
        return JSONResponse({"detail": info.message}, info.status, headers)

    @app.post("/upload", dependencies=[Depends(security.require_token)])
    async def receive(request: Request, file: UploadFile) -> dict:
        rate_limiter.check(security.client_key(request))
        with concurrency_limiter.slot():
            stored = await upload.save_upload(file)
            try:
                if fail_with is not None:
                    raise fail_with
                return {"name": stored.display_name, "size": stored.size}
            finally:
                upload.delete_upload(stored.path)

    return app


@pytest.fixture(autouse=True)
def _config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", TOKEN)
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")


def _client(**kwargs) -> TestClient:
    return TestClient(_build_app(**kwargs))


def _post(client: TestClient, data: bytes = PDF, *, name="f.pdf", mime="application/pdf", **kw):
    return client.post("/upload", files={"file": (name, data, mime)}, headers=AUTH, **kw)


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


# --- happy path and cleanup ---
def test_valid_upload_succeeds_and_the_file_is_deleted_afterwards(upload_dir: Path) -> None:
    response = _post(_client())
    assert response.status_code == 200
    assert response.json() == {"name": "f.pdf", "size": len(PDF)}
    assert _leftovers(upload_dir) == []


def test_real_sample_invoice_goes_through(sample_invoice_pdf: Path) -> None:
    response = _post(_client(), sample_invoice_pdf.read_bytes(), name="sample_invoice.pdf")
    assert response.status_code == 200


def test_path_traversal_in_the_client_file_name_is_harmless(
    upload_dir: Path, tmp_path: Path
) -> None:
    response = _post(_client(), name="../../../evil.pdf")
    assert response.status_code == 200
    assert response.json()["name"] == "evil.pdf"
    assert not (tmp_path / "evil.pdf").exists() and not (tmp_path.parent / "evil.pdf").exists()
    assert _leftovers(upload_dir) == []


# --- authentication happens before anything is stored ---
def test_missing_token_is_refused_and_nothing_is_stored(upload_dir: Path) -> None:
    response = _client().post("/upload", files={"file": ("f.pdf", PDF, "application/pdf")})
    assert response.status_code == 401
    assert not upload_dir.exists()


def test_wrong_token_is_refused(upload_dir: Path) -> None:
    response = _client().post(
        "/upload",
        files={"file": ("f.pdf", PDF, "application/pdf")},
        headers={"Authorization": "Bearer " + "z" * 43},
    )
    assert response.status_code == 401
    assert not upload_dir.exists()


# --- size limits: the middleware stops the body BEFORE the endpoint runs ---
def test_oversize_body_with_content_length_is_refused_by_the_middleware(upload_dir: Path) -> None:
    response = _post(_client(), PDF + b"0" * (3 * 1024 * 1024))
    assert response.status_code == 413
    assert response.json() == {"detail": "Fichier trop volumineux."}
    assert not upload_dir.exists()  # the endpoint never ran


def test_oversize_body_without_content_length_is_cut_while_streaming(upload_dir: Path) -> None:
    """Chunked transfer: no Content-Length to check, the bytes themselves are counted."""
    boundary = "xBOUNDARYx"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="f.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    chunk = b"%PDF-" + b"0" * 65_531  # 64 KiB

    def body() -> Iterator[bytes]:
        yield head
        for _ in range(200):  # 12.5 MiB, sent without a Content-Length
            yield chunk
        yield tail

    response = _client().post(
        "/upload",
        content=body(),
        headers={**AUTH, "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert response.status_code == 413
    assert not upload_dir.exists()


def test_file_over_the_limit_but_inside_the_margin_is_refused_by_save_upload(
    upload_dir: Path,
) -> None:
    """Second layer: the body fits the middleware margin, the file itself is too big."""
    response = _post(_client(), PDF + b"0" * (1024 * 1024))
    assert response.status_code == 413
    assert _leftovers(upload_dir) == []


# --- type checks ---
@pytest.mark.parametrize(
    ("data", "mime", "name"),
    [
        (b"MZ\x90\x00 executable", "application/pdf", "invoice.pdf"),  # pdf name, exe bytes
        (PDF, "application/x-msdownload", "invoice.pdf"),  # good bytes, bad MIME
        (b"<html></html>", "text/html", "invoice.pdf"),
        (b"", "application/pdf", "empty.pdf"),
    ],
)
def test_non_pdf_uploads_are_refused(data: bytes, mime: str, name: str, upload_dir: Path) -> None:
    response = _post(_client(), data, name=name, mime=mime)
    assert response.status_code == 415
    assert _leftovers(upload_dir) == []


# --- limits ---
def test_rate_limit_returns_429_with_retry_after() -> None:
    client = _client(rate_per_minute=2)
    assert _post(client).status_code == 200
    assert _post(client).status_code == 200
    third = _post(client)
    assert third.status_code == 429
    assert 1 <= int(third.headers["retry-after"]) <= 60


def test_concurrency_limit_returns_503_with_retry_after(upload_dir: Path) -> None:
    response = _post(_client(concurrency=0))
    assert response.status_code == 503
    assert int(response.headers["retry-after"]) >= 1
    assert _leftovers(upload_dir) == []


# --- errors: safe message, file deleted ---
def test_processing_error_gives_a_safe_message_and_deletes_the_file(
    upload_dir: Path,
) -> None:
    secret_path = r"C:\Users\ibrahima\projets\data\uploads\3f9a.pdf"
    response = _post(_client(fail_with=PDFCorruptedError(secret_path)))
    assert response.status_code == 422
    assert response.json() == {"detail": "Le PDF est illisible ou corrompu."}
    assert "ibrahima" not in response.text and "uploads" not in response.text
    assert _leftovers(upload_dir) == []
