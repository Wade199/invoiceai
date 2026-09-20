from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.core.exceptions import StorageError
from src.models.schemas import ExtractedInvoice, InvoiceLineItem
from src.services import cache

HASH_A = "a" * 64


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "cache"
    monkeypatch.setenv("CACHE_DIR", str(directory))
    return directory


@pytest.fixture
def invoice() -> ExtractedInvoice:
    return ExtractedInvoice(
        invoice_number="F-001",
        supplier="ACME",
        lines=[InvoiceLineItem(description="A", quantity=1, unit_price=10.0, total=10.0)],
        subtotal_ht=10.0,
        tva_rate=0.2,
        total_ttc=12.0,
    )


def test_hash_pdf_matches_sha256(tmp_path: Path) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 hello")
    assert cache.hash_pdf(pdf) == hashlib.sha256(b"%PDF-1.4 hello").hexdigest()


def test_hash_pdf_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        cache.hash_pdf(tmp_path / "nope.pdf")


def test_miss_returns_none() -> None:
    assert cache.get_cached(HASH_A) is None


def test_store_then_get_roundtrip(invoice: ExtractedInvoice) -> None:
    cache.store_cache(HASH_A, invoice)
    assert cache.get_cached(HASH_A) == invoice


def test_store_overwrites_existing_entry(invoice: ExtractedInvoice) -> None:
    cache.store_cache(HASH_A, invoice)
    cache.store_cache(HASH_A, invoice.model_copy(update={"supplier": "OTHER"}))
    assert cache.get_cached(HASH_A).supplier == "OTHER"


def test_store_leaves_no_temp_file(cache_dir: Path, invoice: ExtractedInvoice) -> None:
    cache.store_cache(HASH_A, invoice)
    assert [p.name for p in cache_dir.iterdir()] == [f"{HASH_A}.enc"]


def test_corrupted_entry_is_a_miss_and_is_removed(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True)
    entry = cache_dir / f"{HASH_A}.enc"
    entry.write_text("{not json", encoding="utf-8")
    assert cache.get_cached(HASH_A) is None
    assert not entry.exists()


@pytest.mark.parametrize("bad_hash", ["../../etc/passwd", "abc", "A" * 64, ""])
def test_invalid_hash_rejected(bad_hash: str, invoice: ExtractedInvoice) -> None:
    with pytest.raises(ValueError):
        cache.get_cached(bad_hash)
    with pytest.raises(ValueError):
        cache.store_cache(bad_hash, invoice)
    with pytest.raises(ValueError):
        cache.delete_cached(bad_hash)


def test_delete_cached(invoice: ExtractedInvoice) -> None:
    cache.store_cache(HASH_A, invoice)
    assert cache.delete_cached(HASH_A) is True
    assert cache.get_cached(HASH_A) is None
    assert cache.delete_cached(HASH_A) is False


