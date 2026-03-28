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
"""

__all__ = [
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
]
