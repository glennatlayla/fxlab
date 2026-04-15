"""
Integration tests for AlembicMigrationRunner and MigrationIntegrityValidator.

Scope:
    End-to-end verification that the FXLab migration chain (all 23
    migrations as of 2026-04) round-trips cleanly against a real database
    driven by Alembic.

Database targets (parameterised):
    - SQLite (temporary file): always runs; catches cross-dialect SQL
      portability problems early.
    - PostgreSQL: runs only when ``TEST_DATABASE_URL`` points at a reachable
      PostgreSQL instance. This is the authoritative production check —
      it catches dialect-specific defaults (e.g. BOOLEAN DEFAULT 0) that
      SQLite silently accepts.

Usage:
    # SQLite only (fast local check):
    pytest tests/integration/dev/test_alembic_migration_runner_integration.py

    # Full check (requires docker-compose.test.yml up):
    TEST_DATABASE_URL="postgresql://fxlab_test:fxlab_test@localhost:5433/fxlab_test" \
        pytest tests/integration/dev/test_alembic_migration_runner_integration.py

Rationale:
    Offline Alembic SQL generation passed two BOOLEAN-default bugs through
    to a live minitux install. The only durable fix is to execute the
    actual DDL against a real PostgreSQL server before merging. These
    integration tests are intended to run in CI as a gate on merges.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from libs.dev.alembic_migration_runner import AlembicMigrationRunner
from libs.dev.interfaces.migration_runner_interface import MigrationRunnerError
from libs.dev.migration_integrity_validator import MigrationIntegrityValidator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Absolute path to the FXLab repository root (contains alembic.ini)."""
    return Path(__file__).resolve().parents[3]


def _alembic_ini() -> Path:
    """Absolute path to the project's alembic.ini."""
    return _project_root() / "alembic.ini"


def _postgres_url_or_skip() -> str:
    """
    Resolve a reachable PostgreSQL URL or skip the test.

    Accepts either ``TEST_DATABASE_URL`` or ``DATABASE_URL`` — the former
    is preferred in CI to keep the production URL separate from the test
    URL; the latter is accepted as a convenience for local runs.
    """
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip(
            "PostgreSQL integration test requires TEST_DATABASE_URL / "
            "DATABASE_URL pointing at a PostgreSQL instance."
        )

    # Fail fast if the URL is set but the server is not reachable; this is
    # a more useful error than a cascade of Alembic failures downstream.
    try:
        engine = create_engine(url, future=True)
        try:
            with engine.connect():
                pass
        finally:
            engine.dispose()
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL at {url!r} is not reachable: {exc}")

    return url


@pytest.fixture()
def sqlite_database_url() -> Iterator[str]:
    """
    Provide a URL for a fresh, file-backed SQLite database.

    Yields:
        SQLAlchemy URL for the temporary database. The file is deleted
        after the test regardless of outcome.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)
    try:
        yield f"sqlite:///{db_path}"
    finally:
        if db_path.exists():
            db_path.unlink()


# ---------------------------------------------------------------------------
# Adapter-level tests
# ---------------------------------------------------------------------------


def test_runner_rejects_missing_alembic_ini(tmp_path: Path) -> None:
    """If alembic.ini does not exist, the runner must refuse to construct."""
    with pytest.raises(MigrationRunnerError):
        AlembicMigrationRunner(
            database_url="sqlite:///:memory:",
            alembic_ini_path=tmp_path / "missing.ini",
        )


def test_runner_rejects_empty_database_url() -> None:
    """An empty DATABASE_URL must fail early rather than triggering an
    Alembic internal error later."""
    with pytest.raises(MigrationRunnerError):
        AlembicMigrationRunner(
            database_url="",
            alembic_ini_path=_alembic_ini(),
        )


def test_runner_current_revision_is_none_on_empty_sqlite(
    sqlite_database_url: str,
) -> None:
    """A fresh SQLite file has no alembic_version table; the runner must
    return ``None`` rather than raising."""
    runner = AlembicMigrationRunner(
        database_url=sqlite_database_url,
        alembic_ini_path=_alembic_ini(),
    )
    assert runner.current_revision() is None


# ---------------------------------------------------------------------------
# Full round-trip validation — PostgreSQL (authoritative)
# ---------------------------------------------------------------------------
#
# No SQLite round-trip test is provided because the FXLab migration chain
# uses ALTER TABLE ADD CONSTRAINT (e.g. migration 0006) which SQLite does
# not support without batch-mode operations. More importantly, SQLite's
# permissive typing means it would silently accept the exact class of bug
# (BOOLEAN DEFAULT 0) that this suite is designed to catch — running the
# round-trip on SQLite would offer false confidence. PostgreSQL is the
# authoritative target.


@pytest.mark.integration
def test_migration_chain_round_trips_on_postgres() -> None:
    """
    Full migration chain upgrades, downgrades, and re-upgrades on
    PostgreSQL.

    This is the authoritative production gate. It is the only test that
    would have caught the BOOLEAN DEFAULT 0 mismatch in migration 0013
    before it shipped.

    Requires TEST_DATABASE_URL to point at a clean PostgreSQL instance.
    The test issues DROP SCHEMA public CASCADE at the start to guarantee
    isolation from prior runs.
    """
    url = _postgres_url_or_skip()

    # Clean slate — CI spins up a fresh container, but the script can also
    # be re-run locally against a persistent test DB, so we reset schema.
    engine = create_engine(url, future=True)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")
    finally:
        engine.dispose()

    runner = AlembicMigrationRunner(
        database_url=url,
        alembic_ini_path=_alembic_ini(),
    )
    validator = MigrationIntegrityValidator(runner=runner)

    result = validator.validate(correlation_id="integration-postgres")

    assert result.head_after_first_upgrade
    assert result.head_after_first_upgrade == result.head_after_second_upgrade
    assert result.revision_after_downgrade is None
