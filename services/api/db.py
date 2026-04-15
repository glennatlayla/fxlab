"""
Database session factory and FastAPI dependency.

Responsibilities:
- Create a SQLAlchemy engine from DATABASE_URL environment variable.
- Provide a SessionLocal factory for creating database sessions.
- Export get_db() as a FastAPI dependency that yields a session per request
  and ensures it is closed after the response is sent.
- Re-export Base from libs.contracts.models for use in Alembic env.py.

Does NOT:
- Contain business logic.
- Define any ORM models (those live in libs/contracts/models.py).
- Run migrations (Alembic handles that).

Dependencies:
- DATABASE_URL environment variable (falls back to SQLite in-memory for tests).
- SQLAlchemy 2.x
- libs.contracts.models.Base

Error conditions:
- Raises sqlalchemy.exc.OperationalError on connection failure at query time.

Example:
    # In a FastAPI route:
    from services.api.db import get_db
    from sqlalchemy.orm import Session
    from fastapi import Depends

    @router.get("/things")
    def list_things(db: Session = Depends(get_db)):
        return db.execute(select(Thing)).scalars().all()

    # In tests — override get_db with an in-memory SQLite session:
    app.dependency_overrides[get_db] = lambda: test_session
"""

from __future__ import annotations

import os
from collections.abc import Generator

import sqlalchemy.exc
import structlog
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import Base  # noqa: F401 — re-exported for Alembic

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine configuration
# ---------------------------------------------------------------------------

# DATABASE_URL supports both PostgreSQL (production) and SQLite (tests).
# Resolved via SecretProvider when available, falling back to os.environ
# for backward compatibility during bootstrapping.


def _resolve_database_url() -> str:
    """
    Resolve DATABASE_URL via SecretProvider, falling back to os.environ.

    The fallback exists because db.py may be imported before the
    SecretProvider singleton is initialised (e.g. during Alembic migrations
    or early test collection).

    Returns:
        Database connection URL string.
    """
    env = os.environ.get("ENVIRONMENT", "")

    try:
        from services.api.infrastructure.secret_provider_factory import get_provider

        url = get_provider().get_secret_or_default("DATABASE_URL", "")
    except (ImportError, KeyError, RuntimeError):
        # Fallback during early bootstrap (Alembic, pytest collection)
        url = os.environ.get("DATABASE_URL", "")

    # --- Production guard: SQLite is forbidden in production ---
    if env == "production":
        if not url:
            raise RuntimeError(
                "DATABASE_URL is not set. Production deployments MUST use PostgreSQL. "
                "Set DATABASE_URL=postgresql://user:pass@host:5432/dbname?sslmode=require"
            )
        if url.startswith("sqlite"):
            raise RuntimeError(
                "DATABASE_URL points to SQLite, which is forbidden in production. "
                "SQLite lacks concurrent write support, connection pooling, and "
                "row-level locking — all required for a trading platform. "
                "Set DATABASE_URL to a PostgreSQL connection string."
            )

    # For non-production: fall back to SQLite for local dev / tests
    if not url:
        url = "sqlite:///./fxlab_test.db"
        if env and env not in ("test", "development", ""):
            logger.warning(
                "db.sqlite_fallback",
                environment=env,
                detail="DATABASE_URL not set — falling back to SQLite. "
                "This is only acceptable in test/development.",
                component="db",
            )

    return url


_DATABASE_URL: str = _resolve_database_url()

_CONNECT_ARGS: dict = {}


# ---------------------------------------------------------------------------
# Connection pool configuration (configurable via environment variables)
# ---------------------------------------------------------------------------

# Defaults — sized for multi-worker production deployments (2+ Uvicorn workers).
# With pool_size=20 + max_overflow=20, up to 40 concurrent DB connections are
# available per process, preventing request queuing under spike traffic.
# Previous defaults (5/10) caused connection starvation under moderate load.
_DEFAULT_POOL_SIZE = 20
_DEFAULT_POOL_OVERFLOW = 20
_DEFAULT_POOL_TIMEOUT = 30
_DEFAULT_STATEMENT_TIMEOUT_MS = 30_000  # 30 seconds — terminates runaway queries


def _read_positive_int(env_var: str, default: int) -> int:
    """
    Read a positive integer from an environment variable.

    Args:
        env_var: Name of the environment variable.
        default: Value to return when the variable is absent, non-numeric, or non-positive.

    Returns:
        The parsed integer if > 0, otherwise *default*.

    Example:
        _read_positive_int("DB_POOL_SIZE", 5)  # returns 5 if not set
    """
    raw = os.environ.get(env_var, "")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.critical(
            "db.pool_config_invalid",
            env_var=env_var,
            raw_value=raw,
            reason="non-numeric value; using default",
            default=default,
        )
        return default
    if value <= 0:
        logger.critical(
            "db.pool_config_invalid",
            env_var=env_var,
            raw_value=raw,
            reason="non-positive value; using default",
            default=default,
        )
        return default
    return value


