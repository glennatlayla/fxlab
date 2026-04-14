"""Health check interface for service availability monitoring."""

from abc import ABC, abstractmethod

from libs.contracts.health import HealthStatus, LivenessStatus, ReadinessStatus


class HealthChecker(ABC):
    """Abstract interface for health check operations.

    All services must implement health checks for orchestration
    and observability requirements.
    """

    @abstractmethod
    async def check_health(self) -> HealthStatus:
        """Check overall service health including dependencies.

        Returns:
            HealthStatus with service name, status, and dependency details.
        """
        ...

    @abstractmethod
    async def check_readiness(self) -> ReadinessStatus:
        """Check if service is ready to accept traffic.

        Returns:
            ReadinessStatus indicating if service can handle requests.
        """
        ...

    @abstractmethod
    async def check_liveness(self) -> LivenessStatus:
        """Check if service is alive and should not be restarted.

        Returns:
            LivenessStatus indicating if service process is functioning.
        """
        ...
