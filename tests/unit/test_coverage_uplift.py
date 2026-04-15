"""
Coverage uplift tests for uncovered code paths.

Targets files with highest uncovered line counts that are
easiest to exercise: main.py lifespan, parity repo, feed health repo,
and dependency health repo.

Example:
    pytest tests/unit/test_coverage_uplift.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import ulid as _ulid_mod
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from libs.contracts.models import Base

# ---------------------------------------------------------------------------
# Shared fixture: in-memory SQLite session for coverage-focused tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mem_session():
    """Provide an in-memory SQLite session with all tables created."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# SqlParity repository — exercise query and filter paths
# ---------------------------------------------------------------------------


class TestSqlParityRepositoryFilterPaths:
    """Cover the filter branches in SqlParityRepository.list()."""

    def test_list_with_severity_filter(self, mem_session):
        """list() with severity filter exercises the severity WHERE clause."""
        from services.api.repositories.sql_parity_repository import SqlParityRepository

        repo = SqlParityRepository(db=mem_session)
        result = repo.list(severity="critical", correlation_id="corr-uplift-01")
        assert isinstance(result, list)
        assert len(result) == 0  # Empty DB should return empty list

    def test_list_with_instrument_filter(self, mem_session):
        """list() with instrument filter exercises the instrument WHERE clause."""
        from services.api.repositories.sql_parity_repository import SqlParityRepository

        repo = SqlParityRepository(db=mem_session)
        result = repo.list(instrument="EURUSD", correlation_id="corr-uplift-02")
        assert isinstance(result, list)
        assert len(result) == 0  # Empty DB should return empty list

    def test_list_with_feed_id_filter(self, mem_session):
        """list() with feed_id filter exercises the feed_id WHERE clause."""
        from services.api.repositories.sql_parity_repository import SqlParityRepository

        repo = SqlParityRepository(db=mem_session)
        result = repo.list(feed_id=str(_ulid_mod.ULID()), correlation_id="corr-uplift-03")
        assert isinstance(result, list)
        assert len(result) == 0  # Empty DB should return empty list

    def test_list_with_all_filters(self, mem_session):
        """list() with all filters combined."""
        from services.api.repositories.sql_parity_repository import SqlParityRepository

        repo = SqlParityRepository(db=mem_session)
        result = repo.list(
            severity="warning",
            instrument="GBPUSD",
            feed_id=str(_ulid_mod.ULID()),
            correlation_id="corr-uplift-04",
        )
        assert isinstance(result, list)
        assert len(result) == 0  # Empty DB should return empty list

    def test_summarize_returns_list(self, mem_session):
        """summarize() exercises the aggregation query path."""
        from services.api.repositories.sql_parity_repository import SqlParityRepository

        repo = SqlParityRepository(db=mem_session)
        result = repo.summarize(correlation_id="corr-uplift-05")
        assert isinstance(result, list)
        assert len(result) == 0  # Empty DB should return empty list of summaries


# ---------------------------------------------------------------------------
# SqlFeedHealth repository — exercise the health event query path
# ---------------------------------------------------------------------------


class TestSqlFeedHealthCoveragePaths:
    """Cover the health event query paths in SqlFeedHealthRepository."""

    def test_get_all_health_with_feeds(self, mem_session):
        """get_all_health() with feeds exercises the per-feed iteration."""
        from libs.contracts.models import Feed
        from services.api.repositories.sql_feed_health_repository import (
            SqlFeedHealthRepository,
        )

        # Insert a feed
        feed = Feed(
            id=str(_ulid_mod.ULID()),
            name="test-health-feed",
            feed_type="price",
            source="test",
            is_active=True,
        )
        mem_session.add(feed)
        mem_session.flush()

        repo = SqlFeedHealthRepository(db=mem_session)
        result = repo.get_all_health(correlation_id="corr-uplift-06")
        assert result is not None
        assert len(result.feeds) >= 1

    def test_get_health_with_health_events(self, mem_session):
        """get_health_by_feed_id() with health events exercises the event mapping."""
        from libs.contracts.models import Feed, FeedHealthEvent
        from services.api.repositories.sql_feed_health_repository import (
            SqlFeedHealthRepository,
        )

        feed = Feed(
            id=str(_ulid_mod.ULID()),
            name="test-events-feed",
            feed_type="price",
            source="test",
            is_active=True,
        )
        mem_session.add(feed)
        mem_session.flush()

        # Add a health event
        event = FeedHealthEvent(
            id=str(_ulid_mod.ULID()),
            feed_id=feed.id,
            status="healthy",
            checked_at=datetime.now(tz=timezone.utc),
            details={"latency_ms": 50},
        )
        mem_session.add(event)
        mem_session.flush()

        repo = SqlFeedHealthRepository(db=mem_session)
        result = repo.get_health_by_feed_id(feed_id=feed.id, correlation_id="corr-uplift-07")
        assert result is not None

    def test_get_health_not_found(self, mem_session):
        """get_health_by_feed_id() raises NotFoundError for missing feed."""
        from libs.contracts.errors import NotFoundError
        from services.api.repositories.sql_feed_health_repository import (
            SqlFeedHealthRepository,
        )

        repo = SqlFeedHealthRepository(db=mem_session)
        with pytest.raises(NotFoundError):
            repo.get_health_by_feed_id(
                feed_id="01HNOTEXIST0000000000000000",
                correlation_id="corr-uplift-08",
            )


