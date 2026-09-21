from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from src.core.env import load_env
from src.core.exceptions import StorageError
from src.models.invoice_record import Base

logger = logging.getLogger(__name__)

_DEFAULT_DATABASE_URL = "sqlite:///./data/invoiceai.db"

# One engine per URL (an engine owns a connection pool). Guarded: the API serves requests
# from several threads.
_engines: dict[str, Engine] = {}
_lock = threading.Lock()


def database_url() -> str:
    # Read at call time so tests / deployments can override it.
    load_env()
    return os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record) -> None:  # noqa: ANN001 - DBAPI object
        cursor = dbapi_connection.cursor()
        # Without this SQLite leaves deleted rows readable in the file's free pages: a
        # GDPR erasure would not physically erase anything.
        cursor.execute("PRAGMA secure_delete = ON")
        cursor.close()


def _restrict_permissions(url: str) -> None:
    """Owner-only mode on the database file (POSIX; no effect on Windows)."""
    database = make_url(url).database
    if database and database != ":memory:" and Path(database).exists():
        try:
            os.chmod(database, 0o600)
        except OSError:
            logger.warning("Cannot restrict permissions on the database file")


def get_engine(url: str | None = None) -> Engine:
    """Return the (cached) engine for `url` and make sure the tables exist.

    Raises:
        StorageError: If the database cannot be opened or initialised.
    """
    url = url or database_url()
    with _lock:
        engine = _engines.get(url)
        if engine is None:
            try:
                parsed = make_url(url)
                if parsed.drivername.startswith("sqlite") and parsed.database not in (
                    None,
                    "",
                    ":memory:",
                ):
                    Path(parsed.database).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                engine = create_engine(url)
                if engine.dialect.name == "sqlite":
                    _configure_sqlite(engine)
                Base.metadata.create_all(engine)
                _restrict_permissions(url)
            except (SQLAlchemyError, OSError) as exc:
                raise StorageError(f"Cannot open the database: {type(exc).__name__}") from exc
            _engines[url] = engine
        return engine


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    """A transaction: committed if the block succeeds, rolled back if it raises."""
    session = sessionmaker(get_engine(url), expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise StorageError(f"Database error: {type(exc).__name__}") from exc
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engines() -> None:
    """Close every pooled connection (releases the database files: needed on Windows)."""
    with _lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
