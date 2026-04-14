"""
API endpoint interfaces for Phase 3.

All FastAPI routers must implement these interfaces to ensure consistent
error handling, request/response contracts, and observability.
"""

from abc import abstractmethod
from typing import Protocol

from libs.contracts.phase3.runtime import (
    HealthCheckResponse,
    LivenessCheckResponse,
    ReadinessCheckResponse,
)


class HealthEndpoint(Protocol):
    """
    Protocol for health check endpoint.

    Must be implemented by the main FastAPI application to support
    Docker Compose health checks.
    """

    @abstractmethod
    async def get_health(self) -> HealthCheckResponse:
        """
        GET /health endpoint.

        Returns:
            HealthCheckResponse with service and dependency status
        """
        ...


class ReadinessEndpoint(Protocol):
    """
    Protocol for readiness check endpoint.

    Used by orchestrators to determine when service can accept traffic.
    """

    @abstractmethod
    async def get_readiness(self) -> ReadinessCheckResponse:
        """
        GET /ready endpoint.

        Returns:
            ReadinessCheckResponse indicating if service is ready
        """
        ...


class LivenessEndpoint(Protocol):
    """
    Protocol for liveness check endpoint.

    Used by orchestrators to determine if container should be restarted.
    """

    @abstractmethod
    async def get_liveness(self) -> LivenessCheckResponse:
        """
        GET /alive endpoint.

        Returns:
            LivenessCheckResponse indicating if process is responsive
        """
        ...


class RootEndpoint(Protocol):
    """
    Protocol for root API endpoint.

    Provides service identity and version information.
    """

    @abstractmethod
    async def get_root(self) -> dict[str, str]:
        """
        GET / endpoint.

        Returns:
            Dictionary with service name, version, and documentation URL
        """
        ...
