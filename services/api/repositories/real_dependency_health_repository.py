"""
Real dependency health checker implementation (ISS-024).

Responsibilities:
- Check the health/reachability of all platform dependencies.
- Implement DependencyHealthRepositoryInterface with real connectivity checks.
- Each check has 2s timeout; gracefully fallback to degraded status on failure.

Does NOT:
- Contain classification logic (performed by the checker itself).
- Store health check history.
- Connect to dependencies on init (only on check() call).

Dependencies:
- DATABASE_URL environment variable (optional; checks database connectivity).
- REDIS_URL environment variable (optional; checks Redis connectivity).
- structlog: Structured logging.

Error conditions:
- Each dependency check has a 2s timeout and gracefully degrades to DOWN status.
- Never raises exceptions; always returns DependencyHealthResponse with status.

Example:
    from services.api.repositories.real_dependency_health_repository import RealDependencyHealthRepository

    repo = RealDependencyHealthRepository()
    response = repo.check(correlation_id="corr-1")
    # response.overall_status in ("OK", "DEGRADED", "DOWN")
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from typing import Any

import structlog

from libs.contracts.interfaces.dependency_health_repository import (
    DependencyHealthRepositoryInterface,
)
from libs.contracts.observability import DependencyHealthRecord, DependencyHealthResponse

logger = structlog.get_logger(__name__)

# Timeout for each dependency check (seconds)
_CHECK_TIMEOUT = 2.0


class RealDependencyHealthRepository(DependencyHealthRepositoryInterface):
    """
    Real connectivity checker for platform dependencies.

    Responsibilities:
    - Check database (via SELECT 1).
    - Check Redis (via PING).
    - Check artifact store (local or MinIO).
    - Check feed health table (via query).
    - Each check has 2s timeout and gracefully degrades to DOWN status.

    Does NOT:
    - Contain classification logic.
    - Store history or perform trend analysis.
    - Connect on init (only on check() call).

    Dependencies:
    - DATABASE_URL (optional): PostgreSQL or SQLite connection string.
    - REDIS_URL (optional): Redis connection string.

    Error conditions:
    - Each dependency timeout returns DOWN status (not exception).
    - All dependencies DOWN returns overall status "DOWN".
    - Some DOWN returns overall status "DEGRADED".
    - All UP returns overall status "OK".

    Example:
        repo = RealDependencyHealthRepository()
        response = repo.check(correlation_id="corr-1")
        assert response.overall_status in ("OK", "DEGRADED", "DOWN")
    """

    def __init__(self) -> None:
        """
        Initialize the real dependency health repository.

        Does not connect to any dependencies; that happens on check() call.

        Example:
            repo = RealDependencyHealthRepository()
        """
        pass

    def check(self, *, correlation_id: str) -> DependencyHealthResponse:
        """
        Check the health of all platform dependencies.

        Args:
            correlation_id: Request-scoped tracing ID for structured logging.

        Returns:
            DependencyHealthResponse with one record per dependency and
            overall_status computed from individual statuses.

        Example:
            resp = repo.check(correlation_id="corr-123")
            assert resp.overall_status in ("OK", "DEGRADED", "DOWN")
        """
        records = []

        # Check database
        db_record = self._check_database(correlation_id)
        records.append(db_record)

        # Check Redis
        redis_record = self._check_redis(correlation_id)
        records.append(redis_record)

        # Check artifact store
        artifact_record = self._check_artifact_store(correlation_id)
        records.append(artifact_record)

        # Check feed health table
        feed_health_record = self._check_feed_health_table(correlation_id)
        records.append(feed_health_record)

        # Compute overall status
        statuses = [r.status for r in records]
        if all(s == "OK" for s in statuses):
            overall_status = "OK"
        elif all(s == "DOWN" for s in statuses):
            overall_status = "DOWN"
        else:
            overall_status = "DEGRADED"

        logger.info(
            "dependency_health.check",
            correlation_id=correlation_id,
            overall_status=overall_status,
            dependency_count=len(records),
        )

        return DependencyHealthResponse(
            dependencies=records,
            overall_status=overall_status,
            generated_at=datetime.now(timezone.utc),
        )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _check_database(correlation_id: str) -> DependencyHealthRecord:
        """
        Check database connectivity with 2s timeout.

        Args:
            correlation_id: Request-scoped tracing ID.

        Returns:
            DependencyHealthRecord with OK or DOWN status.
        """

        def _check():
            try:
                from services.api.db import check_db_connection

                result = check_db_connection()
                return "OK" if result else "DOWN"
            except Exception as exc:
                logger.warning(
                    "dependency_health.database_check_failed",
                    error=str(exc),
                    correlation_id=correlation_id,
                )
                return "DOWN"

        return RealDependencyHealthRepository._run_with_timeout(
            name="database",
            check_fn=_check,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _check_redis(correlation_id: str) -> DependencyHealthRecord:
        """
        Check Redis connectivity via PING with 2s timeout.

        Args:
            correlation_id: Request-scoped tracing ID.

        Returns:
            DependencyHealthRecord with OK or DOWN status.
        """

        def _check():
            redis_url = os.environ.get("REDIS_URL")
            if not redis_url:
                logger.debug(
                    "dependency_health.redis_not_configured",
                    correlation_id=correlation_id,
                )
                return "DOWN"

            try:
                import redis

                r = redis.from_url(redis_url)
                r.ping()
                return "OK"
            except Exception as exc:
                logger.warning(
                    "dependency_health.redis_check_failed",
                    error=str(exc),
                    correlation_id=correlation_id,
                )
                return "DOWN"

        return RealDependencyHealthRepository._run_with_timeout(
            name="redis",
            check_fn=_check,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _check_artifact_store(correlation_id: str) -> DependencyHealthRecord:
        """
        Check artifact store (local or MinIO) connectivity with 2s timeout.

        Args:
            correlation_id: Request-scoped tracing ID.

        Returns:
            DependencyHealthRecord with OK or DOWN status.
        """

        def _check():
            bucket = os.environ.get("ARTIFACT_BUCKET")
            endpoint = os.environ.get("MINIO_ENDPOINT")

            if bucket and endpoint:
                # MinIO configured
                try:
                    from minio import Minio

                    client = Minio(endpoint)
                    client.bucket_exists(bucket)
                    return "OK"
                except Exception as exc:
                    logger.warning(
                        "dependency_health.minio_check_failed",
                        error=str(exc),
                        correlation_id=correlation_id,
                    )
                    return "DOWN"
            else:
                # Local artifact storage
                local_path = os.environ.get("ARTIFACT_LOCAL_PATH", "/tmp/fxlab")
                try:
                    if os.path.exists(local_path) and os.path.isdir(local_path):
                        return "OK"
                    else:
                        return "DOWN"
                except Exception as exc:
                    logger.warning(
                        "dependency_health.local_storage_check_failed",
                        error=str(exc),
                        correlation_id=correlation_id,
                    )
                    return "DOWN"

        return RealDependencyHealthRepository._run_with_timeout(
            name="artifact_store",
            check_fn=_check,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _check_feed_health_table(correlation_id: str) -> DependencyHealthRecord:
        """
        Check feed_health_events table with 2s timeout.

        Args:
            correlation_id: Request-scoped tracing ID.

        Returns:
            DependencyHealthRecord with OK or DOWN status.
        """

        def _check():
            try:
                from sqlalchemy import text

                from services.api.db import engine

                with engine.connect() as conn:
                    conn.execute(text("SELECT COUNT(*) FROM feed_health_events"))
                return "OK"
            except Exception as exc:
                logger.warning(
                    "dependency_health.feed_health_table_check_failed",
                    error=str(exc),
                    correlation_id=correlation_id,
                )
                return "DOWN"

        return RealDependencyHealthRepository._run_with_timeout(
            name="feed_health_table",
            check_fn=_check,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _run_with_timeout(
        name: str,
        check_fn: Any,
        correlation_id: str,
    ) -> DependencyHealthRecord:
        """
        Run a check function with a 2s timeout and return a DependencyHealthRecord.

        Args:
            name: Name of the dependency being checked.
            check_fn: Callable that returns "OK" or "DOWN".
            correlation_id: Request-scoped tracing ID.

        Returns:
            DependencyHealthRecord with status and detail.
        """
        # Use a bounded thread pool (max 4 concurrent checks) to prevent
        # thread exhaustion under load.
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="health") as pool:
            future = pool.submit(check_fn)
            try:
                status = future.result(timeout=_CHECK_TIMEOUT)
            except FutureTimeoutError:
                logger.warning(
                    "dependency_health.check_timeout",
                    dependency=name,
                    timeout_seconds=_CHECK_TIMEOUT,
                    correlation_id=correlation_id,
                    component="dependency_health",
                )
                status = "DOWN"
                detail = f"Check timed out after {_CHECK_TIMEOUT}s"
            except Exception as exc:
                logger.warning(
                    "dependency_health.check_exception",
                    dependency=name,
                    error=str(exc),
                    exc_info=True,
                    correlation_id=correlation_id,
                    component="dependency_health",
                )
                status = "DOWN"
                detail = f"{name} check failed: {exc}"
            else:
                detail = f"{name} connectivity check: {status.lower()}"

        return DependencyHealthRecord(
            name=name,
            status=status,
            detail=detail,
            latency_ms=int(_CHECK_TIMEOUT * 1000),  # Placeholder
        )
