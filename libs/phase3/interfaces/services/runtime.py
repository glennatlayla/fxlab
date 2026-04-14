"""
Runtime service interfaces for Phase 3.

Services that manage application lifecycle, startup/shutdown, and
runtime coordination.
"""

from abc import abstractmethod
from typing import Protocol


class RuntimeService(Protocol):
    """
    Protocol for application runtime lifecycle management.

    Implementations coordinate startup, shutdown, and graceful degradation
    of Phase 3 services.
    """

    @abstractmethod
    async def startup(self) -> None:
        """
        Execute service startup sequence.

        Must establish database connections, initialize caches, verify
        dependencies, and prepare service to accept requests.
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """
        Execute graceful shutdown sequence.

        Must close database connections, flush queues, persist state,
        and clean up resources.
        """
        ...

    @abstractmethod
    async def get_uptime_seconds(self) -> float:
        """
        Retrieve service uptime in seconds.

        Returns:
            Seconds since service started
        """
        ...

    @abstractmethod
    def get_service_version(self) -> str:
        """
        Retrieve service version or build hash.

        Returns:
            Version identifier for health checks and observability
        """
        ...


class DependencyCoordinator(Protocol):
    """
    Protocol for coordinating external dependency initialization.

    Ensures database migrations, cache warming, and other startup
    dependencies complete before service accepts traffic.
    """

    @abstractmethod
    async def wait_for_database(self, timeout_seconds: int = 30) -> bool:
        """
        Wait for database to become available.

        Args:
            timeout_seconds: Maximum time to wait

        Returns:
            True if database is available, False if timeout
        """
        ...

    @abstractmethod
    async def wait_for_redis(self, timeout_seconds: int = 30) -> bool:
        """
        Wait for Redis to become available.

        Args:
            timeout_seconds: Maximum time to wait

        Returns:
            True if Redis is available, False if timeout
        """
        ...

    @abstractmethod
    async def verify_all_dependencies(self) -> dict[str, bool]:
        """
        Verify all external dependencies are available.

        Returns:
            Map of dependency name to availability status
        """
        ...
