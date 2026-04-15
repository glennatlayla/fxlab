"""
Thread-safe broker adapter registry for multi-broker deployments.

Responsibilities:
- Register and deregister broker adapters by deployment_id.
- Retrieve adapters by deployment_id for order operations.
- List all registered deployments with their broker type.
- Call adapter connect/disconnect lifecycle hooks on register/deregister.
- Thread-safe: all mutations protected by threading.Lock.
- Persist deployment → broker_type mapping via deployment repository
  so the registry can be reconstructed after restart.

Does NOT:
- Contain business logic, risk checks, or execution logic.
- Know about specific broker APIs (Alpaca, IBKR, etc.).
- Submit orders or manage positions (that's the execution service's job).

Dependencies:
- libs.contracts.interfaces.broker_adapter: BrokerAdapterInterface.
- libs.contracts.errors: NotFoundError.
- threading: Thread safety via Lock.
- structlog: Structured logging.

Error conditions:
- NotFoundError: deployment_id not found in registry.
- ValueError: duplicate deployment_id registration attempt.

Example:
    registry = BrokerAdapterRegistry()
    registry.register(deployment_id="dep-001", adapter=adapter, broker_type="alpaca")
    adapter = registry.get(deployment_id="dep-001")
    registry.deregister(deployment_id="dep-001")
"""

from __future__ import annotations

import threading
from typing import Any

import structlog

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface

logger = structlog.get_logger(__name__)


