"""
Integration test fixtures for FXLab Phase 3.

Responsibilities:
- Provide fixtures that spin up or connect to real services (DB, Redis, storage).
- All fixtures here use real I/O and are intended for the integration test suite only.
- Apply SAVEPOINT isolation (LL-S004) so tests do not contaminate each other.

Does NOT:
- Contain business logic.
- Stub or mock external services (that is the unit conftest's job).

Dependencies:
- SQLAlchemy 2.x with SQLite or PostgreSQL
- libs.contracts.models.Base — ORM metadata registry

Notes:
- Use session.flush() NOT session.commit() inside fixtures to keep data within
  the SAVEPOINT boundary.  Committing past a SAVEPOINT causes UNIQUE violations
  in subsequent tests (LL-S004).
- Cross-arch venv warning: pydantic-core native binaries may not load in
  cross-architecture sandboxes (macOS arm64 venv on Linux x86_64).  When this
  happens, Field constraint enforcement is silently disabled.  Use
  model.model_fields inspection instead of expecting ValidationError (LL-007).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import Base


# ---------------------------------------------------------------------------
# Database URL helpers
# ---------------------------------------------------------------------------


def _integration_db_url() -> str:
    """
    Return the integration test database URL.

    Reads TEST_DATABASE_URL from the environment, defaulting to the local
    docker-compose PostgreSQL instance.

    Returns:
        SQLAlchemy-compatible database URL string.
    """
    return os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://fxlab:fxlab@localhost:5432/fxlab_test",
    )


# ---------------------------------------------------------------------------
# Core DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def integration_db_engine():
    """
    Create a session-scoped SQLAlchemy engine for integration tests.

    Creates all tables on startup and drops them on teardown.
    Uses _integration_db_url() which resolves TEST_DATABASE_URL.

    Yields:
        SQLAlchemy Engine connected to the integration test database.
    """
    url = _integration_db_url()
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def integration_db_session(integration_db_engine) -> Generator[Session, None, None]:
    """
    Provide a per-test database session wrapped in a SAVEPOINT.

    Uses the SAVEPOINT isolation pattern (LL-S004) so each test gets a clean
    slate without recreating tables.  Session data is rolled back after each
    test regardless of pass/fail.

    Args:
        integration_db_engine: Session-scoped engine fixture.

    Yields:
        SQLAlchemy Session bound to a SAVEPOINT transaction.
    """
    connection = integration_db_engine.connect()
    transaction = connection.begin()
    nested = connection.begin_nested()  # SAVEPOINT
    session = Session(bind=connection)

    yield session

    session.close()
    nested.rollback()  # roll back to SAVEPOINT
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# URL / connectivity fixtures (no I/O — just config strings)
# ---------------------------------------------------------------------------


@pytest.fixture
def integration_test_db_url() -> str:
    """
    Return the integration test database URL string.

    Returns:
        Postgres or SQLite URL for integration test database.
    """
    return _integration_db_url()


@pytest.fixture
def integration_test_redis_url() -> str:
    """
    Return the test Redis URL (DB 15, isolated from production).

    Returns:
        redis://localhost:6379/15
    """
    return "redis://localhost:6379/15"


@pytest.fixture
def integration_temp_storage(tmp_path: Path) -> Generator[Path, None, None]:
    """
    Provide a temporary directory for integration storage tests.

    The directory is cleaned up automatically by pytest's tmp_path mechanism.

    Args:
        tmp_path: pytest built-in temporary directory fixture.

    Yields:
        Path to an isolated storage directory.
    """
    storage = tmp_path / "integration_storage"
    storage.mkdir(parents=True, exist_ok=True)
    yield storage


@pytest.fixture
def integration_test_correlation_id() -> str:
    """
    Provide a fresh ULID correlation ID for integration test tracing.

    Returns:
        26-character ULID string.
    """
    import ulid

    return str(ulid.ULID())
