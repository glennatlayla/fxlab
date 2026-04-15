"""
In-memory mock deployment repository for unit testing.

Responsibilities:
- Implement DeploymentRepositoryInterface with dict-backed storage.
- Provide seed() and introspection helpers for test setup and assertions.
- Match the behavioural contract of the production SQL repository.

Does NOT:
- Persist data across process restarts.
- Contain business logic or state machine rules.

Dependencies:
- libs.contracts.interfaces.deployment_repository_interface.DeploymentRepositoryInterface

Error conditions:
- NotFoundError: deployment_id does not exist (same as SQL repo).

Example:
    repo = MockDeploymentRepository()
    record = repo.seed(
        strategy_id="01HSTRAT...",
        execution_mode="paper",
        emergency_posture="flatten_all",
        deployed_by="01HUSER...",
    )
    assert repo.get_by_id(record["id"]) is not None
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)


def _generate_test_ulid() -> str:
    """
    Generate a ULID for test use.

    Uses python-ulid which produces spec-compliant 26-character Crockford
    base32 ULIDs.

    Returns:
        26-character ULID string.
    """
    import ulid as _ulid

    return str(_ulid.ULID())


class MockDeploymentRepository(DeploymentRepositoryInterface):
    """
    In-memory implementation of DeploymentRepositoryInterface for unit tests.

    Responsibilities:
    - Store deployment records in a dict keyed by deployment ID.
    - Store transition audit events in a list per deployment.
    - Provide seed() for prepopulating test data.
    - Provide introspection helpers for assertions.

    Does NOT:
    - Enforce state machine rules (service responsibility).
    - Persist across test runs.

    Example:
        repo = MockDeploymentRepository()
        record = repo.create(
            strategy_id="01HSTRAT...",
            execution_mode="paper",
            emergency_posture="flatten_all",
            risk_limits={},
            custom_posture_config=None,
            deployed_by="01HUSER...",
        )
        assert repo.count() == 1
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._transitions: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Interface methods
    # ------------------------------------------------------------------

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
        Create a new deployment record in 'created' state.

        Args:
            strategy_id: ULID of the strategy being deployed.
            execution_mode: One of 'shadow', 'paper', 'live'.
            emergency_posture: One of 'flatten_all', 'cancel_open', 'hold', 'custom'.
            risk_limits: Serialised RiskLimits dict.
            custom_posture_config: Custom posture config (nullable).
            deployed_by: ULID of the deploying user.

        Returns:
            Dict with generated id, state='created', and all fields.
        """
        deployment_id = _generate_test_ulid()
        now = datetime.now(tz=timezone.utc).isoformat()
        record: dict[str, Any] = {
            "id": deployment_id,
            "strategy_id": strategy_id,
            "state": "created",
            "execution_mode": execution_mode,
            "emergency_posture": emergency_posture,
            "risk_limits": dict(risk_limits),
            "custom_posture_config": custom_posture_config,
            "deployed_by": deployed_by,
            "created_at": now,
            "updated_at": now,
        }
        self._store[deployment_id] = record
        self._transitions[deployment_id] = []
        return dict(record)

    def get_by_id(self, deployment_id: str) -> dict[str, Any] | None:
        """
        Retrieve a deployment by primary key.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Deployment dict or None if not found.
        """
        record = self._store.get(deployment_id)
        if record is None:
            return None
        return dict(record)

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
        """
        record = self._store.get(deployment_id)
        if record is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")
        record["state"] = new_state
        record["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        return dict(record)

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
            actor: Identity string.
            reason: Human-readable reason.
            correlation_id: Distributed tracing ID.

        Returns:
            Dict representing the recorded transition event.
        """
        event: dict[str, Any] = {
            "id": _generate_test_ulid(),
            "deployment_id": deployment_id,
            "from_state": from_state,
            "to_state": to_state,
            "actor": actor,
            "reason": reason,
            "correlation_id": correlation_id,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        if deployment_id not in self._transitions:
            self._transitions[deployment_id] = []
        self._transitions[deployment_id].append(event)
        return dict(event)

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
        """
        record = self._store.get(deployment_id)
        if record is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")
        record["risk_limits"] = dict(risk_limits)
        record["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        return dict(record)

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
            List of transition event dicts ordered by timestamp ascending.
        """
        return [dict(e) for e in self._transitions.get(deployment_id, [])]

    # ------------------------------------------------------------------
    # Test helpers / introspection
    # ------------------------------------------------------------------

    def seed(
        self,
        *,
        deployment_id: str | None = None,
        strategy_id: str = "01HTESTSTRT000000000000001",
        state: str = "created",
        execution_mode: str = "paper",
        emergency_posture: str = "flatten_all",
        risk_limits: dict[str, Any] | None = None,
        custom_posture_config: dict[str, Any] | None = None,
        deployed_by: str = "01HTESTSRA0000000000000001",
    ) -> dict[str, Any]:
        """
        Prepopulate a deployment record for test setup.

        Unlike create(), this allows setting an arbitrary initial state
        and deployment_id for test determinism.

        Args:
            deployment_id: Fixed ULID (auto-generated if None).
            strategy_id: Strategy ULID (defaults to test value).
            state: Initial state (defaults to 'created').
            execution_mode: Execution mode (defaults to 'paper').
            emergency_posture: Emergency posture (defaults to 'flatten_all').
            risk_limits: Risk limits dict (defaults to empty).
            custom_posture_config: Custom posture config (defaults to None).
            deployed_by: Deployer ULID (defaults to test value).

        Returns:
            Seeded deployment dict.

        Example:
            record = repo.seed(state="approved", execution_mode="live")
        """
        if deployment_id is None:
            deployment_id = _generate_test_ulid()
        now = datetime.now(tz=timezone.utc).isoformat()
        record: dict[str, Any] = {
            "id": deployment_id,
            "strategy_id": strategy_id,
            "state": state,
            "execution_mode": execution_mode,
            "emergency_posture": emergency_posture,
            "risk_limits": risk_limits if risk_limits is not None else {},
            "custom_posture_config": custom_posture_config,
            "deployed_by": deployed_by,
            "created_at": now,
            "updated_at": now,
        }
        self._store[deployment_id] = record
        self._transitions[deployment_id] = []
        return dict(record)

    def count(self) -> int:
        """Return the number of stored deployments."""
        return len(self._store)

    def get_all(self) -> list[dict[str, Any]]:
        """Return all stored deployments."""
        return [dict(r) for r in self._store.values()]

    def get_transitions_count(self, deployment_id: str) -> int:
        """Return the number of recorded transitions for a deployment."""
        return len(self._transitions.get(deployment_id, []))

    def clear(self) -> None:
        """Remove all stored data."""
        self._store.clear()
        self._transitions.clear()
