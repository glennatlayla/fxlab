"""
Unit tests for chart cache service (M14-T9: SQL cache with TTL-based eviction).

Responsibilities:
- Test cache miss → compute_fn called → result cached and returned.
- Test cache hit → compute_fn NOT called → cached result returned.
- Test expired entry → treated as cache miss → compute_fn called again.
- Test invalidate clears all cache entries for a run_id.
- Test eviction purges expired entries.

Uses in-memory SQLite for test isolation (no transactional overhead).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import Base, ChartCache
from services.api.services.chart_cache_service import ChartCacheService


@pytest.fixture
def test_db() -> Session:
    """
    In-memory SQLite database for chart cache tests.

    Creates all tables, yields an active session, then tears down on completion.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def cache_service(test_db: Session) -> ChartCacheService:
    """Provide a ChartCacheService bound to the test database."""
    return ChartCacheService(db=test_db)


class TestChartCacheMiss:
    """Test cache miss behavior: compute_fn is called and result is cached."""

    def test_cache_miss_calls_compute_fn(
        self,
        cache_service: ChartCacheService,
    ) -> None:
        """
        When cache key does not exist, compute_fn is called and result cached.

        Scenario:
        - Cache key "run_123:equity_curve" does not exist.
        - compute_fn is provided.
        - Call get_or_compute(...).

        Expected:
        - compute_fn is called exactly once.
        - Result is returned.
        - Result is stored in cache.
        """
        compute_fn = MagicMock(return_value={"points": [1, 2, 3]})

        result = cache_service.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn,
            ttl_seconds=3600,
        )

        assert result == {"points": [1, 2, 3]}
        compute_fn.assert_called_once()

    def test_cache_miss_stores_result_in_db(
        self,
        cache_service: ChartCacheService,
        test_db: Session,
    ) -> None:
        """
        When cache miss occurs, result is stored in database for future hits.

        Scenario:
        - Cache key does not exist.
        - compute_fn returns data.
        - Call get_or_compute(...).

        Expected:
        - ChartCache is created in the database.
        - cache_key, run_id, chart_type, and data JSON are populated.
        - created_at and expires_at are set.
        """
        compute_fn = MagicMock(return_value={"points": [1, 2, 3]})

        cache_service.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn,
            ttl_seconds=3600,
        )

        # Verify cache entry was created
        entry = (
            test_db.query(ChartCache).filter_by(run_id="run_123", chart_type="equity_curve").first()
        )
        assert entry is not None
        assert entry.cache_key == "run_123:equity_curve"
        assert entry.data == {"points": [1, 2, 3]}
        assert entry.expires_at is not None


class TestChartCacheHit:
    """Test cache hit behavior: compute_fn is NOT called, cached result is returned."""

    def test_cache_hit_does_not_call_compute_fn(
        self,
        cache_service: ChartCacheService,
        test_db: Session,
    ) -> None:
        """
        When cache entry exists and is not expired, compute_fn is not called.

        Scenario:
        - Pre-populate cache with a valid entry.
        - Call get_or_compute with same cache key.

        Expected:
        - compute_fn is NOT called.
        - Cached data is returned.
        """
        # Pre-populate cache
        entry = ChartCache(
            cache_key="run_123:equity_curve",
            run_id="run_123",
            chart_type="equity_curve",
            data={"points": [1, 2, 3]},
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        test_db.add(entry)
        test_db.commit()

        compute_fn = MagicMock()

        result = cache_service.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn,
            ttl_seconds=3600,
        )

        assert result == {"points": [1, 2, 3]}
        compute_fn.assert_not_called()

    def test_cache_hit_returns_exact_cached_data(
        self,
        cache_service: ChartCacheService,
        test_db: Session,
    ) -> None:
        """
        Cache hit returns the exact data that was cached.

        Scenario:
        - Cache entry with complex nested data structure.
        - Call get_or_compute with same key.

        Expected:
        - Returned data equals cached data (deep equality).
        """
        cached_data = {
            "points": [
                {"timestamp": "2026-01-01T00:00:00Z", "equity": 10000.0},
                {"timestamp": "2026-01-02T00:00:00Z", "equity": 10500.0},
            ],
            "sampling_applied": True,
            "raw_point_count": 50000,
        }

        entry = ChartCache(
            cache_key="run_123:equity_curve",
            run_id="run_123",
            chart_type="equity_curve",
            data=cached_data,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        test_db.add(entry)
        test_db.commit()

        compute_fn = MagicMock()

        result = cache_service.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn,
            ttl_seconds=3600,
        )

        assert result == cached_data


class TestChartCacheExpiration:
    """Test expired cache entries are treated as cache misses."""

    def test_expired_cache_entry_is_treated_as_miss(
        self,
        cache_service: ChartCacheService,
        test_db: Session,
    ) -> None:
        """
        When cache entry has expired, compute_fn is called (cache miss behavior).

        Scenario:
        - Pre-populate cache with an EXPIRED entry (expires_at in the past).
        - Call get_or_compute with same cache key.

        Expected:
        - compute_fn IS called (treated as cache miss).
        - New data is returned and cached.
        - expires_at is updated to future timestamp.
        """
        # Pre-populate cache with EXPIRED entry
        entry = ChartCache(
            cache_key="run_123:equity_curve",
            run_id="run_123",
            chart_type="equity_curve",
            data={"points": [1, 2, 3]},  # old data
            created_at=datetime.now(UTC) - timedelta(hours=2),
            expires_at=datetime.now(UTC) - timedelta(hours=1),  # expired!
        )
        test_db.add(entry)
        test_db.commit()

        compute_fn = MagicMock(return_value={"points": [4, 5, 6]})  # new data

        result = cache_service.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn,
            ttl_seconds=3600,
        )

        assert result == {"points": [4, 5, 6]}
        compute_fn.assert_called_once()

        # Verify cache was updated
        updated_entry = (
            test_db.query(ChartCache).filter_by(run_id="run_123", chart_type="equity_curve").first()
        )
        assert updated_entry.data == {"points": [4, 5, 6]}
        # ChartCache.expires_at is a naive DateTime column; the value comes
        # back from SQLite without tzinfo. Compare against naive UTC.
        assert updated_entry.expires_at > datetime.now(UTC).replace(tzinfo=None)


