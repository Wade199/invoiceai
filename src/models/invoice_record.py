from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, LargeBinary, String
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

SCHEMA_VERSION = 1  # version of the encrypted payload's content


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on SQLite, which has no time zone support.

    Refuses naive datetimes on the way in (a naive value is ambiguous), and gives back
    aware UTC datetimes on the way out, so comparisons never mix the two.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime: use timezone-aware UTC datetimes")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


class Base(DeclarativeBase):
    pass


class InvoiceRecord(Base):
    """One processed invoice.

    Everything personal (supplier, client, amounts, lines, file name) lives in the
    encrypted `payload`. The plain columns hold nothing readable about the customer: an id,
    dates, a reliability flag and the PDF's hash (needed to erase the cache entry too).
    """

    __tablename__ = "invoices"
    __table_args__ = (CheckConstraint("status IN ('high', 'low')", name="ck_invoices_status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    pdf_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=SCHEMA_VERSION)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
