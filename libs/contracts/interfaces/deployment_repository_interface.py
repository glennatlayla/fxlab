"""
Abstract deployment repository interface for Phase 4 execution layer.

Responsibilities:
- Define data access operations for deployment records.
- Serve as the port between the service and data layers.

Does NOT:
- Contain business logic or state machine rules.
- Know about HTTP or API layer concerns.
- Enforce policy gates or approval logic.

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: deployment_id does not exist.

Example:
    repo: DeploymentRepositoryInterface = SqlDeploymentRepository(db=session)
    record = repo.create(
        strategy_id="01HSTRAT...",
        execution_mode="paper",
        emergency_posture="flatten_all",
        deployed_by="01HUSER...",
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DeploymentRepositoryInterface(ABC):
    """
    Abstract port for deployment data access.

    Implementations:
    - MockDeploymentRepository   — in-memory, for unit tests
    - SqlDeploymentRepository    — SQLAlchemy-backed, for production

    Responsibilities:
    - Create, read, and update deployment records.
    - Record state transition audit entries.

    Does NOT:
    - Enforce state machine rules (service layer responsibility).
    - Contain business logic.
    """

    @abstractmethod
    def create(
        self,
        *,
        strategy_id: str,
        execution_mode: str,
        emergency_posture: str,
        risk_limits: dict[str, Any],
        custom_posture_config: dict[str, Any] | None,
        deployed_by: str,
    ) -> dict[str, Any]:
        """
        Persist a new deployment in 'created' state.

        Args:
            strategy_id: ULID of the strategy being deployed.
            execution_mode: One of 'shadow', 'paper', 'live'.
            emergency_posture: One of 'flatten_all', 'cancel_open', 'hold', 'custom'.
            risk_limits: Serialised RiskLimits dict.
            custom_posture_config: Custom posture config (nullable).
            deployed_by: ULID of the deploying user.

        Returns:
            Dict with all deployment fields including generated id and state='created'.

        Example:
            record = repo.create(
                strategy_id="01HSTRAT...",
                execution_mode="paper",
                emergency_posture="flatten_all",
                risk_limits={"max_position_size": "10000"},
                custom_posture_config=None,
                deployed_by="01HUSER...",
            )
        """

    @abstractmethod
    def get_by_id(self, deployment_id: str) -> dict[str, Any] | None:
        """
        Retrieve a deployment by primary key.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Deployment dict or None if not found.

        Example:
            record = repo.get_by_id("01HDEPLOY...")
        """

    @abstractmethod
    def update_state(
        self,
        *,
        deployment_id: str,
        new_state: str,
    ) -> dict[str, Any]:
        """
        Update the state of a deployment.

        Args:
            deployment_id: ULID of the deployment.
            new_state: The new state value.

        Returns:
            Updated deployment dict.

        Raises:
            NotFoundError: deployment_id does not exist.

        Example:
            updated = repo.update_state(
                deployment_id="01HDEPLOY...",
                new_state="pending_approval",
            )
        """

    @abstractmethod
    def record_transition(
        self,
        *,
        deployment_id: str,
        from_state: str,
        to_state: str,
        actor: str,
        reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Record an audit entry for a state transition.

        Args:
            deployment_id: ULID of the deployment.
            from_state: State before the transition.
            to_state: State after the transition.
            actor: Identity string (e.g. 'user:<ulid>').
            reason: Human-readable reason for the transition.
            correlation_id: Distributed tracing ID.

        Returns:
            Dict representing the recorded transition event.

        Example:
            event = repo.record_transition(
                deployment_id="01HDEPLOY...",
                from_state="created",
                to_state="pending_approval",
                actor="user:01HUSER...",
                reason="Submitted for approval",
                correlation_id="corr-001",
            )
        """

    @abstractmethod
    def update_risk_limits(
        self,
        *,
        deployment_id: str,
        risk_limits: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Update the risk limits for a deployment.

        Args:
            deployment_id: ULID of the deployment.
            risk_limits: New risk limits dict.

        Returns:
            Updated deployment dict.

        Raises:
            NotFoundError: deployment_id does not exist.

        Example:
            updated = repo.update_risk_limits(
                deployment_id="01HDEPLOY...",
                risk_limits={"max_position_size": "10000"},
            )
        """

    @abstractmethod
    def list_transitions(
        self,
        *,
        deployment_id: str,
    ) -> list[dict[str, Any]]:
        """
        List all recorded state transitions for a deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of transition event dicts, ordered by timestamp ascending.

        Example:
            transitions = repo.list_transitions(deployment_id="01HDEPLOY...")
        """

    @abstractmethod
    def list_by_state(self, *, state: str) -> list[dict[str, Any]]:
        """
        List all deployments currently in a given lifecycle state.

        Args:
            state: Deployment state to filter by (e.g. 'active',
                'pending_approval', 'paused').

        Returns:
            List of deployment dicts. Empty list if none match. Each dict
            carries the same shape as get_by_id() / create() returns,
            including the execution_mode field so callers can do further
            client-side filtering (e.g. PeriodicReconciliationJob filters
            for execution_mode='live').

        Example:
            active = repo.list_by_state(state="active")
            live_active = [d for d in active if d["execution_mode"] == "live"]
        """
