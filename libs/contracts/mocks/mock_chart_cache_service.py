"""
Mock chart cache service for unit testing.

Purpose:
    Provide an in-memory, controllable implementation of ChartCacheServiceInterface
    for unit tests that need chart caching without database I/O.

Responsibilities:
    - Store cached data in an in-memory dictionary.
    - Support TTL-based expiration using a simple timestamp mechanism.
    - Provide introspection helpers for test assertions.

Does NOT:
    - Perform actual database I/O.
    - Handle real SQLAlchemy transactions.

Dependencies:
    - services.api.services.interfaces.chart_cache_service_interface: Interface.
    - datetime: Timestamp management.

Example:
    cache = MockChartCacheService()
    result = cache.get_or_compute(
        run_id="run_123",
        chart_type="equity_curve",
        compute_fn=lambda: {"points": [1, 2, 3]},
        ttl_seconds=3600,
    )
    assert cache.get_cache_size() == 1
    cache.invalidate("run_123")
    assert cache.get_cache_size() == 0
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from services.api.services.interfaces.chart_cache_service_interface import (
    ChartCacheServiceInterface,
)


class MockChartCacheService(ChartCacheServiceInterface):
    """
    In-memory mock implementation of ChartCacheServiceInterface.

    Stores cache entries in a dictionary keyed by cache_key.
    Each entry has: data, created_at, expires_at.

    Useful for unit tests that need cache behavior without database overhead.

    Example:
        cache = MockChartCacheService()
        data = cache.get_or_compute(
            run_id="run_123",
            chart_type="equity_curve",
            compute_fn=expensive_computation,
        )
    """

    def __init__(self) -> None:
        """Initialize the mock cache with an empty store."""
        self._store: dict[str, dict[str, Any]] = {}

    def get_or_compute(
        self,
        run_id: str,
        chart_type: str,
        compute_fn: Callable[[], Any],
        ttl_seconds: int = 3600,
    ) -> Any:
        """
        Return cached chart data or compute and cache it.

        Args:
            run_id:        Run ULID.
            chart_type:    Chart type identifier.
            compute_fn:    Callable that computes the chart data.
            ttl_seconds:   Time-to-live in seconds.

        Returns:
            Chart data (from cache or freshly computed).
        """
        cache_key = f"{run_id}:{chart_type}"
        now = datetime.now(UTC)

        # Check for valid (non-expired) cache entry
        if cache_key in self._store:
            entry = self._store[cache_key]
            if entry["expires_at"] > now:
                return entry["data"]

        # Cache miss or expiration: compute and store
        computed_data = compute_fn()
        expires_at = now + timedelta(seconds=ttl_seconds)

        self._store[cache_key] = {
            "data": computed_data,
            "created_at": now,
            "expires_at": expires_at,
        }

        return computed_data

    def invalidate(self, run_id: str) -> None:
        """
        Invalidate all cache entries for a specific run.

        Args:
            run_id: Run ULID whose cache should be cleared.
        """
        keys_to_delete = [k for k in self._store if k.startswith(f"{run_id}:")]
        for key in keys_to_delete:
            del self._store[key]

    def eviction_cleanup(self) -> None:
        """
        Purge all expired cache entries.

        Deletes entries where expires_at <= now.
        """
        now = datetime.now(UTC)
        expired_keys = [k for k, v in self._store.items() if v["expires_at"] <= now]
        for key in expired_keys:
            del self._store[key]

    # =========================================================================
    # Introspection helpers for tests
    # =========================================================================

    def get_cache_size(self) -> int:
        """
        Return the number of entries currently in the cache.

        Returns:
            Entry count.

        Example:
            assert cache.get_cache_size() == 2
        """
        return len(self._store)

    def get_entry(self, run_id: str, chart_type: str) -> dict[str, Any] | None:
        """
        Return a cache entry for inspection (test assertion).

        Args:
            run_id:     Run ULID.
            chart_type: Chart type.

        Returns:
            Cache entry dict (data, created_at, expires_at) or None if not cached.

        Example:
            entry = cache.get_entry("run_123", "equity_curve")
            assert entry["data"] == {"points": [...]}
        """
        cache_key = f"{run_id}:{chart_type}"
        return self._store.get(cache_key)

    def clear(self) -> None:
        """
        Clear all cache entries (useful for test isolation).

        Example:
            cache.clear()  # Between tests
        """
        self._store.clear()
