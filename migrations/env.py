"""
Alembic migration environment.

Responsibilities:
- Configure the SQLAlchemy engine for both online (live) and offline
  (SQL script generation) migration modes.
- Import all ORM models via libs.contracts.models.Base so that autogenerate
  can detect schema changes.
- Read DATABASE_URL from environment, falling back to alembic.ini value.

Does NOT:
- Contain business logic.
- Run migrations itself — Alembic calls run_migrations_online/offline.

Dependencies:
- libs.contracts.models (Base, all ORM model classes)
- SQLAlchemy, Alembic
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Import all ORM models so autogenerate picks them up
# ---------------------------------------------------------------------------
# This import registers every model's __tablename__ in Base.metadata.
# Adding a new model to libs/contracts/models.py is sufficient — no change
# here is needed as long as the model inherits from Base.
from libs.contracts.models import Base  # noqa: F401 — side-effect import

# ---------------------------------------------------------------------------
# Alembic Config object (provides access to values in alembic.ini)
# ---------------------------------------------------------------------------
config = context.config

# Override sqlalchemy.url with DATABASE_URL from environment if set.
# This allows docker-compose and CI to inject the real connection string
# without modifying alembic.ini.
_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate support
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline mode — generate SQL script without a live database connection
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """
    Run migrations in offline mode.

    Configures the context with just a URL and not an Engine — calls to
    context.execute() emit the SQL to the script output stream.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode — run migrations against a live database connection
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    """
    Run migrations in online mode.

    Creates an Engine, associates a connection with the context, and runs
    migrations within a transaction.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
