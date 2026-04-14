"""
SQL repository implementations for FXLab Phase 3 API.

This package contains all SQLAlchemy-backed repository implementations
that provide data access for the API routes. Each repository implements
a corresponding interface from libs.contracts.interfaces.

Implementations:
- sql_artifact_repository: Artifact metadata persistence (ISS-011)
- sql_feed_repository: Feed registry data access (ISS-013)
- sql_feed_health_repository: Feed health state access (ISS-014)
- sql_chart_repository: Chart data caching and retrieval (ISS-016)
- celery_queue_repository: Queue state via Celery inspect API (ISS-017)
- sql_certification_repository: Feed certification event access (ISS-019)
- sql_parity_repository: Parity event data access (ISS-020)
- sql_audit_explorer_repository: Audit event read access (ISS-021)
- sql_symbol_lineage_repository: Symbol data provenance access (ISS-022)
- real_dependency_health_repository: Platform dependency health checks (ISS-024)
- sql_diagnostics_repository: Platform-wide operational snapshots (ISS-025)

Utilities:
- check_row_version: Optimistic locking guard for concurrent write detection (H-CRIT-4).

Dependencies:
- SQLAlchemy ORM
- structlog

Example:
    from services.api.repositories import check_row_version
    check_row_version(entity, expected_version=2)
    entity.row_version += 1
    db.flush()
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


class OptimisticLockError(Exception):
    """
    Raised when a concurrent write conflict is detected via row_version mismatch.

    This is a permanent failure — retrying with the same stale version will always
    fail. The caller must re-read the entity at the current version and re-apply
    its changes.

    Attributes:
        entity_type: Name of the model class (e.g. "Strategy").
        entity_id: Primary key of the conflicting entity.
        expected_version: The version the caller expected to find.
        actual_version: The version currently stored in the database.
    """

    def __init__(
        self,
        entity_type: str,
        entity_id: str,
        expected_version: int,
        actual_version: int,
    ) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"Optimistic lock conflict on {entity_type} {entity_id}: "
            f"expected row_version={expected_version}, "
            f"found row_version={actual_version}. "
            f"Another request modified this record. Re-read and retry."
        )


def check_row_version(entity: object, expected_version: int) -> None:
    """
    Verify that an entity's row_version matches the expected version.

    Call this BEFORE applying mutations to a mutable entity (Strategy, Run,
    Override) to detect concurrent writes. If the versions don't match,
    another request has modified the entity since the caller read it.

    After a successful check, the caller MUST increment row_version before
    flushing: ``entity.row_version += 1``

    Args:
        entity: A SQLAlchemy model instance with a ``row_version`` attribute
                and an ``id`` attribute.
        expected_version: The row_version value the caller read when they
                         fetched the entity.

    Raises:
        OptimisticLockError: If entity.row_version != expected_version.
        AttributeError: If the entity has no row_version column.

    Example:
        strategy = db.get(Strategy, strategy_id)
        check_row_version(strategy, expected_version=payload.row_version)
        strategy.name = payload.name
        strategy.row_version += 1
        db.flush()
    """
    actual_version = getattr(entity, "row_version", None)
    if actual_version is None:
        raise AttributeError(
            f"{type(entity).__name__} does not have a row_version column. "
            f"Optimistic locking requires a row_version Integer column."
        )

    if actual_version != expected_version:
        entity_id = getattr(entity, "id", "unknown")
        entity_type = type(entity).__name__

        logger.warning(
            "repository.optimistic_lock_conflict",
            entity_type=entity_type,
            entity_id=entity_id,
            expected_version=expected_version,
            actual_version=actual_version,
            component="repositories",
        )

        raise OptimisticLockError(
            entity_type=entity_type,
            entity_id=str(entity_id),
            expected_version=expected_version,
            actual_version=actual_version,
        )


__all__ = [
    "OptimisticLockError",
    "SqlArtifactRepository",
    "SqlFeedRepository",
    "SqlFeedHealthRepository",
    "SqlChartRepository",
    "CeleryQueueRepository",
    "SqlCertificationRepository",
    "SqlParityRepository",
    "SqlAuditExplorerRepository",
    "SqlSymbolLineageRepository",
    "RealDependencyHealthRepository",
    "SqlDiagnosticsRepository",
    "check_row_version",
]
