from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_invoice_pdf() -> Path:
    """Path to a valid, text-based fake invoice PDF (1 page)."""
    return Path(__file__).parent / "fixtures" / "pdfs" / "sample_invoice.pdf"


@pytest.fixture(autouse=True)
def _never_read_the_real_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never load the developer's real .env (real API key, real settings)."""
    monkeypatch.setattr("src.core.env.load_dotenv", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _cache_encryption_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """A throw-away key per test: the cache fails closed without one."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CACHE_ENCRYPTION_KEY", key)
    return key


@pytest.fixture(autouse=True)
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Uploads go to a per-test folder: tests never touch the real data/uploads."""
    directory = tmp_path / "uploads"
    monkeypatch.setenv("UPLOAD_DIR", str(directory))
    return directory


@pytest.fixture(autouse=True)
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A throw-away SQLite file per test; connections are released so Windows can clean up."""
    from src.core.database import dispose_engines

    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    yield url
    dispose_engines()


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Cache entries go to a per-test folder: tests never write into the real data/cache."""
    directory = tmp_path / "cache"
    monkeypatch.setenv("CACHE_DIR", str(directory))
    return directory
