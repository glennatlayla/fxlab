"""
Unit tests for ConnectionManager interface (libs.db.interfaces.connection_manager).

Tests verify:
- ConnectionManager is an abstract base class.
- All required abstract methods are properly declared.
- Subclasses can implement the interface.
"""

from __future__ import annotations

from typing import Any, AsyncContextManager

import pytest

from libs.db.interfaces.connection_manager import ConnectionManager


class ConcreteConnectionManager(ConnectionManager):
    """Concrete implementation of ConnectionManager for testing."""

    async def initialize(self) -> None:
        """Initialize connection pool."""
        pass

    async def shutdown(self) -> None:
        """Shutdown connection pool."""
        pass

    async def health_check(self) -> bool:
        """Check health status."""
        return True

    def session(self) -> AsyncContextManager[Any]:
        """Get a session context manager."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _session():
            yield None

        return _session()


class TestConnectionManagerInterface:
    """Tests for ConnectionManager abstract interface."""

    def test_connection_manager_is_abstract(self) -> None:
        """
        ConnectionManager cannot be instantiated directly (it's abstract).

        Scenario:
        - Attempt to instantiate ConnectionManager.

        Expected:
        - Raises TypeError (cannot instantiate abstract class).
        """
        with pytest.raises(TypeError):
            ConnectionManager()  # type: ignore

    def test_concrete_implementation_can_be_instantiated(self) -> None:
        """
        Concrete subclass of ConnectionManager can be instantiated.

        Scenario:
        - Create ConcreteConnectionManager.

        Expected:
        - Instance is created successfully.
        """
        manager = ConcreteConnectionManager()
        assert isinstance(manager, ConnectionManager)

    def test_concrete_implementation_has_initialize_method(self) -> None:
        """
        Concrete implementation has initialize method.

        Scenario:
        - ConcreteConnectionManager instance.

        Expected:
        - initialize method exists and is callable.
        """
        manager = ConcreteConnectionManager()
        assert hasattr(manager, "initialize")
        assert callable(manager.initialize)

    def test_concrete_implementation_has_shutdown_method(self) -> None:
        """
        Concrete implementation has shutdown method.

        Scenario:
        - ConcreteConnectionManager instance.

        Expected:
        - shutdown method exists and is callable.
        """
        manager = ConcreteConnectionManager()
        assert hasattr(manager, "shutdown")
        assert callable(manager.shutdown)

    def test_concrete_implementation_has_health_check_method(self) -> None:
        """
        Concrete implementation has health_check method.

        Scenario:
        - ConcreteConnectionManager instance.

        Expected:
        - health_check method exists and is callable.
        """
        manager = ConcreteConnectionManager()
        assert hasattr(manager, "health_check")
        assert callable(manager.health_check)

    def test_concrete_implementation_has_session_method(self) -> None:
        """
        Concrete implementation has session method.

        Scenario:
        - ConcreteConnectionManager instance.

        Expected:
        - session method exists and is callable.
        """
        manager = ConcreteConnectionManager()
        assert hasattr(manager, "session")
        assert callable(manager.session)
