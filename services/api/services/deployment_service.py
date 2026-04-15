"""
Deployment lifecycle management service with formal state machine.

Responsibilities:
- Create deployments with declared emergency posture and risk limits.
- Manage deployment state transitions per the DEPLOYMENT_TRANSITIONS map.
- Enforce policy gates before activation:
  1. Deployment must be in 'approved' state.
  2. Emergency posture must be declared (spec rule 6).
- Record an audit trail for every state transition.
- Report deployment health metrics.

Does NOT:
- Persist data directly (delegates to DeploymentRepositoryInterface).
- Execute trades or manage broker adapters.
- Know about HTTP or any transport mechanism.
- Manage kill switches or reconciliation (separate services).

Dependencies:
- DeploymentRepositoryInterface (injected): data persistence.
- structlog: structured logging.

Error conditions:
- NotFoundError: deployment_id does not exist.
- StateTransitionError: attempted transition violates state machine.
- ValidationError: pre-activation gate failed.

Example:
    repo = MockDeploymentRepository()
    service = DeploymentService(repo=repo)
    deployment = service.create_deployment(
        request=DeploymentCreateRequest(...),
        deployed_by="01HUSER...",
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

from typing import Any

import structlog

from libs.contracts.deployment import (
    DEPLOYMENT_TRANSITIONS,
    DeploymentCreateRequest,
    DeploymentHealthResponse,
    DeploymentState,
    RiskLimits,
)
from libs.contracts.errors import NotFoundError, StateTransitionError, ValidationError
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)
from libs.contracts.interfaces.deployment_service_interface import (
    DeploymentServiceInterface,
)

logger = structlog.get_logger(__name__)


class DeploymentService(DeploymentServiceInterface):
    """
    Production implementation of the deployment lifecycle service.

    Responsibilities:
    - Enforce the deployment state machine via _transition().
    - Enforce pre-activation policy gates.
    - Delegate persistence to the injected repository.
    - Emit structured log events on every lifecycle action.

    Does NOT:
    - Know about HTTP, API routes, or serialisation formats.
    - Execute orders or talk to broker adapters.
    - Persist data directly.

    Dependencies:
        repo: DeploymentRepositoryInterface (injected).

    Example:
        service = DeploymentService(repo=SqlDeploymentRepository(db=session))
        result = service.create_deployment(request=req, deployed_by=uid, correlation_id=cid)
    """

    def __init__(self, *, repo: DeploymentRepositoryInterface) -> None:
        """
        Initialise with a deployment repository.

        Args:
            repo: DeploymentRepositoryInterface implementation.
        """
        self._repo = repo

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_deployment_or_raise(self, deployment_id: str) -> dict[str, Any]:
        """
        Fetch a deployment by ID or raise NotFoundError.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Deployment dict.

        Raises:
            NotFoundError: deployment_id does not exist.
        """
        record = self._repo.get_by_id(deployment_id)
        if record is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")
        return record

    def _transition(
        self,
        *,
        deployment_id: str,
        target_state: DeploymentState,
        actor: str,
        reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Execute a single state transition with validation and audit.

        This is the core state machine enforcement method. Every public
        lifecycle method delegates here to guarantee:
        1. The transition is valid per DEPLOYMENT_TRANSITIONS.
        2. The repository state is updated atomically.
        3. An audit record is written.

        Args:
            deployment_id: ULID of the deployment.
            target_state: Desired target state.
            actor: Identity string (e.g. 'user:<ulid>').
            reason: Human-readable transition reason.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: transition is invalid.
        """
        record = self._get_deployment_or_raise(deployment_id)
        current_state_str = record["state"]

        # Parse current state — this validates the stored value
        try:
            current_state = DeploymentState(current_state_str)
        except ValueError:
            raise StateTransitionError(
                f"Deployment {deployment_id} is in unknown state '{current_state_str}'",
                current_state=current_state_str,
                attempted_state=target_state.value,
            )

        # Check if transition is valid
        allowed = DEPLOYMENT_TRANSITIONS.get(current_state, frozenset())
        if target_state not in allowed:
            raise StateTransitionError(
                f"Cannot transition deployment {deployment_id} from "
                f"'{current_state.value}' to '{target_state.value}'. "
                f"Allowed transitions: {[s.value for s in allowed]}",
                current_state=current_state.value,
                attempted_state=target_state.value,
            )

        # Perform the transition
        updated = self._repo.update_state(
            deployment_id=deployment_id,
            new_state=target_state.value,
        )

        # Record audit event
        self._repo.record_transition(
            deployment_id=deployment_id,
            from_state=current_state.value,
            to_state=target_state.value,
            actor=actor,
            reason=reason,
            correlation_id=correlation_id,
        )

        logger.info(
            "deployment_state_transition",
            deployment_id=deployment_id,
            from_state=current_state.value,
            to_state=target_state.value,
            actor=actor,
            reason=reason,
            correlation_id=correlation_id,
        )

        return updated

    # ------------------------------------------------------------------
    # Public interface methods
    # ------------------------------------------------------------------

    def create_deployment(
        self,
        *,
        request: DeploymentCreateRequest,
        deployed_by: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Create a new deployment in 'created' state.

        Args:
            request: Validated creation payload.
            deployed_by: ULID of the deploying user.
            correlation_id: Distributed tracing ID.

        Returns:
            Dict with deployment fields including id, state='created'.
        """
        record = self._repo.create(
            strategy_id=request.strategy_id,
            execution_mode=request.execution_mode,
            emergency_posture=request.emergency_posture,
            risk_limits=request.risk_limits.model_dump(),
            custom_posture_config=request.custom_posture_config,
            deployed_by=deployed_by,
        )

        logger.info(
            "deployment_created",
            deployment_id=record["id"],
            strategy_id=request.strategy_id,
            execution_mode=request.execution_mode,
            emergency_posture=request.emergency_posture,
            deployed_by=deployed_by,
            correlation_id=correlation_id,
        )

        return record

    def submit_for_approval(
        self,
        *,
        deployment_id: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Transition deployment from 'created' to 'pending_approval'.

        Args:
            deployment_id: ULID of the deployment.
            actor: Identity string.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='pending_approval'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: deployment is not in 'created' state.
        """
        return self._transition(
            deployment_id=deployment_id,
            target_state=DeploymentState.pending_approval,
            actor=actor,
            reason="Submitted for approval",
            correlation_id=correlation_id,
        )

    def approve_deployment(
        self,
        *,
        deployment_id: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Transition deployment from 'pending_approval' to 'approved'.

        Args:
            deployment_id: ULID of the deployment.
            actor: Identity string.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='approved'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: deployment is not in 'pending_approval' state.
        """
        return self._transition(
            deployment_id=deployment_id,
            target_state=DeploymentState.approved,
            actor=actor,
            reason="Approved for activation",
            correlation_id=correlation_id,
        )

    def activate_deployment(
        self,
        *,
        deployment_id: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Transition deployment from 'approved' to 'active' via 'activating'.

        Pre-activation gates:
        1. Must be in 'approved' state.
        2. Emergency posture must be declared (spec rule 6).

        Args:
            deployment_id: ULID of the deployment.
            actor: Identity string.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='active'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: not in 'approved' state.
            ValidationError: emergency posture not declared.
        """
        # Pre-activation gate: verify emergency posture is declared
        record = self._get_deployment_or_raise(deployment_id)
        emergency_posture = record.get("emergency_posture", "")
        if not emergency_posture:
            raise ValidationError(
                f"Deployment {deployment_id} cannot activate without a declared "
                f"emergency posture (spec rule 6). Current posture: '{emergency_posture}'"
            )

        # Two-step transition: approved → activating → active
        self._transition(
            deployment_id=deployment_id,
            target_state=DeploymentState.activating,
            actor=actor,
            reason="Activation initiated — pre-activation gates passed",
            correlation_id=correlation_id,
        )

        return self._transition(
            deployment_id=deployment_id,
            target_state=DeploymentState.active,
            actor=actor,
            reason="Activation complete",
            correlation_id=correlation_id,
        )

    def freeze_deployment(
        self,
        *,
        deployment_id: str,
        reason: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Freeze an active deployment.

        Args:
            deployment_id: ULID of the deployment.
            reason: Freeze reason.
            actor: Identity string.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='frozen'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: not in 'active' state.
        """
        return self._transition(
            deployment_id=deployment_id,
            target_state=DeploymentState.frozen,
            actor=actor,
            reason=reason,
            correlation_id=correlation_id,
        )

    def unfreeze_deployment(
        self,
        *,
        deployment_id: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Unfreeze a frozen deployment back to active.

        Args:
            deployment_id: ULID of the deployment.
            actor: Identity string.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='active'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: not in 'frozen' state.
        """
        return self._transition(
            deployment_id=deployment_id,
            target_state=DeploymentState.active,
            actor=actor,
            reason="Deployment unfrozen",
            correlation_id=correlation_id,
        )

    def deactivate_deployment(
        self,
        *,
        deployment_id: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Gracefully deactivate a deployment (active/frozen → deactivating → deactivated).

        Args:
            deployment_id: ULID of the deployment.
            actor: Identity string.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='deactivated'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: not in 'active' or 'frozen' state.
        """
        # Two-step: active/frozen → deactivating → deactivated
        self._transition(
            deployment_id=deployment_id,
            target_state=DeploymentState.deactivating,
            actor=actor,
            reason="Graceful deactivation initiated",
            correlation_id=correlation_id,
        )

        return self._transition(
            deployment_id=deployment_id,
            target_state=DeploymentState.deactivated,
            actor=actor,
            reason="Deactivation complete",
            correlation_id=correlation_id,
        )

    def rollback_deployment(
        self,
        *,
        deployment_id: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Emergency rollback from active/frozen to rolled_back.

        Args:
            deployment_id: ULID of the deployment.
            actor: Identity string.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='rolled_back'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: not in 'active' or 'frozen' state.
        """
        return self._transition(
            deployment_id=deployment_id,
            target_state=DeploymentState.rolled_back,
            actor=actor,
            reason="Emergency rollback",
            correlation_id=correlation_id,
        )

    def get_deployment(
        self,
        *,
        deployment_id: str,
    ) -> dict[str, Any]:
        """
        Retrieve a deployment by ID.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Deployment dict.

        Raises:
            NotFoundError: deployment_id does not exist.
        """
        return self._get_deployment_or_raise(deployment_id)

    def get_deployment_health(
        self,
        *,
        deployment_id: str,
    ) -> DeploymentHealthResponse:
        """
        Get real-time health summary for a deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            DeploymentHealthResponse with current metrics.

        Raises:
            NotFoundError: deployment_id does not exist.
        """
        record = self._get_deployment_or_raise(deployment_id)

        # Build risk limits from stored data
        risk_limits_data = record.get("risk_limits", {})
        risk_limits = RiskLimits(**risk_limits_data) if risk_limits_data else RiskLimits()

        return DeploymentHealthResponse(
            deployment_id=record["id"],
            state=record["state"],
            execution_mode=record["execution_mode"],
            emergency_posture=record["emergency_posture"],
            risk_limits=risk_limits,
            # Real metrics would come from order/position repositories
            # For now, return safe defaults
            open_order_count=0,
            position_count=0,
            total_unrealized_pnl="0",
            total_realized_pnl="0",
            adapter_connected=False,
            last_heartbeat_at=None,
        )
