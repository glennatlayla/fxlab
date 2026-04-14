"""
Health check service interface.

All Phase 3 services must implement this interface to support container
orchestration and monitoring.
"""

from abc import abstractmethod
from typing import Protocol

from libs.contracts.phase3.runtime import (
    HealthCheckResponse,
    LivenessCheckResponse,
    ReadinessCheckResponse,
)


class HealthCheckService(Protocol):
    """
    Protocol for health check providers.

    Every Phase 3 service must implement this to expose health, readiness,
    and liveness endpoints for Docker Compose health checks and orchestration.
    """

    @abstractmethod
    async def check_health(self) -> HealthCheckResponse:
        """
        Execute full health check including dependency verification.

        Returns:
            HealthCheckResponse with overall status and dependency states
        """
        ...

    @abstractmethod
    async def check_readiness(self) -> ReadinessCheckResponse:
        """
        Execute readiness check to determine if service can accept traffic.

        Readiness may fail even if the service is alive (e.g., waiting for
        database migrations, warming caches).

        Returns:
            ReadinessCheckResponse indicating if service is ready and why
        """
        ...

    @abstractmethod
    async def check_liveness(self) -> LivenessCheckResponse:
        """
        Execute liveness check to verify process is responsive.

        This should be a lightweight check that does not depend on external
        services. Used by orchestrators to determine if a container should
        be restarted.

        Returns:
            LivenessCheckResponse indicating if process is alive
        """
        ...


class DependencyHealthChecker(Protocol):
    """
    Protocol for checking health of a specific dependency.

    Used by HealthCheckService to verify external service availability.
    """

    @abstractmethod
    async def check(self) -> tuple[bool, float | None, str | None]:
        """
        Check dependency health.

        Returns:
            Tuple of (is_healthy, latency_ms, error_message)
        """
        ...


class DatabaseHealthChecker(DependencyHealthChecker, Protocol):
    """Health checker for PostgreSQL database connection."""

    @abstractmethod
    async def check(self) -> tuple[bool, float | None, str | None]:
        """
        Verify database connectivity by executing a simple query.

        Returns:
            Tuple of (is_healthy, latency_ms, error_message)
        """
        ...


class RedisHealthChecker(DependencyHealthChecker, Protocol):
    """Health checker for Redis connection."""

    @abstractmethod
    async def check(self) -> tuple[bool, float | None, str | None]:
        """
        Verify Redis connectivity by executing PING command.

        Returns:
            Tuple of (is_healthy, latency_ms, error_message)
        """
        ...
