"""
Database engine and transaction helper (SQLAlchemy 2.x Core).

* The URL comes from config.DATABASE_URL (SQLite file by default, PostgreSQL
  when DATABASE_URL is set), so the same code runs on both.
* `transaction()` is the one way to change data: everything inside the
  `with` block is committed together, or rolled back together if anything fails.

    with transaction() as conn:
        conn.execute(...)
        conn.execute(...)      # both happen, or neither does
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Connection, Engine, create_engine, event

import config

_engine: Engine | None = None


def _sqlite_setup(engine: Engine) -> None:
    """
    SQLite needs three tweaks to behave like a real server database:
      1. foreign keys are OFF by default – switch them on for every connection;
      2. wait up to 15 s for a lock instead of failing at once;
      3. take the write lock at the *start* of a write transaction
         (BEGIN IMMEDIATE), so two "read balance → insert" transactions can
         never interleave. Read-only work keeps a normal (deferred) BEGIN.
    """
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None          # let SQLAlchemy emit BEGIN itself
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA busy_timeout = 15000")
        cursor.execute("PRAGMA journal_mode = WAL")       # readers don't block the writer
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Connection):
        mode = conn.get_execution_options().get("sqlite_begin", "DEFERRED")
        conn.exec_driver_sql(f"BEGIN {mode}")


def get_engine() -> Engine:
    """Create the engine once (lazily) and reuse it."""
    global _engine
    if _engine is None:
        url = config.DATABASE_URL
        if url.startswith("sqlite"):
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(url, echo=config.DB_ECHO,
                                    connect_args={"check_same_thread": False, "timeout": 15})
            _sqlite_setup(_engine)
        else:
            _engine = create_engine(url, echo=config.DB_ECHO, pool_pre_ping=True)
    return _engine


def reset_engine() -> None:
    """Forget the cached engine (used by tests and after changing DATABASE_URL)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def is_sqlite() -> bool:
    return get_engine().dialect.name == "sqlite"


@contextmanager
def transaction() -> Iterator[Connection]:
    """All-or-nothing block: commit on success, roll back on any exception."""
    with get_engine().connect() as conn:
        conn.execution_options(sqlite_begin="IMMEDIATE")
        with conn.begin():
            yield conn


@contextmanager
def reading() -> Iterator[Connection]:
    """A connection for read-only queries."""
    with get_engine().connect() as conn:
        yield conn
