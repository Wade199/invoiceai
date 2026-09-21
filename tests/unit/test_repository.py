from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from src.core.database import session_scope
from src.core.exceptions import StorageError
from src.models.schemas import ExtractedInvoice, InvoiceLineItem
from src.services import cache, repository
from src.services.repository import InvoiceRepository

HASH_A, HASH_B = "a" * 64, "b" * 64
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _invoice(**overrides) -> ExtractedInvoice:
    data = {
        "invoice_number": "F-2026-001",
        "date": "2026-09-10",
        "supplier": "Orange SA",
        "client": "Dupont SARL",
        "lines": [
            InvoiceLineItem(description="Forfait", quantity=1, unit_price=100.0, total=100.0)
        ],
        "subtotal_ht": 100.0,
        "tva_rate": 0.2,
        "total_ttc": 120.0,
    }
    data.update(overrides)
    return ExtractedInvoice(**data)


def _db_path(database_url: str) -> Path:
    return Path(database_url.removeprefix("sqlite:///"))


def _make(session, invoice=None, *, pdf_hash=HASH_A, name="facture.pdf", now=NOW):
    return InvoiceRepository(session).create(
        invoice or _invoice(), pdf_hash=pdf_hash, display_name=name, now=now
    )


# --- create / get ---
def test_create_then_get_roundtrip() -> None:
    with session_scope() as session:
        created = _make(session)
        fetched = InvoiceRepository(session).get(created.id, now=NOW)
    assert fetched == created
    assert fetched.invoice == _invoice()
    assert fetched.display_name == "facture.pdf" and fetched.pdf_hash == HASH_A
    assert fetched.expires_at == NOW + timedelta(days=30)
    assert fetched.created_at.tzinfo is not None


def test_status_column_follows_the_invoice_confidence(database_url: str) -> None:
    with session_scope() as session:
        _make(session, _invoice(extraction_confidence="low"))
    with sqlite3.connect(_db_path(database_url)) as connection:
        assert connection.execute("SELECT status FROM invoices").fetchone() == ("low",)


def test_retention_is_configurable_and_a_bad_value_keeps_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFAULT_RETENTION_DAYS", "7")
    with session_scope() as session:
        assert _make(session).expires_at == NOW + timedelta(days=7)
    monkeypatch.setenv("DEFAULT_RETENTION_DAYS", "not-a-number")
    with session_scope() as session:
        assert _make(session, pdf_hash=HASH_B).expires_at == NOW + timedelta(days=30)


def test_create_rejects_an_invalid_pdf_hash() -> None:
    with session_scope() as session, pytest.raises(ValueError):
        _make(session, pdf_hash="../../etc/passwd")


@pytest.mark.parametrize(
    "bad_id",
    ["", "abc", "1; DROP TABLE invoices", "' OR '1'='1", "../../x", "A" * 36, "0" * 36],
)
def test_malformed_ids_are_simply_not_found(bad_id: str) -> None:
    with session_scope() as session:
        repo = InvoiceRepository(session)
        assert repo.get(bad_id, now=NOW) is None
        assert repo.update(bad_id, _invoice(), now=NOW) is None
        assert repo.delete(bad_id) is False


def test_uppercase_uuid_is_not_accepted() -> None:
    with session_scope() as session:
        created = _make(session)
        assert InvoiceRepository(session).get(created.id.upper(), now=NOW) is None


