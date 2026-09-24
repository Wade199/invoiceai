from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from pydantic import StringConstraints

from src.api.schemas import InvoiceOut, InvoiceSummary, InvoiceUpdate
from src.api.security import client_key, require_token
from src.api.upload import StoredUpload, delete_upload, save_upload
from src.core.database import session_scope
from src.services import export
from src.services.cache import hash_pdf
from src.services.pipeline import process_invoice
from src.services.repository import InvoiceRepository, StoredInvoice
from src.services.validate_invoice import validate_invoice

# Only canonical lowercase UUIDs can be one of our ids: anything else is a 422 before any lookup.
_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
RecordId = Annotated[str, Path(pattern=_UUID_PATTERN)]
RecordIdQuery = Annotated[str, StringConstraints(pattern=_UUID_PATTERN)]

MAX_EXPORT_IDS = 200
MAX_EXPORT_ROWS = 500
_NOT_FOUND = "Facture introuvable."

# Every route of this router needs the bearer token: a route added later is protected by default.
router = APIRouter(dependencies=[Depends(require_token)])


def _extract_and_store(upload: StoredUpload) -> StoredInvoice:
    """Blocking work (OCR process, Gemini call, database): runs in a worker thread."""
    pdf_hash = hash_pdf(upload.path)
    invoice = process_invoice(upload.path, upload.mime)
    with session_scope() as session:
        return InvoiceRepository(session).create(
            invoice, pdf_hash=pdf_hash, display_name=upload.display_name
        )


@router.post("/invoices", status_code=201, response_model=InvoiceOut)
async def create_invoice(request: Request, file: Annotated[UploadFile, File()]) -> InvoiceOut:
    """Upload a PDF, JPEG or PNG; extract, validate, store the result. The file is not kept."""
    state = request.app.state
    state.rate_limiter.check(client_key(request))
    with state.concurrency.slot():
        upload = await save_upload(file)
        try:
            stored = await run_in_threadpool(_extract_and_store, upload)
        finally:
            delete_upload(upload.path)  # personal data: gone as soon as it was processed
    return InvoiceOut.from_stored(stored)


@router.get("/invoices", response_model=list[InvoiceSummary])
def list_invoices(
    q: Annotated[str | None, Query(max_length=100)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: Literal["high", "low"] | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_EXPORT_ROWS)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[InvoiceSummary]:
    with session_scope() as session:
        found = InvoiceRepository(session).list(
            query=q,
            date_from=date_from,
            date_to=date_to,
            status=status,
            limit=limit,
            offset=offset,
        )
    return [InvoiceSummary.from_stored(item) for item in found]


# Declared BEFORE /invoices/{record_id}: "export.csv" must not be read as an id.
@router.get("/invoices/export.csv")
def export_csv(
    ids: Annotated[list[RecordIdQuery] | None, Query(max_length=MAX_EXPORT_IDS)] = None,
    kind: Literal["invoices", "lines"] = "invoices",
    columns: Annotated[list[str] | None, Query(max_length=20)] = None,
    locale: Literal["fr", "intl"] = "fr",
    q: Annotated[str | None, Query(max_length=100)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: Literal["high", "low"] | None = None,
) -> Response:
    """CSV of the selected invoices (`ids`) or of everything matching the filters."""
    if columns and any(name not in export.INVOICE_COLUMNS for name in columns):
        raise HTTPException(status_code=422, detail="Colonne d'export inconnue.")

    with session_scope() as session:
        repository = InvoiceRepository(session)
        if ids:
            selected = [repository.get(record_id) for record_id in dict.fromkeys(ids)]
            invoices = [item for item in selected if item is not None]
        else:
            invoices = repository.list(
                query=q,
                date_from=date_from,
                date_to=date_to,
                status=status,
                limit=MAX_EXPORT_ROWS,
            )

    if kind == "lines":
        content = export.lines_csv(invoices, locale=locale)
    else:
        options = {"columns": columns} if columns else {}
        content = export.invoices_csv(invoices, locale=locale, **options)
    # The file name is built from dates only: no user text ever reaches this header.
    filename = export.suggested_filename(invoices, kind)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/invoices/{record_id}", response_model=InvoiceOut)
def get_invoice(record_id: RecordId) -> InvoiceOut:
    with session_scope() as session:
        stored = InvoiceRepository(session).get(record_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return InvoiceOut.from_stored(stored)


@router.put("/invoices/{record_id}", response_model=InvoiceOut)
def update_invoice(record_id: RecordId, body: InvoiceUpdate) -> InvoiceOut:
    """Save the user's corrections. Reliability and warnings are recomputed by the server."""
    invoice = validate_invoice(body.to_invoice())
    with session_scope() as session:
        stored = InvoiceRepository(session).update(record_id, invoice)
    if stored is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return InvoiceOut.from_stored(stored)


@router.delete("/invoices/{record_id}", status_code=204)
def delete_invoice(record_id: RecordId) -> Response:
    """GDPR erasure: the record AND its cache entry."""
    with session_scope() as session:
        deleted = InvoiceRepository(session).delete(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return Response(status_code=204)
