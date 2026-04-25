"""
Unit tests for MockChartCacheService (libs.contracts.mocks.mock_chart_cache_service).

Tests verify:
- get_or_compute() caches data and respects TTL.
- Cache hits return data without calling compute_fn.
- Cache misses call compute_fn and cache the result.
- Expired entries are treated as cache misses.
- invalidate() clears all entries for a run_id.
- eviction_cleanup() purges expired entries.
- Introspection helpers (get_cache_size, get_entry, clear) work correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from libs.contracts.mocks.mock_chart_cache_service import MockChartCacheService


class TestMockChartCacheServiceGetOrCompute:
    """Tests for get_or_compute() method."""

    def test_get_or_compute_cache_miss_calls_compute_fn(self) -> None:
        """
        When cache key does not exist, compute_fn is called.

        Scenario:
        - Empty cache.
        - Call get_or_compute with a compute_fn.

        Expected:
        - compute_fn is called exactly once.
        - Result is returned.
        """
        cache = MockChartCacheService()
        compute_fn = MagicMock(return_value={"data": [1, 2, 3]})

        result = cache.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn,
            ttl_seconds=3600,
        )

        assert result == {"data": [1, 2, 3]}
        compute_fn.assert_called_once()

    def test_get_or_compute_cache_hit_does_not_call_compute_fn(self) -> None:
        """
        When cache entry exists and is not expired, compute_fn is not called.

        Scenario:
        - Pre-populate cache with valid entry.
        - Call get_or_compute with same cache key.

        Expected:
        - compute_fn is NOT called.
        - Cached data is returned.
        """
        cache = MockChartCacheService()
        cached_data = {"data": [1, 2, 3]}

        # First call: populate cache
        compute_fn_1 = MagicMock(return_value=cached_data)
        result_1 = cache.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn_1,
            ttl_seconds=3600,
        )
        assert result_1 == cached_data

        # Second call: should hit cache
        compute_fn_2 = MagicMock(return_value={"data": [4, 5, 6]})
        result_2 = cache.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn_2,
            ttl_seconds=3600,
        )

        assert result_2 == cached_data  # Still the cached data
        compute_fn_2.assert_not_called()

    def test_get_or_compute_stores_entry_in_cache(self) -> None:
        """
        get_or_compute stores the result in the cache store.

        Scenario:
        - Call get_or_compute on empty cache.

        Expected:
        - Entry is stored with correct cache_key.
        - Entry has data, created_at, expires_at.
        """
        cache = MockChartCacheService()
        compute_fn = MagicMock(return_value={"points": [1, 2]})

        cache.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn,
            ttl_seconds=3600,
        )

        entry = cache.get_entry("run_123", "equity_curve")
        assert entry is not None
        assert entry["data"] == {"points": [1, 2]}
        assert entry["created_at"] is not None
        assert entry["expires_at"] is not None

    def test_get_or_compute_respects_ttl_seconds(self) -> None:
        """
        Entries cached with different TTLs have different expiration times.

        Scenario:
        - Cache entry with TTL 3600 seconds.
        - Cache entry with TTL 300 seconds.

        Expected:
        - Expiration times differ by ~55 minutes.
        """
        cache = MockChartCacheService()

        # First entry: TTL 3600 (1 hour)
        cache.get_or_compute(
            run_id="run_1",
            chart_type="type_a",
            compute_fn=MagicMock(return_value={"a": 1}),
            ttl_seconds=3600,
        )
        entry_1 = cache.get_entry("run_1", "type_a")
        expires_1 = entry_1["expires_at"]

        # Second entry: TTL 300 (5 minutes)
        cache.get_or_compute(
            run_id="run_2",
            chart_type="type_b",
            compute_fn=MagicMock(return_value={"b": 2}),
            ttl_seconds=300,
        )
        entry_2 = cache.get_entry("run_2", "type_b")
        expires_2 = entry_2["expires_at"]

        # Verify significant difference in expiration
        diff_seconds = (expires_1 - expires_2).total_seconds()
        assert abs(diff_seconds) > 3000  # ~55 min difference


class TestMockChartCacheServiceExpiration:
    """Tests for cache expiration behavior."""

    def test_expired_entry_is_treated_as_cache_miss(self) -> None:
        """
        When cache entry has expired, it is treated as a cache miss.

        Scenario:
        - Pre-populate cache with expired entry.
        - Call get_or_compute with same cache key.

        Expected:
        - compute_fn IS called (cache miss).
        - New data is returned and cached.
        """
        cache = MockChartCacheService()

        # Manually insert an expired entry (bypass get_or_compute)
        now = datetime.now(UTC)
        cache._store["run_123:equity_curve"] = {
            "data": {"old": "data"},
            "created_at": now - timedelta(hours=2),
            "expires_at": now - timedelta(hours=1),  # EXPIRED
        }

        # Call get_or_compute: should treat as cache miss
        new_data = {"new": "data"}
        compute_fn = MagicMock(return_value=new_data)

        result = cache.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=compute_fn,
            ttl_seconds=3600,
        )

        assert result == new_data
        compute_fn.assert_called_once()

        # Verify cache was updated
        entry = cache.get_entry("run_123", "equity_curve")
        assert entry["data"] == new_data
        assert entry["expires_at"] > now


class TestMockChartCacheServiceInvalidate:
    """Tests for invalidate() method."""

    def test_invalidate_removes_all_entries_for_run_id(self) -> None:
        """
        invalidate(run_id) removes all cache entries for that run_id.

        Scenario:
        - Populate cache with multiple entries for same run_id (different chart types).
        - Call invalidate(run_id).

        Expected:
        - All entries for that run_id are deleted.
        - Entries for other run_ids are NOT affected.
        """
        cache = MockChartCacheService()

        # Populate cache with entries for run_123 and run_456
        for run_id, chart_type in [
            ("run_123", "equity_curve"),
            ("run_123", "drawdown"),
            ("run_456", "equity_curve"),
        ]:
            cache.get_or_compute(
                run_id=run_id,
                chart_type=chart_type,
                compute_fn=MagicMock(return_value={"a": 1}),
                ttl_seconds=3600,
            )

        assert cache.get_cache_size() == 3

        # Invalidate run_123
        cache.invalidate("run_123")

        # Verify run_123 entries are deleted
        assert cache.get_entry("run_123", "equity_curve") is None
        assert cache.get_entry("run_123", "drawdown") is None

        # Verify run_456 entry is NOT affected
        assert cache.get_entry("run_456", "equity_curve") is not None
        assert cache.get_cache_size() == 1

    def test_invalidate_nonexistent_run_id_does_not_raise(self) -> None:
        """
        invalidate(run_id) with non-existent run_id is a no-op (no error).

        Scenario:
        - Cache has entries for run_123.
        - Call invalidate("run_999").

        Expected:
        - No exception is raised.
        - Existing entries are not affected.
        """
        cache = MockChartCacheService()
        cache.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=MagicMock(return_value={"a": 1}),
            ttl_seconds=3600,
        )

        # Should not raise
        cache.invalidate("run_999")

        # Verify run_123 entry is still there
        assert cache.get_entry("run_123", "equity_curve") is not None


class TestMockChartCacheServiceEvictionCleanup:
    """Tests for eviction_cleanup() method."""

    def test_eviction_cleanup_removes_expired_entries(self) -> None:
        """
        eviction_cleanup() deletes all expired entries.

        Scenario:
        - Populate cache with mix of valid and expired entries.
        - Call eviction_cleanup().

        Expected:
        - Expired entries are deleted.
        - Valid entries are NOT affected.
        """
        cache = MockChartCacheService()
        now = datetime.now(UTC)

        # Insert valid entry
        cache._store["run_1:valid"] = {
            "data": {"valid": True},
            "created_at": now,
            "expires_at": now + timedelta(hours=1),
        }

        # Insert expired entry
        cache._store["run_2:expired"] = {
            "data": {"expired": True},
            "created_at": now - timedelta(hours=2),
            "expires_at": now - timedelta(hours=1),
        }

        assert cache.get_cache_size() == 2

        # Run cleanup
        cache.eviction_cleanup()

        # Verify only valid entry remains
        assert cache.get_cache_size() == 1
        assert cache._store["run_1:valid"]["data"] == {"valid": True}
        assert "run_2:expired" not in cache._store

    def test_eviction_cleanup_preserves_valid_entries(self) -> None:
        """
        eviction_cleanup() does not affect valid (not-yet-expired) entries.

        Scenario:
        - Multiple valid entries.
        - Call eviction_cleanup().

        Expected:
        - All entries remain.
        """
        cache = MockChartCacheService()
        now = datetime.now(UTC)

        # Insert multiple valid entries
        for i in range(5):
            cache._store[f"run_{i}:chart"] = {
                "data": {"i": i},
                "created_at": now,
                "expires_at": now + timedelta(hours=1),
            }

        cache.eviction_cleanup()

        # All should remain
        assert cache.get_cache_size() == 5


class TestMockChartCacheServiceIntrospection:
    """Tests for introspection helper methods."""

    def test_get_cache_size_returns_entry_count(self) -> None:
        """
        get_cache_size() returns the number of cache entries.

        Scenario:
        - Populate cache with 3 entries.

        Expected:
        - get_cache_size() returns 3.
        """
        cache = MockChartCacheService()
        for i in range(3):
            cache.get_or_compute(
                run_id=f"run_{i}",
                chart_type="equity_curve",
                compute_fn=MagicMock(return_value={"i": i}),
                ttl_seconds=3600,
            )

        assert cache.get_cache_size() == 3

    def test_get_entry_returns_none_for_nonexistent_entry(self) -> None:
        """
        get_entry() returns None when cache key does not exist.

        Scenario:
        - Cache does not have the requested key.

        Expected:
        - get_entry() returns None.
        """
        cache = MockChartCacheService()
        entry = cache.get_entry("run_999", "nonexistent")
        assert entry is None

    def test_get_entry_returns_full_entry_dict(self) -> None:
        """
        get_entry() returns the full entry dict with data, created_at, expires_at.

        Scenario:
        - Populate cache with an entry.
        - Call get_entry().

        Expected:
        - Returns dict with 'data', 'created_at', 'expires_at' keys.
        """
        cache = MockChartCacheService()
        cache.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=MagicMock(return_value={"points": [1, 2, 3]}),
            ttl_seconds=3600,
        )

        entry = cache.get_entry("run_123", "equity_curve")
        assert entry is not None
        assert "data" in entry
        assert "created_at" in entry
        assert "expires_at" in entry
        assert entry["data"] == {"points": [1, 2, 3]}

    def test_clear_removes_all_entries(self) -> None:
        """
        clear() removes all entries from the cache.

        Scenario:
        - Populate cache with multiple entries.
        - Call clear().

        Expected:
        - Cache is empty (size == 0).
        """
        cache = MockChartCacheService()
        for i in range(5):
            cache.get_or_compute(
                run_id=f"run_{i}",
                chart_type="equity_curve",
                compute_fn=MagicMock(return_value={"i": i}),
                ttl_seconds=3600,
            )

        assert cache.get_cache_size() == 5

        cache.clear()

        assert cache.get_cache_size() == 0