def _get_pool_kwargs(database_url: str) -> tuple[dict, dict]:
    """
    Build SQLAlchemy engine pool keyword arguments based on the database URL.

    For SQLite databases, returns StaticPool configuration (no connection pool).
    For PostgreSQL (or other server-based databases), reads pool parameters from
    environment variables with validated defaults.

    Args:
        database_url: The database connection URL.

    Returns:
        A 2-tuple of:
        - engine_kwargs: Dict of keyword arguments suitable for
          ``create_engine(**engine_kwargs)`` (pool settings only, no
          ``connect_args`` — those are in the second element).
        - extra_connect_args: Dict of additional libpq/driver connect
          options (e.g. PostgreSQL ``statement_timeout``).  The caller
          must merge these into the ``connect_args`` dict passed to
          ``create_engine()``.

    Raises:
        No exceptions raised; invalid env values fall back to defaults with
        CRITICAL-level log warnings.

    Example:
        engine_kw, pg_connect = _get_pool_kwargs("postgresql://u:p@host/db")
        # engine_kw == {"pool_size": 20, "max_overflow": 20, ...}
        # pg_connect == {"options": "-c statement_timeout=30000"}
    """
    if database_url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        return {"poolclass": StaticPool}, {}

    pool_size = _read_positive_int("DB_POOL_SIZE", _DEFAULT_POOL_SIZE)
    max_overflow = _read_positive_int("DB_POOL_OVERFLOW", _DEFAULT_POOL_OVERFLOW)
    pool_timeout = _read_positive_int("DB_POOL_TIMEOUT", _DEFAULT_POOL_TIMEOUT)
    statement_timeout = _read_positive_int(
        "DB_STATEMENT_TIMEOUT_MS",
        _DEFAULT_STATEMENT_TIMEOUT_MS,
    )

    return {
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout,
        "pool_pre_ping": True,  # evict stale connections before use
    }, {
        # PostgreSQL statement timeout via libpq connect options.
        # Returned separately so the caller can merge into _CONNECT_ARGS
        # rather than passing a duplicate 'connect_args' to create_engine().
        "options": f"-c statement_timeout={statement_timeout}",
    }


_POOL_KWARGS, _PG_CONNECT_ARGS = _get_pool_kwargs(_DATABASE_URL)

if _DATABASE_URL.startswith("sqlite"):
    # SQLite requires check_same_thread=False when used with FastAPI because
    # requests are handled in a thread pool and the session may be used from
    # a different thread than the one that created the connection.
    _CONNECT_ARGS = {"check_same_thread": False}
else:
    # Merge PostgreSQL-specific libpq options (e.g. statement_timeout)
    # into connect_args.  _PG_CONNECT_ARGS is empty for SQLite.
    _CONNECT_ARGS = {**_CONNECT_ARGS, **_PG_CONNECT_ARGS}

engine = create_engine(
    _DATABASE_URL,
    connect_args=_CONNECT_ARGS,
    **_POOL_KWARGS,
    echo=os.environ.get("SQL_ECHO", "false").lower() == "true",
)

# Enable WAL mode for SQLite (improves concurrent read performance in tests).
if _DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


# Session factory — each call to SessionLocal() produces a new Session.
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # avoid lazy-loading after commit in async contexts
)

logger.debug(
    "db.engine_created",
    url=_DATABASE_URL.split("@")[-1] if "@" in _DATABASE_URL else _DATABASE_URL,
    pool_size=_POOL_KWARGS.get("pool_size", "n/a"),
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session for the duration of a request.

    Commits the session on successful completion, rolls back on exception,
    and always closes. This makes every request an atomic unit of work:
    all flushes that occur during the request are committed together, or
    rolled back together on any error.

    Usage:
        @router.get("/things")
        def list_things(db: Session = Depends(get_db)):
            ...

    Yields:
        Session: An active SQLAlchemy session bound to the request lifecycle.

    Notes:
        - Repository and audit writer methods should use session.flush()
          (not commit) to stay within the request-scoped transaction.
        - Legacy code that calls session.commit() directly is safe —
          commit is idempotent on an already-committed or empty session.
        - On exception, the session is rolled back before closing.

    Example:
        from services.api.db import get_db
        db = next(get_db())  # for manual use outside FastAPI DI
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_db_connection() -> bool:
    """
    Ping the database to verify connectivity.

    Returns:
        True if the database is reachable.
        False if the connection attempt fails.

    Example:
        if check_db_connection():
            logger.info("db.connected")
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except (
        sqlalchemy.exc.OperationalError,
        sqlalchemy.exc.TimeoutError,
        sqlalchemy.exc.InterfaceError,
        OSError,
    ) as exc:
        logger.warning(
            "db.connection_check_failed",
            error=str(exc),
            exc_info=True,
            component="db",
        )
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "Base",
    "SessionLocal",
    "check_db_connection",
    "engine",
    "get_db",
]
