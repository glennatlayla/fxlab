"""
Execution Loop Manager — registry of active execution loops.

Responsibilities:
- Maintain a registry of active ExecutionLoop instances keyed by deployment_id.
- Enforce one loop per deployment.
- Enforce maximum concurrent loop limit.
- Provide lookup, listing, and shutdown-all capabilities.
- Thread-safe for concurrent API access.

Does NOT:
- Implement loop logic (StrategyExecutionEngine does that).
- Define contracts (libs.contracts.execution_loop).
- Wire dependencies (DI layer responsibility).

Dependencies:
- libs.contracts.execution_loop: ExecutionLoopConfig, LoopState, LoopDiagnostics
- libs.contracts.interfaces.execution_loop: ExecutionLoopInterface
- threading: Lock for thread safety

Error conditions:
- ValueError: if deployment_id already has an active loop.
- ValueError: if max concurrent loops exceeded.
- KeyError: if deployment_id not found.

Example:
    manager = ExecutionLoopManager(max_concurrent=10)
    manager.register("deploy-001", engine)
    engine = manager.get("deploy-001")
    manager.stop_all()
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import structlog

from libs.contracts.execution_loop import LoopDiagnostics, LoopState

if TYPE_CHECKING:
    from libs.contracts.interfaces.execution_loop import ExecutionLoopInterface

logger = structlog.get_logger(__name__)


class ExecutionLoopManager:
    """
    Thread-safe registry managing active execution loop instances.

    Enforces:
    - At most one loop per deployment_id.
    - At most max_concurrent loops running simultaneously.
    - Graceful shutdown of all loops on stop_all().

    Responsibilities:
    - Register, retrieve, unregister execution loops.
    - List active deployments and their diagnostics.
    - Stop all loops for application shutdown.

    Does NOT:
    - Create or configure StrategyExecutionEngine instances.
    - Define loop behaviour.

    Thread safety:
    - All mutations under self._lock.

    Example:
        manager = ExecutionLoopManager(max_concurrent=10)
        manager.register("deploy-001", engine)
        diag = manager.get_diagnostics("deploy-001")
        manager.stop_all()
    """

    def __init__(self, *, max_concurrent: int = 50) -> None:
        """
        Initialize the manager with a maximum concurrent loop limit.

        Args:
            max_concurrent: Maximum number of simultaneous execution loops.

        Raises:
            ValueError: If max_concurrent < 1.

        Example:
            manager = ExecutionLoopManager(max_concurrent=20)
        """
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")
        self._lock = threading.Lock()
        self._loops: dict[str, ExecutionLoopInterface] = {}
        self._max_concurrent = max_concurrent

    def register(
        self,
        deployment_id: str,
        loop: ExecutionLoopInterface,
    ) -> None:
        """
        Register a new execution loop for a deployment.

        Args:
            deployment_id: Unique deployment identifier.
            loop: The execution loop instance to register.

        Raises:
            ValueError: If deployment_id already has an active loop.
            ValueError: If max concurrent loops would be exceeded.

        Example:
            manager.register("deploy-001", engine)
        """
        with self._lock:
            if deployment_id in self._loops:
                raise ValueError(f"Deployment {deployment_id} already has an active loop")
            if len(self._loops) >= self._max_concurrent:
                raise ValueError(f"Maximum concurrent loops ({self._max_concurrent}) reached")
            self._loops[deployment_id] = loop

        logger.info(
            "Execution loop registered",
            deployment_id=deployment_id,
            active_count=len(self._loops),
        )

    def unregister(self, deployment_id: str) -> None:
        """
        Remove a loop from the registry.

        Does NOT stop the loop — caller should stop it first.

        Args:
            deployment_id: Deployment to unregister.

        Raises:
            KeyError: If deployment_id not found.

        Example:
            loop = manager.get("deploy-001")
            loop.stop()
            manager.unregister("deploy-001")
        """
        with self._lock:
            if deployment_id not in self._loops:
                raise KeyError(f"No loop found for deployment {deployment_id}")
            del self._loops[deployment_id]

        logger.info(
            "Execution loop unregistered",
            deployment_id=deployment_id,
            active_count=len(self._loops),
        )

    def get(self, deployment_id: str) -> ExecutionLoopInterface:
        """
        Retrieve the execution loop for a deployment.

        Args:
            deployment_id: Deployment to look up.

        Returns:
            The registered ExecutionLoopInterface instance.

        Raises:
            KeyError: If deployment_id not found.

        Example:
            loop = manager.get("deploy-001")
            diag = loop.diagnostics()
        """
        with self._lock:
            if deployment_id not in self._loops:
                raise KeyError(f"No loop found for deployment {deployment_id}")
            return self._loops[deployment_id]

    def list_deployments(self) -> list[str]:
        """
        List all active deployment IDs.

        Returns:
            List of deployment_id strings.

        Example:
            ids = manager.list_deployments()
        """
        with self._lock:
            return list(self._loops.keys())

    def list_diagnostics(self) -> list[LoopDiagnostics]:
        """
        Get diagnostics for all active loops.

        Returns:
            List of LoopDiagnostics snapshots.

        Example:
            all_diag = manager.list_diagnostics()
        """
        with self._lock:
            loops = list(self._loops.values())
        # Call diagnostics outside the lock to avoid holding it during I/O.
        return [loop.diagnostics() for loop in loops]

    def get_diagnostics(self, deployment_id: str) -> LoopDiagnostics:
        """
        Get diagnostics for a specific deployment.

        Args:
            deployment_id: Deployment to query.

        Returns:
            LoopDiagnostics snapshot.

        Raises:
            KeyError: If deployment_id not found.

        Example:
            diag = manager.get_diagnostics("deploy-001")
        """
        loop = self.get(deployment_id)
        return loop.diagnostics()

    def count(self) -> int:
        """Return the number of active loops."""
        with self._lock:
            return len(self._loops)

    def stop_all(self) -> dict[str, str]:
        """
        Stop all active loops gracefully.

        Returns a dict mapping deployment_id to outcome ("stopped" or error message).

        Returns:
            Dict of deployment_id → outcome string.

        Example:
            results = manager.stop_all()
            # {"deploy-001": "stopped", "deploy-002": "stopped"}
        """
        with self._lock:
            deployment_ids = list(self._loops.keys())
            loops = list(self._loops.values())

        results: dict[str, str] = {}
        for deploy_id, loop in zip(deployment_ids, loops, strict=True):
            try:
                if loop.state not in (LoopState.STOPPED, LoopState.FAILED):
                    loop.stop()
                results[deploy_id] = "stopped"
            except Exception as e:
                logger.error(
                    "Failed to stop execution loop",
                    deployment_id=deploy_id,
                    error=str(e),
                )
                results[deploy_id] = f"error: {e}"

        # Clear the registry after stopping all.
        with self._lock:
            self._loops.clear()

        logger.info(
            "All execution loops stopped",
            count=len(results),
        )
        return results