# --- nothing readable at rest ---
def test_database_file_contains_nothing_readable_about_the_customer(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session_scope() as session:
        _make(session, name="facture-orange-secrete.pdf")
    raw = _db_path(database_url).read_bytes()
    for secret in (b"Orange", b"Dupont", b"F-2026-001", b"facture-orange", b"120.0", b"Forfait"):
        assert secret not in raw


def test_deleted_data_is_physically_erased_from_the_file(database_url: str) -> None:
    """PRAGMA secure_delete: without it the ciphertext stays in the file's free pages."""
    with session_scope() as session:
        created = _make(session)
    with sqlite3.connect(_db_path(database_url)) as connection:
        ciphertext = connection.execute("SELECT payload FROM invoices").fetchone()[0]
    assert ciphertext[:40] in _db_path(database_url).read_bytes()

    with session_scope() as session:
        assert InvoiceRepository(session).delete(created.id) is True
    from src.core.database import dispose_engines

    dispose_engines()
    assert ciphertext[:40] not in _db_path(database_url).read_bytes()


# --- retention is enforced on read ---
def test_expired_record_is_treated_as_absent_before_the_purge_runs() -> None:
    with session_scope() as session:
        created = _make(session)
        repo = InvoiceRepository(session)
        later = created.expires_at + timedelta(seconds=1)
        assert repo.get(created.id, now=later) is None
        assert repo.list(now=later) == []
        assert repo.update(created.id, _invoice(), now=later) is None
        assert repo.get(created.id, now=created.expires_at - timedelta(seconds=1)) is not None


# --- list and filters ---
def _seed(session) -> dict[str, str]:
    repo = InvoiceRepository(session)
    rows = {
        "orange": repo.create(
            _invoice(),
            pdf_hash="1" * 64,
            display_name="orange-septembre.pdf",
            now=NOW - timedelta(days=3),
        ),
        "edf": repo.create(
            _invoice(supplier="EDF", client="Martin", invoice_number="E-77", date="2026-08-20"),
            pdf_hash="2" * 64,
            display_name="edf.pdf",
            now=NOW - timedelta(days=2),
        ),
        "nodate": repo.create(
            _invoice(supplier="Boulangerie Lune", date="pas une date", extraction_confidence="low"),
            pdf_hash="3" * 64,
            display_name="pain.pdf",
            now=NOW - timedelta(days=1),
        ),
    }
    return {key: value.id for key, value in rows.items()}


def test_list_is_newest_first() -> None:
    with session_scope() as session:
        ids = _seed(session)
        listed = InvoiceRepository(session).list(now=NOW)
    assert [item.id for item in listed] == [ids["nodate"], ids["edf"], ids["orange"]]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("orange", ["orange"]),  # supplier, and file name
        ("ORANGE", ["orange"]),  # case-insensitive
        ("martin", ["edf"]),  # client
        ("e-77", ["edf"]),  # invoice number
        ("pain.pdf", ["nodate"]),  # file name
        ("  edf  ", ["edf"]),  # trimmed
        ("inconnu", []),
        ("", ["nodate", "edf", "orange"]),
    ],
)
def test_list_search(query: str, expected: list[str]) -> None:
    with session_scope() as session:
        ids = _seed(session)
        found = InvoiceRepository(session).list(query=query, now=NOW)
    assert [item.id for item in found] == [ids[key] for key in expected]


def test_list_filters_on_the_invoice_date_with_processing_date_as_fallback() -> None:
    with session_scope() as session:
        ids = _seed(session)
        repo = InvoiceRepository(session)
        in_august = repo.list(date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), now=NOW)
        # "nodate" has no valid invoice date: it falls back to its processing date (Sep 20)
        from_sep_15 = repo.list(date_from=date(2026, 9, 15), now=NOW)
        bounds_are_inclusive = repo.list(
            date_from=date(2026, 9, 10), date_to=date(2026, 9, 10), now=NOW
        )
    assert [i.id for i in in_august] == [ids["edf"]]
    assert [i.id for i in from_sep_15] == [ids["nodate"]]
    assert [i.id for i in bounds_are_inclusive] == [ids["orange"]]


def test_list_filters_on_status() -> None:
    with session_scope() as session:
        ids = _seed(session)
        low = InvoiceRepository(session).list(status="low", now=NOW)
    assert [item.id for item in low] == [ids["nodate"]]


def test_list_pagination() -> None:
    with session_scope() as session:
        ids = _seed(session)
        repo = InvoiceRepository(session)
        page_1 = repo.list(limit=2, now=NOW)
        page_2 = repo.list(limit=2, offset=2, now=NOW)
    assert [i.id for i in page_1] == [ids["nodate"], ids["edf"]]
    assert [i.id for i in page_2] == [ids["orange"]]


@pytest.mark.parametrize(
    "kwargs", [{"limit": 0}, {"limit": 501}, {"offset": -1}, {"status": "medium"}]
)
def test_list_rejects_out_of_range_arguments(kwargs: dict) -> None:
    with session_scope() as session, pytest.raises(ValueError):
        InvoiceRepository(session).list(**kwargs)


# --- update ---
def test_update_replaces_content_but_not_the_retention_date_or_file_name() -> None:
    with session_scope() as session:
        created = _make(session, name="original.pdf")
        corrected = _invoice(supplier="Orange SA (corrigé)", extraction_confidence="low")
        updated = InvoiceRepository(session).update(created.id, corrected, now=NOW)
    assert updated.invoice.supplier == "Orange SA (corrigé)"
    assert updated.expires_at == created.expires_at  # a correction never extends retention
    assert updated.display_name == "original.pdf"
    with session_scope() as session:
        assert InvoiceRepository(session).list(status="low", now=NOW)[0].id == created.id


def test_update_of_an_unknown_id_returns_none() -> None:
    with session_scope() as session:
        assert (
            InvoiceRepository(session).update("0" * 8 + "-0000-4000-8000-" + "0" * 12, _invoice())
            is None
        )


# --- delete (GDPR erasure) ---
def test_delete_removes_the_record_and_its_cache_entry() -> None:
    cache.store_cache(HASH_A, _invoice())
    with session_scope() as session:
        created = _make(session)
        assert InvoiceRepository(session).delete(created.id) is True
    assert cache.get_cached(HASH_A) is None
    with session_scope() as session:
        assert InvoiceRepository(session).get(created.id, now=NOW) is None
        assert InvoiceRepository(session).delete(created.id) is False