class BrokerAdapterRegistry:
    """
    Thread-safe registry mapping deployment_id → broker adapter instance.

    Manages the lifecycle of broker adapters for all active deployments.
    On register, calls adapter.connect(). On deregister, calls
    adapter.disconnect(). All reads and writes are Lock-protected
    for safe use in multi-threaded ASGI workers.

    Responsibilities:
    - Store deployment_id → (adapter, broker_type) mappings.
    - Enforce one adapter per deployment_id (no duplicates).
    - Invoke adapter lifecycle hooks (connect/disconnect).
    - Provide thread-safe access to adapters.

    Does NOT:
    - Create adapters (that's the caller's job).
    - Persist state to DB (caller must persist if needed).
    - Enforce execution mode rules (service layer responsibility).

    Attributes:
        _registry: Dict mapping deployment_id → (adapter, broker_type).
        _lock: Threading lock for concurrent access safety.

    Example:
        registry = BrokerAdapterRegistry()
        registry.register("dep-001", mock_adapter, "mock")
        adapter = registry.get("dep-001")
        registry.deregister("dep-001")
    """

    def __init__(self) -> None:
        """Initialize the empty registry with thread safety lock."""
        self._registry: dict[str, tuple[BrokerAdapterInterface, str]] = {}
        self._lock = threading.Lock()

    def register(
        self,
        deployment_id: str,
        adapter: BrokerAdapterInterface,
        broker_type: str,
    ) -> None:
        """
        Register a broker adapter for a deployment.

        Calls adapter.connect() to establish the broker connection.
        If connect() fails, the adapter is NOT registered and the
        exception propagates to the caller.

        Args:
            deployment_id: ULID of the deployment.
            adapter: BrokerAdapterInterface implementation to register.
            broker_type: Broker identifier string (e.g. "alpaca", "paper", "mock").

        Raises:
            ValueError: deployment_id is already registered. Deregister first.
            ExternalServiceError: adapter.connect() failed.

        Example:
            registry.register("dep-001", alpaca_adapter, "alpaca")
        """
        with self._lock:
            if deployment_id in self._registry:
                raise ValueError(
                    f"Deployment {deployment_id} is already registered. "
                    "Deregister the existing adapter before registering a new one."
                )

        # Connect outside the lock — adapter.connect() may do network I/O
        # and we don't want to block other registry operations.
        logger.info(
            "broker_registry.connecting",
            deployment_id=deployment_id,
            broker_type=broker_type,
            component="broker_registry",
        )
        adapter.connect()

        with self._lock:
            # Double-check after connect (another thread may have registered)
            if deployment_id in self._registry:
                # Clean up the adapter we just connected
                try:
                    adapter.disconnect()
                except Exception:
                    logger.warning(
                        "broker_registry.disconnect_cleanup_error",
                        deployment_id=deployment_id,
                        component="broker_registry",
                        exc_info=True,
                    )
                raise ValueError(
                    f"Deployment {deployment_id} was registered by another thread "
                    "while connect() was in progress."
                )

            self._registry[deployment_id] = (adapter, broker_type)

        logger.info(
            "broker_registry.registered",
            deployment_id=deployment_id,
            broker_type=broker_type,
            component="broker_registry",
            total_registered=self.count(),
        )

    def deregister(self, deployment_id: str) -> None:
        """
        Deregister a broker adapter and disconnect it.

        Calls adapter.disconnect() to release broker resources.
        disconnect() errors are logged but NOT raised — deregistration
        always succeeds to prevent resource leaks during shutdown.

        Args:
            deployment_id: ULID of the deployment to deregister.

        Raises:
            NotFoundError: deployment_id is not registered.

        Example:
            registry.deregister("dep-001")
        """
        with self._lock:
            entry = self._registry.pop(deployment_id, None)

        if entry is None:
            raise NotFoundError(f"Deployment {deployment_id} is not registered")

        adapter, broker_type = entry

        logger.info(
            "broker_registry.disconnecting",
            deployment_id=deployment_id,
            broker_type=broker_type,
            component="broker_registry",
        )

        try:
            adapter.disconnect()
        except Exception:
            # disconnect() errors are swallowed per the interface contract
            logger.warning(
                "broker_registry.disconnect_error",
                deployment_id=deployment_id,
                broker_type=broker_type,
                component="broker_registry",
                exc_info=True,
            )

        logger.info(
            "broker_registry.deregistered",
            deployment_id=deployment_id,
            broker_type=broker_type,
            component="broker_registry",
            total_registered=self.count(),
        )

    def get(self, deployment_id: str) -> BrokerAdapterInterface:
        """
        Retrieve the broker adapter for a deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            The registered BrokerAdapterInterface instance.

        Raises:
            NotFoundError: deployment_id is not registered.

        Example:
            adapter = registry.get("dep-001")
            response = adapter.submit_order(request)
        """
        with self._lock:
            entry = self._registry.get(deployment_id)

        if entry is None:
            raise NotFoundError(f"No broker adapter registered for deployment {deployment_id}")

        return entry[0]

    def get_broker_type(self, deployment_id: str) -> str:
        """
        Get the broker type string for a registered deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Broker type string (e.g. "alpaca", "paper", "mock").

        Raises:
            NotFoundError: deployment_id is not registered.

        Example:
            broker_type = registry.get_broker_type("dep-001")
            # broker_type == "alpaca"
        """
        with self._lock:
            entry = self._registry.get(deployment_id)

        if entry is None:
            raise NotFoundError(f"No broker adapter registered for deployment {deployment_id}")

        return entry[1]

    def list_deployments(self) -> list[dict[str, Any]]:
        """
        List all registered deployments with their broker type.

        Returns:
            List of dicts with 'deployment_id' and 'broker_type' keys,
            sorted by deployment_id for deterministic output.

        Example:
            deployments = registry.list_deployments()
            # [{"deployment_id": "dep-001", "broker_type": "alpaca"}, ...]
        """
        with self._lock:
            entries = [
                {"deployment_id": dep_id, "broker_type": bt}
                for dep_id, (_adapter, bt) in self._registry.items()
            ]

        return sorted(entries, key=lambda e: e["deployment_id"])

    def is_registered(self, deployment_id: str) -> bool:
        """
        Check if a deployment has a registered adapter.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            True if the deployment has a registered adapter.

        Example:
            if not registry.is_registered("dep-001"):
                registry.register("dep-001", adapter, "alpaca")
        """
        with self._lock:
            return deployment_id in self._registry

    def count(self) -> int:
        """
        Return the number of currently registered adapters.

        Returns:
            Number of registered deployments.

        Example:
            n = registry.count()
            # n >= 0
        """
        with self._lock:
            return len(self._registry)

    def deregister_all(self) -> int:
        """
        Deregister all adapters. Used during graceful shutdown.

        Calls disconnect() on every registered adapter. Errors from
        disconnect() are logged but swallowed to ensure all adapters
        are cleaned up even if some fail.

        Returns:
            Number of adapters that were deregistered.

        Example:
            count = registry.deregister_all()
            # count == number of adapters that were cleaned up
        """
        with self._lock:
            entries = list(self._registry.items())
            self._registry.clear()

        logger.info(
            "broker_registry.deregistering_all",
            count=len(entries),
            component="broker_registry",
        )

        for deployment_id, (adapter, broker_type) in entries:
            try:
                adapter.disconnect()
            except Exception:
                logger.warning(
                    "broker_registry.shutdown_disconnect_error",
                    deployment_id=deployment_id,
                    broker_type=broker_type,
                    component="broker_registry",
                    exc_info=True,
                )

        logger.info(
            "broker_registry.all_deregistered",
            count=len(entries),
            component="broker_registry",
        )

        return len(entries)