# ---------------------------------------------------------------------------
# RealDependencyHealthRepository — exercise check paths
# ---------------------------------------------------------------------------


class TestRealDependencyHealthCoveragePaths:
    """Cover the health check paths in RealDependencyHealthRepository."""

    def test_snapshot_returns_result(self):
        """snapshot() exercises the database ping and dependency check paths."""
        from services.api.repositories.real_dependency_health_repository import (
            RealDependencyHealthRepository,
        )

        repo = RealDependencyHealthRepository()
        result = repo.check(correlation_id="corr-uplift-09")
        assert result is not None


# ---------------------------------------------------------------------------
# CeleryQueueRepository — exercise list and status paths
# ---------------------------------------------------------------------------


class TestCeleryQueueCoveragePaths:
    """Cover CeleryQueueRepository paths (graceful degradation when no Celery)."""

    def test_list_without_celery(self):
        """list() returns empty/degraded result when Celery/Redis is unavailable."""
        from services.api.repositories.celery_queue_repository import (
            CeleryQueueRepository,
        )

        repo = CeleryQueueRepository()
        result = repo.list(correlation_id="corr-uplift-10")
        assert isinstance(result, list)
        assert len(result) == 0  # When Celery unavailable, returns empty list


# ---------------------------------------------------------------------------
# Main app — lifespan and pydantic check
# ---------------------------------------------------------------------------


class TestMainAppLifespan:
    """Cover the main.py lifespan startup code."""

    def test_pydantic_core_check_runs(self):
        """_check_pydantic_core() executes without exception."""
        from services.api.main import _check_pydantic_core

        # Should not raise — just logs a warning or info
        _check_pydantic_core()

    def test_app_has_correct_title(self):
        """App metadata is set correctly."""
        from services.api.main import app

        assert app.title == "FXLab Phase 3 API"

    def test_app_has_cors_middleware(self):
        """CORS middleware is registered."""
        from services.api.main import app

        middleware_classes = [m.cls.__name__ for m in app.user_middleware if hasattr(m, "cls")]
        assert "CORSMiddleware" in middleware_classes

    def test_app_has_rate_limit_middleware(self):
        """RateLimitMiddleware is registered."""
        from services.api.main import app

        middleware_classes = [m.cls.__name__ for m in app.user_middleware if hasattr(m, "cls")]
        assert "RateLimitMiddleware" in middleware_classes


# ---------------------------------------------------------------------------
# Error hierarchy — cover the exception classes themselves
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    """Cover libs.contracts.errors exception hierarchy."""

    def test_all_errors_inherit_from_fxlab_error(self):
        """All custom errors inherit from FXLabError."""
        from libs.contracts.errors import (
            AuthError,
            ConfigError,
            ExternalServiceError,
            FXLabError,
            NotFoundError,
            SeparationOfDutiesError,
            TransientError,
            ValidationError,
        )

        for cls in [
            NotFoundError,
            ValidationError,
            SeparationOfDutiesError,
            AuthError,
            ExternalServiceError,
            TransientError,
            ConfigError,
        ]:
            assert issubclass(cls, FXLabError), f"{cls.__name__} must inherit FXLabError"

    def test_transient_error_inherits_external(self):
        """TransientError is a subclass of ExternalServiceError."""
        from libs.contracts.errors import ExternalServiceError, TransientError

        assert issubclass(TransientError, ExternalServiceError)

    def test_errors_carry_message(self):
        """Custom errors carry their message string."""
        from libs.contracts.errors import NotFoundError

        err = NotFoundError("item X not found")
        assert str(err) == "item X not found"