def test_delete_leaves_everything_untouched_if_the_cache_cannot_be_erased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_hash: str) -> bool:
        raise StorageError("disk error")

    with session_scope() as session:
        created = _make(session)
    original = repository.delete_cached
    monkeypatch.setattr(repository, "delete_cached", boom)
    with pytest.raises(StorageError):
        with session_scope() as session:
            InvoiceRepository(session).delete(created.id)
    monkeypatch.setattr(
        repository, "delete_cached", original
    )  # not undo(): it would drop every fixture
    with session_scope() as session:  # the row is still there: the caller can retry
        assert InvoiceRepository(session).get(created.id, now=NOW) is not None


def test_a_tampered_pdf_hash_is_never_turned_into_a_path(database_url: str, tmp_path: Path) -> None:
    victim = tmp_path / "victim.enc"
    victim.write_text("must survive")
    with session_scope() as session:
        created = _make(session)
        session.execute(
            text("UPDATE invoices SET pdf_hash = :h"),
            {"h": "../" + victim.stem},
        )
    with session_scope() as session:
        assert InvoiceRepository(session).delete(created.id) is True  # still erasable
    assert victim.read_text() == "must survive"


# --- purge ---
def test_purge_expired_erases_old_records_and_their_cache_entries_only() -> None:
    cache.store_cache(HASH_A, _invoice())
    cache.store_cache(HASH_B, _invoice())
    with session_scope() as session:
        old = _make(session, pdf_hash=HASH_A, now=NOW - timedelta(days=40))
        fresh = _make(session, pdf_hash=HASH_B, now=NOW - timedelta(days=1))
        assert InvoiceRepository(session).purge_expired(now=NOW) == 1
    assert cache.get_cached(HASH_A) is None and cache.get_cached(HASH_B) is not None
    with session_scope() as session:
        repo = InvoiceRepository(session)
        assert repo.get(old.id, now=NOW - timedelta(days=39)) is None
        assert repo.get(fresh.id, now=NOW) is not None


def test_purge_removes_expired_records_even_when_they_can_no_longer_be_decrypted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with session_scope() as session:
        _make(session, now=NOW - timedelta(days=40))
    monkeypatch.setenv("CACHE_ENCRYPTION_KEY", Fernet.generate_key().decode())  # key lost
    with session_scope() as session:
        assert InvoiceRepository(session).purge_expired(now=NOW) == 1


def test_purge_with_nothing_to_do_returns_zero() -> None:
    with session_scope() as session:
        assert InvoiceRepository(session).purge_expired(now=NOW) == 0


# --- integrity ---
def test_tampered_payload_is_refused_on_get_and_skipped_in_list(database_url: str) -> None:
    with session_scope() as session:
        created = _make(session)
        good = _make(session, pdf_hash=HASH_B)
    with sqlite3.connect(_db_path(database_url)) as connection:
        payload = bytearray(
            connection.execute(
                "SELECT payload FROM invoices WHERE id = ?", (created.id,)
            ).fetchone()[0]
        )
        payload[len(payload) // 2] ^= 0x01
        connection.execute(
            "UPDATE invoices SET payload = ? WHERE id = ?", (bytes(payload), created.id)
        )
    with session_scope() as session:
        repo = InvoiceRepository(session)
        with pytest.raises(StorageError, match="tampered"):
            repo.get(created.id, now=NOW)
        assert [item.id for item in repo.list(now=NOW)] == [good.id]  # one bad row: list survives


def test_payload_copied_onto_another_row_is_refused(database_url: str) -> None:
    with session_scope() as session:
        first = _make(session)
        second = _make(session, _invoice(supplier="Autre"), pdf_hash=HASH_B)
    with sqlite3.connect(_db_path(database_url)) as connection:
        stolen = connection.execute(
            "SELECT payload FROM invoices WHERE id = ?", (first.id,)
        ).fetchone()[0]
        connection.execute("UPDATE invoices SET payload = ? WHERE id = ?", (stolen, second.id))
    with session_scope() as session:
        with pytest.raises(StorageError, match="another record"):
            InvoiceRepository(session).get(second.id, now=NOW)


def test_other_key_makes_records_unreadable_not_crashing_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with session_scope() as session:
        created = _make(session)
    monkeypatch.setenv("CACHE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with session_scope() as session:
        repo = InvoiceRepository(session)
        assert repo.list(now=NOW) == []
        with pytest.raises(StorageError):
            repo.get(created.id, now=NOW)


def test_missing_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CACHE_ENCRYPTION_KEY")
    with session_scope() as session, pytest.raises(StorageError, match="CACHE_ENCRYPTION_KEY"):
        _make(session)


# --- effective_date ---
@pytest.mark.parametrize(
    ("invoice_date", "expected"),
    [
        ("2026-09-10", date(2026, 9, 10)),
        ("10/09/2026", date(2026, 9, 21)),
        (None, date(2026, 9, 21)),
    ],
)
def test_effective_date(invoice_date: str | None, expected: date) -> None:
    with session_scope() as session:
        stored = _make(session, _invoice(date=invoice_date))
    assert stored.effective_date == expected
