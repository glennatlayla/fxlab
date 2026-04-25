"""
SQL repository for deployment lifecycle management.

Responsibilities:
- Persist deployment records and state updates via SQLAlchemy.
- Record deployment state transitions in the deployment_transitions table.
- Generate ULID primary keys for new records.

Does NOT:
- Enforce state machine rules (service layer responsibility).
- Contain business logic or policy gate logic.
- Emit audit events to external systems.

Dependencies:
- SQLAlchemy Session (injected via get_db).
- libs.contracts.models.Deployment ORM model.
- libs.contracts.models.DeploymentTransition ORM model.

Error conditions:
- NotFoundError: raised by update_state when deployment_id does not exist.

Example:
    db = next(get_db())
    repo = SqlDeploymentRepository(db=db)
    record = repo.create(
        strategy_id="01HSTRAT...",
        execution_mode="paper",
        emergency_posture="flatten_all",
        risk_limits={},
        custom_posture_config=None,
        deployed_by="01HUSER...",
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)
from libs.contracts.models import Deployment, DeploymentTransition

logger = structlog.get_logger(__name__)


def _generate_ulid() -> str:
    """
    Generate a cryptographically random, time-ordered ULID for new records.

    Uses python-ulid which is thread-safe and produces spec-compliant
    26-character Crockford base32 ULIDs with millisecond-precision
    timestamps and 80 bits of cryptographic randomness.

    Returns:
        26-character ULID string (Crockford base32).
    """
    import ulid as _ulid

    return str(_ulid.ULID())


def _deployment_to_dict(deployment: Deployment) -> dict[str, Any]:
    """
    Convert a Deployment ORM instance to a plain dict for cross-layer transport.

    Args:
        deployment: Deployment ORM instance.

    Returns:
        Dict with all deployment fields, timestamps as ISO strings.
    """
    return {
        "id": deployment.id,
        "strategy_id": deployment.strategy_id,
        "environment": deployment.environment,
        "status": deployment.status,
        "state": deployment.state,
        "execution_mode": deployment.execution_mode,
        "emergency_posture": deployment.emergency_posture,
        "risk_limits": deployment.risk_limits or {},
        "custom_posture_config": deployment.custom_posture_config,
        "deployed_by": deployment.deployed_by,
        "created_at": (deployment.created_at.isoformat() if deployment.created_at else None),
        "updated_at": (deployment.updated_at.isoformat() if deployment.updated_at else None),
    }


def _transition_to_dict(transition: DeploymentTransition) -> dict[str, Any]:
    """
    Convert a DeploymentTransition ORM instance to a plain dict.

    Args:
        transition: DeploymentTransition ORM instance.

    Returns:
        Dict with all transition fields.
    """
    return {
        "id": transition.id,
        "deployment_id": transition.deployment_id,
        "from_state": transition.from_state,
        "to_state": transition.to_state,
        "actor": transition.actor,
        "reason": transition.reason,
        "correlation_id": transition.correlation_id,
        "timestamp": (
            transition.transitioned_at.isoformat() if transition.transitioned_at else None
        ),
    }


class SqlDeploymentRepository(DeploymentRepositoryInterface):
    """
    SQLAlchemy-backed repository for deployment lifecycle management.

    Responsibilities:
    - Create deployment records with ULID primary keys.
    - Update deployment state.
    - Record state transition audit entries.
    - List transition history.

    Does NOT:
    - Enforce state machine rules.
    - Contain business logic.

    Dependencies:
        db: SQLAlchemy Session, injected by the caller.

    Example:
        repo = SqlDeploymentRepository(db=session)
        record = repo.create(strategy_id="01HSTRAT...", ...)
    """

    def __init__(self, db: Any) -> None:
        """
        Initialise with an active SQLAlchemy session.

        Args:
            db: An open SQLAlchemy Session from get_db().
        """
        self._db = db

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
            Dict with all deployment fields including generated id.
        """
        deployment_id = _generate_ulid()

        # Map execution_mode to environment for backward compatibility
        environment = execution_mode if execution_mode in ("paper", "live") else "research"

        deployment = Deployment(
            id=deployment_id,
            strategy_id=strategy_id,
            environment=environment,
            status="pending",
            state="created",
            execution_mode=execution_mode,
            emergency_posture=emergency_posture,
            risk_limits=risk_limits,
            custom_posture_config=custom_posture_config,
            deployed_by=deployed_by,
        )
        self._db.add(deployment)
        self._db.flush()

        logger.debug(
            "deployment_created",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            execution_mode=execution_mode,
        )

        return _deployment_to_dict(deployment)

    def get_by_id(self, deployment_id: str) -> dict[str, Any] | None:
        """
        Retrieve a deployment by primary key.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Deployment dict or None if not found.
        """
        deployment = self._db.get(Deployment, deployment_id)
        if deployment is None:
            return None
        return _deployment_to_dict(deployment)

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
        deployment = self._db.get(Deployment, deployment_id)
        if deployment is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")

        deployment.state = new_state
        deployment.updated_at = datetime.now(tz=timezone.utc)
        self._db.flush()

        logger.debug(
            "deployment_state_updated",
            deployment_id=deployment_id,
            new_state=new_state,
        )

        return _deployment_to_dict(deployment)

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
        transition = DeploymentTransition(
            id=_generate_ulid(),
            deployment_id=deployment_id,
            from_state=from_state,
            to_state=to_state,
            actor=actor,
            reason=reason,
            correlation_id=correlation_id,
            transitioned_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(transition)
        self._db.flush()

        logger.debug(
            "deployment_transition_recorded",
            deployment_id=deployment_id,
            from_state=from_state,
            to_state=to_state,
            actor=actor,
            correlation_id=correlation_id,
        )

        return _transition_to_dict(transition)

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
        deployment = self._db.get(Deployment, deployment_id)
        if deployment is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")

        deployment.risk_limits = risk_limits
        deployment.updated_at = datetime.now(tz=timezone.utc)
        self._db.flush()

        logger.debug(
            "deployment_risk_limits_updated",
            deployment_id=deployment_id,
        )

        return _deployment_to_dict(deployment)

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
            List of transition event dicts ordered by transitioned_at ascending.
        """
        transitions = (
            self._db.query(DeploymentTransition)
            .filter(DeploymentTransition.deployment_id == deployment_id)
            .order_by(DeploymentTransition.transitioned_at.asc())
            .all()
        )
        return [_transition_to_dict(t) for t in transitions]

    def list_by_state(self, *, state: str) -> list[dict[str, Any]]:
        """
        List all deployments currently in a given lifecycle state.

        Returns plain dicts so the caller (e.g. PeriodicReconciliationJob)
        can filter further on fields like execution_mode without binding to
        the SQLAlchemy model class.
        """
        deployments = self._db.query(Deployment).filter(Deployment.state == state).all()
        return [_deployment_to_dict(d) for d in deployments]
