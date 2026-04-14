"""Database connection management interface."""

from abc import ABC, abstractmethod
from typing import Any, AsyncContextManager


class ConnectionManager(ABC):
    """Abstract interface for database connection lifecycle.

    Provides connection pooling, health checks, and graceful shutdown
    for all database interactions.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize connection pool and verify connectivity.

        Raises:
            ConnectionError: If database is unreachable or credentials invalid.
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully close all connections and clean up resources."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify database connectivity without starting a transaction.

        Returns:
            True if database is reachable and responsive.
        """
        ...

    @abstractmethod
    def session(self) -> AsyncContextManager[Any]:
        """Get a database session context manager.

        Returns:
            Async context manager yielding a database session.
        """
        ...