class TestChartCacheInvalidation:
    """Test invalidate() clears all cache entries for a run_id."""

    def test_invalidate_removes_all_entries_for_run_id(
        self,
        cache_service: ChartCacheService,
        test_db: Session,
    ) -> None:
        """
        invalidate(run_id) deletes all cache entries for that run_id.

        Scenario:
        - Pre-populate cache with multiple entries for same run_id (different chart types).
        - Call invalidate(run_id).

        Expected:
        - All entries for that run_id are deleted.
        - Entries for other run_ids are NOT affected.
        """
        # Pre-populate cache with multiple entries
        entry1 = ChartCache(
            cache_key="run_123:equity_curve",
            run_id="run_123",
            chart_type="equity_curve",
            data={"points": [1, 2, 3]},
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        entry2 = ChartCache(
            cache_key="run_123:drawdown",
            run_id="run_123",
            chart_type="drawdown",
            data={"points": [-0.1, -0.2]},
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        entry3 = ChartCache(
            cache_key="run_456:equity_curve",
            run_id="run_456",
            chart_type="equity_curve",
            data={"points": [10, 20]},
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        test_db.add_all([entry1, entry2, entry3])
        test_db.commit()

        # Invalidate run_123
        cache_service.invalidate("run_123")

        # Verify run_123 entries are deleted
        remaining = test_db.query(ChartCache).filter_by(run_id="run_123").all()
        assert len(remaining) == 0

        # Verify run_456 entries are NOT affected
        other_run_entries = test_db.query(ChartCache).filter_by(run_id="run_456").all()
        assert len(other_run_entries) == 1
        assert other_run_entries[0].cache_key == "run_456:equity_curve"


class TestChartCacheEviction:
    """Test eviction_cleanup() purges expired entries."""

    def test_eviction_cleanup_removes_expired_entries(
        self,
        cache_service: ChartCacheService,
        test_db: Session,
    ) -> None:
        """
        eviction_cleanup() deletes all expired cache entries.

        Scenario:
        - Pre-populate cache with mix of valid and expired entries.
        - Call eviction_cleanup().

        Expected:
        - Expired entries are deleted.
        - Valid entries are NOT affected.
        """
        # Pre-populate cache with mixed entries
        now = datetime.now(UTC)

        expired_entry = ChartCache(
            cache_key="run_123:equity_curve",
            run_id="run_123",
            chart_type="equity_curve",
            data={"points": [1, 2, 3]},
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),  # EXPIRED
        )
        valid_entry = ChartCache(
            cache_key="run_123:drawdown",
            run_id="run_123",
            chart_type="drawdown",
            data={"points": [-0.1, -0.2]},
            created_at=now,
            expires_at=now + timedelta(hours=1),  # VALID
        )
        test_db.add_all([expired_entry, valid_entry])
        test_db.commit()

        # Run eviction cleanup
        cache_service.eviction_cleanup()

        # Verify expired entry is deleted
        all_entries = test_db.query(ChartCache).all()
        assert len(all_entries) == 1
        assert all_entries[0].chart_type == "drawdown"

    def test_eviction_cleanup_does_not_affect_valid_entries(
        self,
        cache_service: ChartCacheService,
        test_db: Session,
    ) -> None:
        """
        eviction_cleanup() does not touch entries that haven't expired.

        Scenario:
        - Multiple valid (not-yet-expired) entries.
        - Call eviction_cleanup().

        Expected:
        - All entries remain.
        """
        now = datetime.now(UTC)

        entries = [
            ChartCache(
                cache_key=f"run_{i}:chart_{j}",
                run_id=f"run_{i}",
                chart_type=f"chart_{j}",
                data={"points": [1, 2]},
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
            for i in range(3)
            for j in range(2)
        ]
        test_db.add_all(entries)
        test_db.commit()

        cache_service.eviction_cleanup()

        remaining = test_db.query(ChartCache).all()
        assert len(remaining) == 6  # All entries remain


class TestChartCacheWithDifferentTTLs:
    """Test cache respects different TTL values."""

    def test_different_ttls_create_different_expiration_times(
        self,
        cache_service: ChartCacheService,
        test_db: Session,
    ) -> None:
        """
        Different TTL values result in different expiration times.

        Scenario:
        - Compute data with TTL 1 hour.
        - Compute data with TTL 5 minutes.

        Expected:
        - Both are cached.
        - Expiration times differ by ~55 minutes.
        """
        datetime.now(UTC)

        compute_fn = MagicMock(return_value={"points": [1, 2, 3]})

        cache_service.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn,
            ttl_seconds=3600,
        )

        entry1 = (
            test_db.query(ChartCache).filter_by(run_id="run_123", chart_type="equity_curve").first()
        )
        expires1 = entry1.expires_at

        # Invalidate and compute with different TTL
        cache_service.invalidate("run_123")

        cache_service.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn,
            ttl_seconds=300,
        )

        entry2 = (
            test_db.query(ChartCache).filter_by(run_id="run_123", chart_type="equity_curve").first()
        )
        expires2 = entry2.expires_at

        # Verify they have different expiration times
        # (should be ~55 min apart)
        diff = (expires1 - expires2).total_seconds()
        assert abs(diff) > 3000  # At least 50 minutes difference