def test_write_failure_raises_storage_error(
    cache_dir: Path, invoice: ExtractedInvoice, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CACHE_DIR pointing at an existing *file* makes mkdir/write fail with OSError.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setenv("CACHE_DIR", str(blocker))
    with pytest.raises(StorageError):
        cache.store_cache(HASH_A, invoice)


def test_concurrent_stores_of_same_hash_do_not_corrupt_entry(
    cache_dir: Path, invoice: ExtractedInvoice
) -> None:
    """Two Streamlit sessions uploading the same PDF must not clobber each other's temp file."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(cache.store_cache, HASH_A, invoice) for _ in range(40)]
        for future in futures:
            future.result()  # re-raises any StorageError

    assert cache.get_cached(HASH_A) == invoice
    assert [p.name for p in cache_dir.iterdir()] == [f"{HASH_A}.enc"]


# --- Confidentiality, integrity, retention (security review) ---------------------------------
def test_entry_on_disk_is_encrypted(cache_dir: Path, invoice: ExtractedInvoice) -> None:
    cache.store_cache(HASH_A, invoice)
    raw = (cache_dir / f"{HASH_A}.enc").read_bytes()
    assert b"ACME" not in raw and b"F-001" not in raw  # no personal data in clear text


def test_missing_key_fails_closed(
    invoice: ExtractedInvoice, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CACHE_ENCRYPTION_KEY")
    with pytest.raises(StorageError, match="CACHE_ENCRYPTION_KEY"):
        cache.store_cache(HASH_A, invoice)
    with pytest.raises(StorageError):
        cache.get_cached(HASH_A)


def test_invalid_key_rejected(invoice: ExtractedInvoice, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACHE_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(StorageError, match="not a valid"):
        cache.store_cache(HASH_A, invoice)


def test_tampered_entry_is_rejected_and_deleted(cache_dir: Path, invoice: ExtractedInvoice) -> None:
    cache.store_cache(HASH_A, invoice)
    entry = cache_dir / f"{HASH_A}.enc"
    data = bytearray(entry.read_bytes())
    data[len(data) // 2] ^= 0x01  # flip one bit
    entry.write_bytes(bytes(data))
    assert cache.get_cached(HASH_A) is None
    assert not entry.exists()


def test_entry_copied_onto_another_hash_is_rejected(
    cache_dir: Path, invoice: ExtractedInvoice
) -> None:
    """A valid entry renamed to another PDF's hash must not be served for that PDF."""
    hash_b = "b" * 64
    cache.store_cache(HASH_A, invoice)
    (cache_dir / f"{HASH_A}.enc").rename(cache_dir / f"{hash_b}.enc")
    assert cache.get_cached(hash_b) is None


def test_entry_encrypted_with_another_key_is_a_miss(
    invoice: ExtractedInvoice, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cryptography.fernet import Fernet

    cache.store_cache(HASH_A, invoice)
    monkeypatch.setenv("CACHE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert cache.get_cached(HASH_A) is None


def test_expired_entry_is_a_miss_and_is_deleted(
    cache_dir: Path, invoice: ExtractedInvoice, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache.store_cache(HASH_A, invoice)
    real_time = cache.time.time
    monkeypatch.setattr(cache.time, "time", lambda: real_time() + 31 * 86_400)
    assert cache.get_cached(HASH_A) is None
    assert not (cache_dir / f"{HASH_A}.enc").exists()


def test_entry_within_retention_is_served(
    invoice: ExtractedInvoice, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache.store_cache(HASH_A, invoice)
    real_time = cache.time.time
    monkeypatch.setattr(cache.time, "time", lambda: real_time() + 29 * 86_400)
    assert cache.get_cached(HASH_A) == invoice


def test_retention_is_configurable_and_bad_value_keeps_default(
    invoice: ExtractedInvoice, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CACHE_TTL_DAYS", "1")
    cache.store_cache(HASH_A, invoice)
    real_time = cache.time.time
    monkeypatch.setattr(cache.time, "time", lambda: real_time() + 2 * 86_400)
    assert cache.get_cached(HASH_A) is None
    monkeypatch.setenv("CACHE_TTL_DAYS", "garbage")
    assert cache._ttl_seconds() == 30 * 86_400


def test_purge_expired_removes_expired_invalid_and_legacy_files(
    cache_dir: Path, invoice: ExtractedInvoice, monkeypatch: pytest.MonkeyPatch
) -> None:
    hash_b, hash_c = "b" * 64, "c" * 64
    cache.store_cache(HASH_A, invoice)  # will expire
    real_time = cache.time.time
    monkeypatch.setattr(cache.time, "time", lambda: real_time() + 20 * 86_400)
    cache.store_cache(hash_b, invoice)  # stored "20 days from now": still fresh at +31 days
    (cache_dir / f"{hash_c}.enc").write_bytes(b"garbage")  # invalid
    (cache_dir / f"{HASH_A[:-1]}9.json").write_text('{"supplier": "plaintext"}')  # legacy
    (cache_dir / "keep.txt").write_text("not ours")
    monkeypatch.setattr(cache.time, "time", lambda: real_time() + 31 * 86_400)

    deleted = cache.purge_expired()

    assert deleted == 3
    assert sorted(p.name for p in cache_dir.iterdir()) == sorted([f"{hash_b}.enc", "keep.txt"])


def test_purge_on_missing_directory_is_a_noop() -> None:
    assert cache.purge_expired() == 0
