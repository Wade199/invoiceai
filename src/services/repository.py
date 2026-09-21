from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.core.crypto import get_cipher
from src.core.env import get_int_env
from src.core.exceptions import StorageError
from src.models.invoice_record import SCHEMA_VERSION, InvoiceRecord
from src.models.schemas import ExtractedInvoice
from src.services.cache import delete_cached

logger = logging.getLogger(__name__)

_DEFAULT_RETENTION_DAYS = 30
_MAX_LIST_LIMIT = 500
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_VALID_STATUSES = ("high", "low")


@dataclass(frozen=True)
class StoredInvoice:
    """A decrypted invoice record.

    Attributes:
        id: UUID of the record.
        created_at: When it was processed (UTC). Retention starts here.
        expires_at: When it will be erased (UTC).
        invoice: The extracted (and possibly user-corrected) data.
        display_name: The client's file name, sanitised (display only).
        pdf_hash: SHA-256 of the source PDF (links the record to its cache entry).
    """

    id: str
    created_at: datetime
    expires_at: datetime
    invoice: ExtractedInvoice
    display_name: str
    pdf_hash: str

    @property
    def effective_date(self) -> date:
        """The invoice's own date when it is a valid ISO date, else the processing date."""
        try:
            return date.fromisoformat(self.invoice.date or "")
        except ValueError:
            return self.created_at.date()


def _now() -> datetime:
    return datetime.now(UTC)


def _retention() -> timedelta:
    return timedelta(days=get_int_env("DEFAULT_RETENTION_DAYS", _DEFAULT_RETENTION_DAYS))


def _valid_id(record_id: str) -> bool:
    """Only canonical lowercase UUIDs: anything else cannot be one of our ids."""
    try:
        return str(uuid.UUID(record_id)) == record_id
    except (ValueError, AttributeError, TypeError):
        return False


def _seal(cipher: Fernet, record_id: str, invoice: ExtractedInvoice, display_name: str) -> bytes:
    payload = {
        "id": record_id,  # bound to the row: a payload copied onto another row is refused
        "display_name": display_name,
        "invoice": invoice.model_dump(mode="json"),
    }
    return cipher.encrypt(json.dumps(payload).encode("utf-8"))


def _open(cipher: Fernet, record: InvoiceRecord) -> StoredInvoice:
    """Decrypt and validate a row.

    Raises:
        StorageError: If the payload is tampered, encrypted with another key, bound to
            another row, or does not match the schema.
    """
    try:
        payload = json.loads(cipher.decrypt(record.payload))
        if payload["id"] != record.id:
            raise StorageError("Record payload belongs to another record")
        return StoredInvoice(
            id=record.id,
            created_at=record.created_at,
            expires_at=record.expires_at,
            invoice=ExtractedInvoice.model_validate(payload["invoice"]),
            display_name=str(payload["display_name"]),
            pdf_hash=record.pdf_hash,
        )
    except InvalidToken as exc:
        raise StorageError("Record cannot be decrypted (tampered or wrong key)") from exc
    except (ValueError, KeyError, TypeError, ValidationError) as exc:
        raise StorageError("Record content is unreadable or obsolete") from exc


