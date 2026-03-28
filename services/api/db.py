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

import structlog
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import Base  # noqa: F401 — re-exported for Alembic

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine configuration
# ---------------------------------------------------------------------------

# DATABASE_URL supports both PostgreSQL (production) and SQLite (tests).
# SQLite in-memory is used when the variable is not set, which is the default
# for unit test runs that don't start a database container.
_DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "sqlite:///./fxlab_test.db",
)

_CONNECT_ARGS: dict = {}
_POOL_KWARGS: dict = {}

if _DATABASE_URL.startswith("sqlite"):
    # SQLite requires check_same_thread=False when used with FastAPI because
    # requests are handled in a thread pool and the session may be used from
    # a different thread than the one that created the connection.
    _CONNECT_ARGS = {"check_same_thread": False}
    # NullPool prevents SQLite file locking issues in tests.
    from sqlalchemy.pool import StaticPool
    _POOL_KWARGS = {"poolclass": StaticPool}
else:
    # PostgreSQL — use a connection pool sized for moderate API concurrency.
    _POOL_KWARGS = {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,   # evict stale connections before use
    }

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

    Usage:
        @router.get("/things")
        def list_things(db: Session = Depends(get_db)):
            ...

    Yields:
        Session: An active SQLAlchemy session bound to the request lifecycle.

    Notes:
        - The session is always closed in the finally block even if an exception
          is raised during request handling.
        - Rollback on error is intentionally left to the caller — the session's
          autorollback behaviour handles this for most cases.

    Example:
        from services.api.db import get_db
        db = next(get_db())  # for manual use outside FastAPI DI
    """
    db = SessionLocal()
    try:
        yield db
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
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.connection_check_failed", error=str(exc))
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
