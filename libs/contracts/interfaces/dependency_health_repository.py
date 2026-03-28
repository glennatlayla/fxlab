"""
DependencyHealthRepositoryInterface — port for platform dependency health checks (M11).

Purpose:
    Define the contract that all dependency health repository implementations must
    honour, so the observability route layer depends on an abstraction (not on a
    concrete connectivity checker or cloud SDK).

Responsibilities:
    - check() → return a DependencyHealthResponse summarising the reachability and
      latency of all platform dependencies.

Does NOT:
    - Contain classification logic (done in mock/concrete implementations).
    - Store health check history.
    - Connect to any dependency directly (concrete adapters do that).

Dependencies:
    - libs.contracts.observability: DependencyHealthResponse.

Example:
    class SqlDependencyHealthRepository(DependencyHealthRepositoryInterface):
        def check(self, *, correlation_id: str) -> DependencyHealthResponse:
            # Ping DB, queues, artifact store, feed health service.
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.observability import DependencyHealthResponse


class DependencyHealthRepositoryInterface(ABC):
    """
    Abstract port for platform dependency health checks.

    Implementations provide either a real connectivity checker (production) or
    a configurable in-memory fake (tests).
    """

    @abstractmethod
    def check(self, *, correlation_id: str) -> DependencyHealthResponse:
        """
        Check the health of all platform dependencies.

        Args:
            correlation_id: Request-scoped tracing ID for structured logging.

        Returns:
            DependencyHealthResponse with one DependencyHealthRecord per dependency
            and a computed overall_status.

        Raises:
            ExternalServiceError: If the health check infrastructure itself fails
                                  (not if individual dependencies are down — those
                                  are reported as DOWN status in the response).

        Example:
            resp = repo.check(correlation_id="corr-123")
            assert resp.overall_status in ("OK", "DEGRADED", "DOWN")
        """
        ...
