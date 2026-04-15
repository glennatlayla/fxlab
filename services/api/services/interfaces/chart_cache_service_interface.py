"""
Chart cache service interface (M14-T9: SQL cache with TTL-based eviction).

Purpose:
    Define the abstract contract for a chart data cache with TTL-based eviction.
    Decouples chart routes and services from the concrete caching implementation.

Responsibilities:
    - Declare abstract methods for cache retrieval with compute fallback.
    - Declare cache invalidation and eviction cleanup methods.
    - Enable in-memory mock substitution in unit tests via dependency injection.

Does NOT:
    - Execute SQL or perform I/O.
    - Compute chart data (that is the route/service layer's responsibility).
    - Contain business logic.

Dependencies:
    - typing: Callable, Any.

Error conditions:
    - No exceptions raised by interface (implementation may raise on I/O failure).

Example:
    cache: ChartCacheServiceInterface = SqlChartCacheService(db=session)
    data = cache.get_or_compute(
        run_id="run_123",
        chart_type="equity_curve",
        compute_fn=lambda: expensive_computation(),
        ttl_seconds=3600,
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class ChartCacheServiceInterface(ABC):
    """
    Port interface for chart cache management with TTL-based eviction.

    Implementations:
    - SqlChartCacheService     — SQL (SQLAlchemy) backed, for production.
    - MockChartCacheService    — in-memory, for unit tests.
    """

    @abstractmethod
    def get_or_compute(
        self,
        run_id: str,
        chart_type: str,
        compute_fn: Callable[[], Any],
        ttl_seconds: int = 3600,
    ) -> Any:
        """
        Return cached chart data or compute and cache it.

        If a valid (non-expired) cache entry exists for (run_id, chart_type),
        return it without calling compute_fn.

        If no valid entry exists, call compute_fn(), cache the result with
        the given TTL, and return it.

        Args:
            run_id:        ULID of the run whose chart is requested.
            chart_type:    Chart type identifier (e.g., "equity_curve", "drawdown").
            compute_fn:    Callable returning chart data when cache misses.
                           Must return a JSON-serializable dict or list.
            ttl_seconds:   Time-to-live in seconds. Defaults to 1 hour (3600).

        Returns:
            Chart data (typically a dict with points, metadata, etc).

        Example:
            data = cache.get_or_compute(
                run_id="01HQ...",
                chart_type="equity_curve",
                compute_fn=lambda: repo.find_equity_by_run_id(...),
                ttl_seconds=3600,
            )
        """
        ...

    @abstractmethod
    def invalidate(self, run_id: str) -> None:
        """
        Invalidate all cache entries for a specific run.

        Clears all cached chart data (all chart types) for the given run_id.
        Used when a run's data changes and cached derivatives are stale.

        Args:
            run_id: ULID of the run whose cache should be cleared.

        Example:
            cache.invalidate("01HQ...")  # Clears equity, drawdown, etc for this run.
        """
        ...

    @abstractmethod
    def eviction_cleanup(self) -> None:
        """
        Purge all expired cache entries.

        Deletes all cache entries where expires_at <= now.
        Intended to be called periodically (e.g., via a background task).

        Example:
            cache.eviction_cleanup()  # Runs in a scheduled background job.
        """
        ...
