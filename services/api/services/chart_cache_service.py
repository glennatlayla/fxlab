"""
Chart cache service implementation with SQL backend and TTL-based eviction (M14-T9 Gap 4).

Responsibilities:
- Retrieve cached chart data or compute and cache on miss.
- Manage cache lifecycle: TTL-based expiration, invalidation, eviction cleanup.
- Serialize/deserialize chart data to/from JSON.

Does NOT:
- Compute chart data (that is the caller's responsibility via compute_fn).
- Apply business logic beyond cache logic.
- Perform downsampling or other transformations.

Dependencies:
- sqlalchemy.orm.Session: Database connection (injected).
- libs.contracts.models.ChartCache: ORM model for cache table.
- datetime: Timestamp management.
- structlog: Structured logging.

Error conditions:
- All methods may raise SQLAlchemy exceptions on database I/O failure.

Example:
    from services.api.db import SessionLocal
    from services.api.services.chart_cache_service import ChartCacheService

    db = SessionLocal()
    cache = ChartCacheService(db=db)
    data = cache.get_or_compute(
        run_id="01HQ...",
        chart_type="equity_curve",
        compute_fn=lambda: expensive_computation(),
        ttl_seconds=3600,
    )
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.orm import Session

from libs.contracts.models import ChartCache
from services.api.services.interfaces.chart_cache_service_interface import (
    ChartCacheServiceInterface,
)

logger = structlog.get_logger(__name__)


class ChartCacheService(ChartCacheServiceInterface):
    """
    SQL-backed chart cache with TTL-based eviction.

    Responsibilities:
    - Query cache table for valid (non-expired) entries.
    - Call compute_fn on cache miss or expiration.
    - Store computed results with TTL-derived expires_at timestamp.
    - Provide cache invalidation and eviction cleanup methods.

    Does NOT:
    - Perform chart computation beyond invoking the caller's compute_fn.
    - Apply downsampling or business logic.
    - Manage database transactions (caller is responsible).

    Dependencies:
    - SQLAlchemy Session (injected): Database connection.

    Error conditions:
    - SQLAlchemy exceptions raised on database I/O failure.

    Example:
        cache = ChartCacheService(db=session)
        points = cache.get_or_compute(
            run_id="01HQ...",
            chart_type="equity_curve",
            compute_fn=lambda: repo.find_equity_by_run_id(...),
            ttl_seconds=3600,
        )
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the chart cache service.

        Args:
            db: SQLAlchemy Session instance (injected by FastAPI Depends).

        Example:
            cache = ChartCacheService(db=get_db())
        """
        self.db = db

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

        If no valid entry exists or it has expired, call compute_fn(), cache
        the result with the given TTL, and return it.

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
        cache_key = f"{run_id}:{chart_type}"
        now = datetime.utcnow()

        # Attempt to fetch valid (non-expired) cache entry
        entry = self.db.query(ChartCache).filter(ChartCache.cache_key == cache_key).first()

        if entry is not None and entry.expires_at > now:
            # Cache hit: return cached data
            logger.debug(
                "cache.hit",
                cache_key=cache_key,
                run_id=run_id,
                chart_type=chart_type,
                component="chart_cache",
            )
            return entry.data

        # Cache miss or expiration: compute and store
        logger.debug(
            "cache.miss",
            cache_key=cache_key,
            run_id=run_id,
            chart_type=chart_type,
            reason="not_found" if entry is None else "expired",
            component="chart_cache",
        )

        computed_data = compute_fn()

        # Create or update cache entry
        expires_at = now + timedelta(seconds=ttl_seconds)

        if entry is not None:
            # Update existing entry
            entry.data = computed_data
            entry.created_at = now
            entry.expires_at = expires_at
        else:
            # Create new entry
            entry = ChartCache(
                cache_key=cache_key,
                run_id=run_id,
                chart_type=chart_type,
                data=computed_data,
                created_at=now,
                expires_at=expires_at,
            )
            self.db.add(entry)

        self.db.commit()

        logger.debug(
            "cache.stored",
            cache_key=cache_key,
            run_id=run_id,
            chart_type=chart_type,
            ttl_seconds=ttl_seconds,
            expires_at=expires_at.isoformat(),
            component="chart_cache",
        )

        return computed_data

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
        count = self.db.query(ChartCache).filter(ChartCache.run_id == run_id).delete()
        self.db.commit()

        logger.debug(
            "cache.invalidated",
            run_id=run_id,
            entries_deleted=count,
            component="chart_cache",
        )

    def eviction_cleanup(self) -> None:
        """
        Purge all expired cache entries.

        Deletes all cache entries where expires_at <= now.
        Intended to be called periodically (e.g., via a background task).

        Example:
            cache.eviction_cleanup()  # Runs in a scheduled background job.
        """
        now = datetime.utcnow()
        count = self.db.query(ChartCache).filter(ChartCache.expires_at <= now).delete()
        self.db.commit()

        logger.debug(
            "cache.eviction_cleanup",
            entries_deleted=count,
            now=now.isoformat(),
            component="chart_cache",
        )