class InvoiceRepository:
    """Access to stored invoices. One instance per request / unit of work.

    Retention is enforced on read: an expired record is treated as absent even before
    `purge_expired()` has physically removed it.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- create / read ------------------------------------------------------------------
    def create(
        self,
        invoice: ExtractedInvoice,
        *,
        pdf_hash: str,
        display_name: str,
        now: datetime | None = None,
    ) -> StoredInvoice:
        """Store a new invoice, encrypted, with a fresh id and an expiry date.

        Raises:
            ValueError: If `pdf_hash` is not a SHA-256 hex digest.
            StorageError: If the key is missing/invalid.
        """
        if not _SHA256_HEX.fullmatch(pdf_hash):
            raise ValueError("pdf_hash must be a SHA-256 hex digest")
        created = now or _now()
        record = InvoiceRecord(
            id=str(uuid.uuid4()),
            created_at=created,
            expires_at=created + _retention(),
            status=invoice.extraction_confidence,
            pdf_hash=pdf_hash,
            schema_version=SCHEMA_VERSION,
            payload=b"",
        )
        record.payload = _seal(get_cipher(), record.id, invoice, display_name)
        self._session.add(record)
        self._session.flush()
        return _open(get_cipher(), record)

    def get(self, record_id: str, *, now: datetime | None = None) -> StoredInvoice | None:
        """Return one invoice, or None if unknown, malformed id or expired.

        Raises:
            StorageError: If the record exists but cannot be decrypted / validated.
        """
        if not _valid_id(record_id):
            return None
        record = self._session.get(InvoiceRecord, record_id)
        if record is None or record.expires_at <= (now or _now()):
            return None
        return _open(get_cipher(), record)

    def list(
        self,
        *,
        query: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        now: datetime | None = None,
    ) -> list[StoredInvoice]:
        """List non-expired invoices, newest first, filtered in memory after decryption.

        `query` is a case-insensitive substring searched in supplier, client, invoice
        number and file name. Dates filter on the invoice date (fallback: processing date),
        bounds included. Unreadable records are skipped with a warning.

        Raises:
            ValueError: If `status`, `limit` or `offset` is out of range.
        """
        if status is not None and status not in _VALID_STATUSES:
            raise ValueError("status must be 'high' or 'low'")
        if not 1 <= limit <= _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        statement = (
            select(InvoiceRecord)
            .where(InvoiceRecord.expires_at > (now or _now()))
            .order_by(InvoiceRecord.created_at.desc(), InvoiceRecord.id)
        )
        if status is not None:
            statement = statement.where(InvoiceRecord.status == status)

        cipher = get_cipher()
        needle = query.strip().casefold() if query else ""
        matches: list[StoredInvoice] = []
        for record in self._session.scalars(statement):
            try:
                stored = _open(cipher, record)
            except StorageError:
                logger.warning("Skipping unreadable record %s", record.id)
                continue
            if needle and needle not in _searchable_text(stored):
                continue
            if date_from and stored.effective_date < date_from:
                continue
            if date_to and stored.effective_date > date_to:
                continue
            matches.append(stored)
        return matches[offset : offset + limit]

    # --- update / delete ----------------------------------------------------------------
    def update(
        self, record_id: str, invoice: ExtractedInvoice, *, now: datetime | None = None
    ) -> StoredInvoice | None:
        """Replace an invoice's content (user corrections). Retention is NOT extended.

        Returns:
            The updated record, or None if unknown / malformed id / expired.
        """
        current = self.get(record_id, now=now)
        if current is None:
            return None
        record = self._session.get(InvoiceRecord, record_id)
        record.status = invoice.extraction_confidence
        record.payload = _seal(get_cipher(), record.id, invoice, current.display_name)
        self._session.flush()
        return _open(get_cipher(), record)

    def delete(self, record_id: str) -> bool:
        """Erase an invoice for good: its cache entry first, then the row (GDPR erasure).

        The cache goes first: if that fails the caller can retry, whereas the opposite order
        could leave a cached copy nobody knows about. An expired-but-unpurged row can still
        be erased explicitly.

        Returns:
            True if a record was erased, False if the id is unknown.

        Raises:
            StorageError: If the cache entry cannot be erased (nothing else is touched).
        """
        if not _valid_id(record_id):
            return False
        record = self._session.get(InvoiceRecord, record_id)
        if record is None:
            return False
        _erase_cache(record.pdf_hash)
        self._session.delete(record)
        self._session.flush()
        return True

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Erase every expired record and its cache entry (GDPR retention). Run at startup.

        Works from the plain columns only, so it also removes records that can no longer be
        decrypted (lost key, tampering).

        Returns:
            Number of records erased.
        """
        cutoff = now or _now()
        expired = self._session.execute(
            select(InvoiceRecord.id, InvoiceRecord.pdf_hash).where(
                InvoiceRecord.expires_at <= cutoff
            )
        ).all()
        for _record_id, pdf_hash in expired:
            _erase_cache(pdf_hash)
        if expired:
            self._session.execute(
                delete(InvoiceRecord).where(InvoiceRecord.id.in_([row[0] for row in expired]))
            )
            self._session.flush()
        return len(expired)


def _erase_cache(pdf_hash: str) -> None:
    """Erase the cache entry linked to a record.

    The hash comes from a plain column that someone with file access could have altered:
    an invalid one is never turned into a path (delete_cached refuses it) and must not
    block erasing the record itself.
    """
    try:
        delete_cached(pdf_hash)
    except ValueError:
        logger.warning("Record holds an invalid PDF hash: no cache entry to erase")


def _searchable_text(stored: StoredInvoice) -> str:
    invoice = stored.invoice
    parts = (invoice.supplier, invoice.client, invoice.invoice_number, stored.display_name)
    return " ".join(part for part in parts if part).casefold()
