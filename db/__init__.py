"""
Database package.

    engine.py      – engine for DATABASE_URL + transaction() helper
    tables.py      – table definitions with keys, CHECKs and indexes
    migrations/    – Alembic migrations (alembic upgrade head)
"""
from __future__ import annotations

from config import BASE_DIR


def alembic_config(connection=None):
    """Alembic settings pointing at db/migrations, optionally reusing an open connection."""
    from alembic.config import Config
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "db" / "migrations"))
    cfg.attributes["configure_logger"] = False
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def init_db() -> None:
    """Create or upgrade every table by running the Alembic migrations (safe to call often)."""
    from alembic import command
    from db.engine import get_engine
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        with engine.begin() as connection:
            command.upgrade(alembic_config(connection), "head")
        return
    # SQLite changes a column by copying the whole table. Foreign-key checks must be
    # off while that happens (they can only be switched outside a transaction), and
    # we check that nothing is broken before switching them back on.
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        raw.execute("PRAGMA foreign_keys = OFF")
        try:
            with connection.begin():
                command.upgrade(alembic_config(connection), "head")
                broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise RuntimeError(f"Migration left broken foreign keys: {broken[:3]}")
        finally:
            raw.execute("PRAGMA foreign_keys = ON")
