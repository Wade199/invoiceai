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
    assert [p.name for p in cache_dir.iterdir()] == [f"{HASH_A}.json"]


def test_corrupted_entry_is_a_miss_and_is_removed(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True)
    entry = cache_dir / f"{HASH_A}.json"
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
