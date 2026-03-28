"""
MockDependencyHealthRepository — in-memory DependencyHealthRepositoryInterface (M11).

Purpose:
    Provide a fast, fully controllable fake for DependencyHealthRepositoryInterface
    so that unit tests can exercise the GET /health/dependencies endpoint without
    real network connectivity.

Responsibilities:
    - Default check() returns all four standard dependencies as DependencyStatus.OK.
    - set_dependency_status(name, status, detail="") allows tests to inject degraded
      or DOWN states for specific dependencies.
    - Compute overall_status from the worst dependency status in check().
    - Provide clear() and count() introspection helpers.

Does NOT:
    - Perform real connectivity checks.
    - Simulate network latency (latency_ms is always 0.0).

Dependencies:
    - DependencyHealthRepositoryInterface (parent).
    - DependencyHealthRecord, DependencyHealthResponse, DependencyStatus (contracts).

Error conditions:
    - No errors raised by this mock; check() always returns a response.

Example:
    repo = MockDependencyHealthRepository()
    resp = repo.check(correlation_id="c")
    assert resp.overall_status == "OK"

    repo.set_dependency_status("queues", DependencyStatus.DOWN, detail="celery unreachable")
    resp = repo.check(correlation_id="c")
    assert resp.overall_status == "DOWN"
"""

from __future__ import annotations

from datetime import datetime, timezone

from libs.contracts.interfaces.dependency_health_repository import (
    DependencyHealthRepositoryInterface,
)
from libs.contracts.observability import (
    DependencyHealthRecord,
    DependencyHealthResponse,
    DependencyStatus,
)

# Standard dependency names checked by this mock.
_DEFAULT_DEPENDENCIES = ("database", "queues", "artifact_store", "feed_health_service")

# Severity rank for computing overall_status (highest wins).
_STATUS_RANK: dict[str, int] = {
    DependencyStatus.DOWN.value: 3,
    DependencyStatus.DEGRADED.value: 2,
    DependencyStatus.OK.value: 1,
}


class MockDependencyHealthRepository(DependencyHealthRepositoryInterface):
    """
    In-memory DependencyHealthRepositoryInterface for unit tests.

    Initialises all default dependencies as OK.  Individual dependency statuses
    can be overridden via set_dependency_status() to simulate degraded scenarios.

    Thread-safety: Not thread-safe.  Use only in synchronous unit tests.
    """

    def __init__(self) -> None:
        # Maps dependency name → (status, detail) override.
        # Dependencies not present in this dict default to OK.
        self._overrides: dict[str, tuple[DependencyStatus, str]] = {}

    # ------------------------------------------------------------------
    # DependencyHealthRepositoryInterface implementation
    # ------------------------------------------------------------------

    def check(self, *, correlation_id: str) -> DependencyHealthResponse:
        """
        Return health status for all standard platform dependencies.

        Uses overrides set via set_dependency_status(); all other dependencies
        default to DependencyStatus.OK.

        Args:
            correlation_id: Ignored in mock.

        Returns:
            DependencyHealthResponse with one record per default dependency and
            an overall_status reflecting the worst individual status.

        Example:
            resp = repo.check(correlation_id="c")
            assert len(resp.dependencies) == 4
        """
        records: list[DependencyHealthRecord] = []
        worst_rank = 0
        worst_status = DependencyStatus.OK

        for name in _DEFAULT_DEPENDENCIES:
            if name in self._overrides:
                status, detail = self._overrides[name]
            else:
                status, detail = DependencyStatus.OK, ""
            records.append(
                DependencyHealthRecord(
                    name=name,
                    status=status,
                    latency_ms=0.0,
                    detail=detail,
                )
            )
            rank = _STATUS_RANK.get(status.value, 0)
            if rank > worst_rank:
                worst_rank = rank
                worst_status = status

        overall = worst_status.value if records else ""
        return DependencyHealthResponse(
            dependencies=records,
            overall_status=overall,
            generated_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Test configuration helpers
    # ------------------------------------------------------------------

    def set_dependency_status(
        self,
        name: str,
        status: DependencyStatus,
        detail: str = "",
    ) -> None:
        """
        Override the status for a named dependency.

        Args:
            name:   Dependency name (e.g. "database", "queues").
            status: DependencyStatus to report for this dependency.
            detail: Optional detail message (str, not Optional[str] — LL-007).

        Example:
            repo.set_dependency_status("queues", DependencyStatus.DOWN, "celery unreachable")
        """
        self._overrides[name] = (status, detail)

    def clear(self) -> None:
        """Reset all dependency overrides (all deps return OK after clear())."""
        self._overrides.clear()

    def count(self) -> int:
        """Return the number of dependencies this mock checks (always 4)."""
        return len(_DEFAULT_DEPENDENCIES)
