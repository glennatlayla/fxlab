"""
Unit test fixtures for FXLab Phase 3.

Provides shared fixtures for unit tests.
All fixtures must be fast and use mocks/stubs for external dependencies.
"""

from datetime import datetime
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import Base

# ---------------------------------------------------------------------------
# Phase 1 / Phase 2 legacy mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_phase1_artifact_store() -> Mock:
    """Mock Phase 1 artifact storage system."""
    store = MagicMock()
    store.store.return_value = "artifact-ulid-123"
    store.retrieve.return_value = b"mock-content"
    store.exists.return_value = True
    return store


@pytest.fixture
def mock_phase1_dataset_registry() -> Mock:
    """Mock Phase 1 dataset registry."""
    registry = MagicMock()
    registry.get_version.return_value = {
        "dataset_version_id": "dv-ulid-123",
        "status": "certified",
        "path": "/mock/path/data.parquet",
    }
    return registry


@pytest.fixture
def mock_phase1_audit_ledger() -> Mock:
    """Mock Phase 1 audit ledger."""
    ledger = MagicMock()
    ledger.record_event.return_value = "audit-event-ulid-123"
    return ledger


@pytest.fixture
def mock_phase1_queue() -> Mock:
    """Mock Phase 1 queue system."""
    queue = MagicMock()
    queue.enqueue.return_value = "job-ulid-123"
    queue.get_status.return_value = "pending"
    return queue


@pytest.fixture
def temp_project_root(tmp_path: Path) -> Generator[Path, None, None]:
    """Provide a temporary project root for file system tests."""
    (tmp_path / "services").mkdir()
    (tmp_path / "libs").mkdir()
    (tmp_path / "tests").mkdir()
    yield tmp_path


# ---------------------------------------------------------------------------
# DB mocks / in-memory DB
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session() -> Mock:
    """Mock SQLAlchemy session for unit tests."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_db_session() -> Mock:
    """Mock database session for unit tests."""
    session = Mock()
    session.commit = Mock()
    session.rollback = Mock()
    session.close = Mock()
    session.execute = Mock()
    session.scalar = Mock()
    return session


@pytest.fixture
def in_memory_db() -> Generator:
    """
    In-memory SQLite database for schema tests.

    Creates all tables from Base.metadata, yields an active session,
    then tears down on test completion.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Auth / RBAC mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_audit_service() -> Mock:
    """Mock audit service for unit tests."""
    service = Mock()
    service.log_event = AsyncMock()
    return service


@pytest.fixture
def mock_auth_context() -> Mock:
    """Mock authentication context."""
    context = Mock()
    context.user_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0V"
    context.role = "researcher"
    context.permissions = {"read:runs", "write:promotions"}
    return context


@pytest.fixture
def mock_rbac_service() -> Mock:
    """Mock RBAC service for unit tests."""
    service = MagicMock()
    service.can_request_promotion = MagicMock(return_value=True)
    return service


@pytest.fixture
def mock_rbac_service_forbidden() -> Mock:
    """Mock RBAC service that denies permission."""
    service = MagicMock()
    service.can_request_promotion = MagicMock(return_value=False)
    return service


# ---------------------------------------------------------------------------
# Utility fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_ulid() -> str:
    """Sample ULID for testing."""
    return "01HQZXYZ123456789ABCDEFGHJK"


@pytest.fixture
def sample_timestamp() -> datetime:
    """Sample timestamp for testing."""
    return datetime(2026, 3, 19, 12, 0, 0)
