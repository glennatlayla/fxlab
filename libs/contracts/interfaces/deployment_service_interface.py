"""
Abstract deployment service interface for Phase 4 execution layer.

Responsibilities:
- Define the deployment lifecycle operations as abstract methods.
- Serve as the contract between the controller (routes) and the service layer.
- Enforce that all implementations provide state machine management,
  policy gate enforcement, and audit event emission.

Does NOT:
- Contain business logic or state transition rules.
- Access the database or external services.
- Know about HTTP or any transport mechanism.

Dependencies:
- libs.contracts.deployment: DeploymentCreateRequest, DeploymentHealthResponse,
  DeploymentResponse.

Error conditions:
- NotFoundError: deployment_id does not exist.
- StateTransitionError: attempted transition violates state machine rules.
- ValidationError: precondition not met (e.g. no emergency posture declared).

Example:
    service: DeploymentServiceInterface = DeploymentService(repo=repo, ...)
    deployment = service.create_deployment(
        request=DeploymentCreateRequest(...),
        deployed_by="01HUSER...",
    )
    service.activate_deployment(deployment_id=deployment["id"], actor="user:01HUSER...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from libs.contracts.deployment import DeploymentCreateRequest, DeploymentHealthResponse


class DeploymentServiceInterface(ABC):
    """
    Port for deployment lifecycle management.

    Responsibilities:
    - Create deployments with declared emergency posture and risk limits.
    - Manage deployment state transitions (activate, freeze, unfreeze, rollback).
    - Enforce policy gates before activation (readiness, approval, posture).
    - Report deployment health for monitoring.

    Does NOT:
    - Persist data directly (delegates to repository).
    - Know about HTTP or API layer concerns.
    - Execute trades (execution services do that).

    Implementations:
    - DeploymentService: production implementation with state machine.
    """

    @abstractmethod
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
            request: Validated deployment creation payload.
            deployed_by: ULID of the deploying user.
            correlation_id: Distributed tracing ID.

        Returns:
            Dict with deployment fields including id, state='created'.

        Raises:
            ValidationError: If the strategy does not exist or is not deployable.

        Example:
            result = service.create_deployment(
                request=DeploymentCreateRequest(...),
                deployed_by="01HUSER...",
                correlation_id="corr-001",
            )
            # result["state"] == "created"
        """

    @abstractmethod
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
            actor: Identity string of the requesting user.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='pending_approval'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: deployment is not in 'created' state.
        """

    @abstractmethod
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
            actor: Identity string of the approving user.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='approved'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: deployment is not in 'pending_approval' state.
        """

    @abstractmethod
    def activate_deployment(
        self,
        *,
        deployment_id: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Transition deployment from 'approved' to 'activating' then 'active'.

        Pre-activation gates enforced:
        1. Deployment must be in 'approved' state.
        2. Emergency posture must be declared (spec rule 6).
        3. Readiness evidence must exist (future: readiness check service).

        Args:
            deployment_id: ULID of the deployment.
            actor: Identity string of the activating user.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='active'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: deployment is not in 'approved' state.
            ValidationError: pre-activation gate failed.
        """

    @abstractmethod
    def freeze_deployment(
        self,
        *,
        deployment_id: str,
        reason: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Freeze an active deployment — rejects all new order submissions.

        Args:
            deployment_id: ULID of the deployment.
            reason: Human-readable freeze reason.
            actor: Identity string.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='frozen'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: deployment is not in 'active' state.
        """

    @abstractmethod
    def unfreeze_deployment(
        self,
        *,
        deployment_id: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Unfreeze a frozen deployment — resumes order processing.

        Args:
            deployment_id: ULID of the deployment.
            actor: Identity string.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='active'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: deployment is not in 'frozen' state.
        """

    @abstractmethod
    def deactivate_deployment(
        self,
        *,
        deployment_id: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Gracefully deactivate a deployment (active or frozen → deactivating → deactivated).

        Args:
            deployment_id: ULID of the deployment.
            actor: Identity string.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='deactivated'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: deployment is not in 'active' or 'frozen' state.
        """

    @abstractmethod
    def rollback_deployment(
        self,
        *,
        deployment_id: str,
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Emergency rollback — move from active/frozen to rolled_back.

        Args:
            deployment_id: ULID of the deployment.
            actor: Identity string.
            correlation_id: Distributed tracing ID.

        Returns:
            Updated deployment dict with state='rolled_back'.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: deployment is not in 'active' or 'frozen' state.
        """

    @abstractmethod
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
            Deployment dict with all fields.

        Raises:
            NotFoundError: deployment_id does not exist.
        """

    @abstractmethod
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
