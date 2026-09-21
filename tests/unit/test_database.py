from __future__ import annotations

import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text

from src.core.database import dispose_engines, get_engine, session_scope
from src.core.exceptions import StorageError
from src.models.invoice_record import InvoiceRecord
from src.models.schemas import ExtractedInvoice
from src.services.repository import InvoiceRepository

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _record(**overrides) -> InvoiceRecord:
    values = {
        "id": "3f9a1c2e-7b4d-4e8a-9c31-5d2f0a6b8e14",
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=30),
        "status": "high",
        "pdf_hash": "a" * 64,
        "schema_version": 1,
        "payload": b"opaque",
    }
    values.update(overrides)
    return InvoiceRecord(**values)


def test_tables_are_created_on_first_use(database_url: str) -> None:
    get_engine()
    path = Path(database_url.removeprefix("sqlite:///"))
    with sqlite3.connect(path) as connection:
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master")]
    assert "invoices" in tables


def test_parent_directory_is_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nested = tmp_path / "a" / "b" / "invoiceai.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{nested.as_posix()}")
    get_engine()
    assert nested.exists()


def test_secure_delete_is_enabled_on_every_connection() -> None:
    with session_scope() as session:
        assert session.execute(text("PRAGMA secure_delete")).scalar() == 1


def test_engine_is_cached_per_url_and_disposed_on_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = get_engine()
    assert get_engine() is first
    other = get_engine(f"sqlite:///{(tmp_path / 'other.db').as_posix()}")
    assert other is not first
    dispose_engines()
    assert get_engine() is not first  # a fresh engine after dispose


def test_unopenable_database_raises_storage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(blocker / 'x.db').as_posix()}")
    with pytest.raises(StorageError):
        get_engine()


def test_a_failed_block_is_rolled_back() -> None:
    with pytest.raises(RuntimeError), session_scope() as session:
        session.add(_record())
        session.flush()
        raise RuntimeError("boom")
    with session_scope() as session:
        assert session.scalars(select(InvoiceRecord)).all() == []


def test_a_successful_block_is_committed() -> None:
    with session_scope() as session:
        session.add(_record())
    with session_scope() as session:
        assert len(session.scalars(select(InvoiceRecord)).all()) == 1


def test_status_check_constraint_rejects_unknown_values() -> None:
    with pytest.raises(StorageError), session_scope() as session:
        session.add(_record(status="medium"))


def test_primary_key_is_unique() -> None:
    with session_scope() as session:
        session.add(_record())
    with pytest.raises(StorageError), session_scope() as session:
        session.add(_record())


def test_sql_injection_string_is_stored_as_data_not_executed() -> None:
    hostile = "x'); DROP TABLE invoices; --"
    with session_scope() as session:
        stored = InvoiceRepository(session).create(
            ExtractedInvoice(supplier=hostile), pdf_hash="c" * 64, display_name=hostile, now=NOW
        )
    with session_scope() as session:
        assert InvoiceRepository(session).get(stored.id, now=NOW).invoice.supplier == hostile
        assert session.scalars(select(InvoiceRecord)).all()  # the table is still there


# --- UTCDateTime ---
def test_datetimes_come_back_timezone_aware_in_utc() -> None:
    paris = timezone(timedelta(hours=2))
    with session_scope() as session:
        session.add(_record(created_at=datetime(2026, 9, 21, 14, 0, tzinfo=paris)))
    with session_scope() as session:
        created = session.scalars(select(InvoiceRecord)).one().created_at
    assert created == datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    assert created.utcoffset() == timedelta(0)


def test_naive_datetimes_are_refused() -> None:
    with pytest.raises(StorageError), session_scope() as session:
        session.add(_record(created_at=datetime(2026, 9, 21, 12, 0)))  # noqa: DTZ001


# --- concurrency and files ---
def test_concurrent_requests_do_not_corrupt_or_lock_the_database() -> None:
    def work(index: int) -> str:
        with session_scope() as session:
            stored = InvoiceRepository(session).create(
                ExtractedInvoice(supplier=f"Fournisseur {index}"),
                pdf_hash=f"{index:064x}",
                display_name=f"f{index}.pdf",
                now=NOW,
            )
        with session_scope() as session:
            fetched = InvoiceRepository(session).get(stored.id, now=NOW)
        assert fetched.invoice.supplier == f"Fournisseur {index}"
        return stored.id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(work, range(40)))
    assert len(set(ids)) == 40
    with session_scope() as session:
        assert len(InvoiceRepository(session).list(limit=500, now=NOW)) == 40


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes do not apply on Windows")
def test_database_file_is_owner_only(database_url: str) -> None:
    get_engine()
    path = Path(database_url.removeprefix("sqlite:///"))
    assert os.stat(path).st_mode & 0o777 == 0o600
