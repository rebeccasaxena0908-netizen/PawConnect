"""
Alembic environment. Uses the same engine as the app (db.engine), so the
database URL always comes from DATABASE_URL / config.py and never from alembic.ini.
"""
from logging.config import fileConfig

from alembic import context

from db.engine import get_engine
from db.tables import metadata

config = context.config
# Only set up logging when run from the `alembic` command, not from inside the app.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql` – print the SQL instead of running it."""
    context.configure(url=str(get_engine().url), target_metadata=metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:              # called from db.init_db() with an open connection
        _run(connection)
        return
    with get_engine().connect() as connection:
        _run(connection)


def _run(connection) -> None:
    # render_as_batch lets later migrations ALTER tables on SQLite too.
    context.configure(connection=connection, target_metadata=metadata, render_as_batch=True,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
