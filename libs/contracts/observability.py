"""
Observability contracts (Phase 3 — M11: Alerting + Observability Hardening).

Purpose:
    Provide the data shapes for the operator diagnostics shell endpoints:
    GET /health/dependencies and GET /health/diagnostics.

Responsibilities:
    - DependencyStatus enum — OK / DEGRADED / DOWN classification.
    - DependencyHealthRecord — single dependency check result.
    - DependencyHealthResponse — aggregate dependency health report.
    - DiagnosticsSnapshot — platform-wide operational counts.

Does NOT:
    - Perform actual connectivity checks (handled in repository implementations).
    - Contain business logic.
    - Access any external system directly.

Note on str fields:
    DependencyHealthRecord.detail and DependencyHealthResponse.overall_status use
    str="" (not Optional[str]) to avoid pydantic-core cross-arch stub failure (LL-007).

Example:
    record = DependencyHealthRecord(
        name="database",
        status=DependencyStatus.OK,
        latency_ms=1.2,
        detail="",
    )
    response = DependencyHealthResponse(
        dependencies=[record],
        overall_status="OK",
        generated_at=datetime.now(timezone.utc),
    )
    snapshot = DiagnosticsSnapshot(
        queue_contention_count=0,
        feed_health_count=3,
        parity_critical_count=1,
        certification_blocked_count=0,
        generated_at=datetime.now(timezone.utc),
    )
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DependencyStatus(str, Enum):
    """
    Reachability / health classification for a backend dependency.

    Attributes:
        OK:       Dependency is reachable and operating normally.
        DEGRADED: Dependency is reachable but experiencing elevated latency or
                  partial failures.  Service may continue with reduced capacity.
        DOWN:     Dependency is unreachable or returning persistent errors.
                  Service functionality that relies on it is unavailable.
    """

    OK = "OK"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


class DependencyHealthRecord(BaseModel):
    """
    Health check result for a single backend dependency.

    Purpose:
        Provide the operator diagnostics shell with the health status of one
        specific platform dependency (database, queues, artifact store, etc.).

    Responsibilities:
        - Carry name, status, round-trip latency, and an optional detail string.
        - detail is str="" (not Optional[str]) to avoid LL-007.

    Does NOT:
        - Perform the connectivity check itself (repository responsibility).
        - Persist check results.

    Example:
        r = DependencyHealthRecord(
            name="database",
            status=DependencyStatus.OK,
            latency_ms=0.8,
            detail="",
        )
    """

    name: str = Field(..., description="Dependency identifier, e.g. 'database', 'queues'")
    status: DependencyStatus = Field(..., description="Reachability / health classification")
    latency_ms: float = Field(
        default=0.0, ge=0.0, description="Round-trip latency in milliseconds; 0.0 when not measured"
    )
    detail: str = Field(
        default="",
        description=(
            "Human-readable detail message for DEGRADED or DOWN states.  "
            "Empty string when status is OK.  "
            "Uses str (not Optional[str]) to avoid pydantic-core cross-arch stub (LL-007)."
        ),
    )


class DependencyHealthResponse(BaseModel):
    """
    Aggregate dependency health report for GET /health/dependencies.

    Purpose:
        Returned by GET /health/dependencies so the operator diagnostics shell
        can display a real-time status badge for each platform component without
        computing health state locally.

    Responsibilities:
        - Wrap a list of DependencyHealthRecord objects (one per dependency).
        - Provide overall_status: "OK" if all deps are OK; "DEGRADED" if any are
          DEGRADED (and none DOWN); "DOWN" if any are DOWN.
        - overall_status is str="" (not Optional[str]) to avoid LL-007.

    Does NOT:
        - Include application-level metrics (use DiagnosticsSnapshot for those).

    Example:
        resp = DependencyHealthResponse(
            dependencies=[...],
            overall_status="OK",
            generated_at=datetime.now(timezone.utc),
        )
    """

    dependencies: list[DependencyHealthRecord] = Field(
        default_factory=list,
        description="Health check results for each platform dependency",
    )
    overall_status: str = Field(
        default="",
        description=(
            "Worst-case status across all dependencies: 'OK', 'DEGRADED', or 'DOWN'.  "
            "Empty string when the dependency list is empty.  "
            "Uses str (not Optional[str]) to avoid pydantic-core cross-arch stub (LL-007)."
        ),
    )
    generated_at: datetime = Field(..., description="Timestamp when the health check was run")


class DiagnosticsSnapshot(BaseModel):
    """
    Platform-wide operational counts for GET /health/diagnostics.

    Purpose:
        Power the operator diagnostics overview panel with a compact real-time
        snapshot of key operational metrics — number of active queue contentions,
        feed health snapshots, unresolved CRITICAL parity events, and blocked
        certification entries — without requiring the UI to aggregate from multiple
        endpoints.

    Responsibilities:
        - Carry four integer count fields and a generation timestamp.
        - All counts are non-negative integers; 0 indicates a clean system state.

    Does NOT:
        - Include raw event or entity data (use the respective list endpoints for that).
        - Compute counts itself (repository responsibility).

    Example:
        snap = DiagnosticsSnapshot(
            queue_contention_count=2,
            feed_health_count=5,
            parity_critical_count=1,
            certification_blocked_count=0,
            generated_at=datetime.now(timezone.utc),
        )
    """

    queue_contention_count: int = Field(
        ...,
        ge=0,
        description="Number of queue classes currently reporting active contention",
    )
    feed_health_count: int = Field(
        ...,
        ge=0,
        description="Total number of feed health snapshots in the system",
    )
    parity_critical_count: int = Field(
        ...,
        ge=0,
        description="Number of unresolved CRITICAL severity parity events",
    )
    certification_blocked_count: int = Field(
        ...,
        ge=0,
        description="Number of feeds with BLOCKED certification status",
    )
    generated_at: datetime = Field(..., description="Snapshot generation timestamp")
