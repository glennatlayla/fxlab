"""
Audit trail completeness enforcement via FastAPI dependency injection.

Purpose:
    Provide a FastAPI dependency that wraps route handlers with automatic
    audit logging. Every state-changing operation on financial entities
    must produce an immutable audit record.

Responsibilities:
    - Record audit events after successful route handler execution.
    - Extract actor identity from authenticated user context.
    - Extract object_id from path parameters or request body.
    - Extract correlation_id from context variable.
    - Extract source from X-Client-Source header.
    - Write to audit ledger via SQLAlchemy session.
    - Log failures without failing the request.

Does NOT:
    - Fail the request if audit write fails (soft failure).
    - Perform business logic validation.
    - Handle authentication or authorisation.

Dependencies:
    - FastAPI (Depends, Request, HTTPException).
    - sqlalchemy.orm: Database session for writing audit events.
    - services.api.auth: AuthenticatedUser identity extraction.
    - services.api.middleware.correlation: Correlation ID context variable.
    - services.api.db: SQLAlchemy session dependency.
    - libs.contracts.audit: write_audit_event() function.
    - structlog: Structured logging.

Error conditions:
    - Audit repository write fails → log ERROR but do not fail the request.
    - User object not authenticated → do not log audit event.

Example:
    @router.post("/{deployment_id}/activate")
    async def activate_kill_switch(
        deployment_id: str,
        body: ActivateBody,
        user: AuthenticatedUser = Depends(require_scope("deployments:write")),
        _audit: None = Depends(audit_action(
            action="kill_switch.activate",
            object_type="kill_switch",
            extract_object_id="deployment_id",
        )),
    ):
        # Business logic here
        ...
"""

from __future__ import annotations

from collections.abc import Callable

import structlog
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from libs.contracts.audit import write_audit_event
from services.api.auth import AuthenticatedUser, get_current_user
from services.api.db import get_db
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)


def audit_action(
    action: str,
    object_type: str,
    *,
    extract_object_id: Callable | str | None = None,
    extract_details: Callable | None = None,
) -> Callable:
    """
    FastAPI dependency factory that records an audit event after the route handler succeeds.

    This dependency factory returns a FastAPI-compatible dependency function that:
    1. Records an audit event AFTER the route handler completes successfully.
    2. Extracts actor, object_id, correlation_id, and source from the request context.
    3. Writes to the audit ledger (AuditEvent table).
    4. Never fails the request if audit write fails.

    The dependency works by:
    - Being injected as a parameter in the route handler (via Depends()).
    - Waiting for the handler to complete.
    - Recording the audit event asynchronously after success.

    Args:
        action: Action verb in dot notation (e.g., "kill_switch.activate", "order.submit_live").
                This identifies the operation being audited.
        object_type: Entity type name (e.g., "kill_switch", "order", "approval").
        extract_object_id: How to extract the object_id:
            - None: No object_id recorded (action-level only).
            - str: Path parameter name (e.g., "deployment_id" extracts from request.path_params).
            - Callable: Function(request, path_params) -> str that extracts object_id.
        extract_details: Optional callable(request, path_params) -> dict for additional metadata.
                        If provided, the returned dict is merged into the audit event metadata.

    Returns:
        A FastAPI dependency callable that will record an audit event after the
        route handler completes.

    Raises:
        Nothing directly. Audit write failures are logged at ERROR level but
        do not fail the request.

    Example:
        # Path parameter extraction
        Depends(audit_action(
            action="kill_switch.activate",
            object_type="kill_switch",
            extract_object_id="deployment_id",
        ))

        # Callable extraction
        def extract_approval_id(request, path_params):
            return path_params.get("approval_id")

        Depends(audit_action(
            action="approval.approve",
            object_type="approval",
            extract_object_id=extract_approval_id,
        ))

        # With details
        def extract_details(request, path_params):
            return {"decision": "approved"}

        Depends(audit_action(
            action="approval.approve",
            object_type="approval",
            extract_object_id="approval_id",
            extract_details=extract_details,
        ))
    """

    async def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: AuthenticatedUser | None = Depends(get_current_user),
    ) -> None:
        """
        Dependency that schedules an audit event write after the route handler completes.

        The audit write happens after the route handler returns, so we capture
        the successful completion of the operation.

        Args:
            request: The current HTTP request.
            db: SQLAlchemy session for writing audit events.
            user: Authenticated user (from JWT token). May be None if route is unauthenticated.

        Returns:
            None. This dependency has no meaningful return value.
        """
        # Schedule the audit write to happen in a background task
        # after the response is prepared but before it's sent to the client.
        _register_audit_callback(
            request=request,
            action=action,
            object_type=object_type,
            extract_object_id=extract_object_id,
            extract_details=extract_details,
            user=user,
            db=db,
        )

    return dependency


def _register_audit_callback(
    request: Request,
    action: str,
    object_type: str,
    extract_object_id: Callable | str | None,
    extract_details: Callable | None,
    user: AuthenticatedUser | None,
    db: Session,
) -> None:
    """
    Register an audit write callback in the request state.

    The callback is executed after the route handler returns but before
    the response is sent (via a background task in the response).

    Args:
        request: HTTP request object.
        action: Action verb (e.g., "kill_switch.activate").
        object_type: Entity type (e.g., "kill_switch").
        extract_object_id: Strategy for extracting object_id.
        extract_details: Optional callable for extracting additional metadata.
        user: Authenticated user (optional).
        db: SQLAlchemy session for audit write.
    """
    if not hasattr(request.state, "_audit_callbacks"):
        request.state._audit_callbacks = []

    request.state._audit_callbacks.append(
        _make_audit_callback(
            action=action,
            object_type=object_type,
            extract_object_id=extract_object_id,
            extract_details=extract_details,
            user=user,
            db=db,
            request=request,
        )
    )


def _make_audit_callback(
    action: str,
    object_type: str,
    extract_object_id: Callable | str | None,
    extract_details: Callable | None,
    user: AuthenticatedUser | None,
    db: Session,
    request: Request,
) -> Callable:
    """
    Create a callback function that records an audit event.

    This callback is invoked AFTER the route handler completes successfully.
    It extracts context information and writes an immutable audit ledger entry.

    Args:
        action: Action verb (e.g., "kill_switch.activate").
        object_type: Entity type (e.g., "kill_switch").
        extract_object_id: Strategy for extracting object_id.
        extract_details: Optional callable for extracting additional metadata.
        user: Authenticated user (optional).
        db: SQLAlchemy session for audit write.
        request: HTTP request object (for path params, headers).

    Returns:
        A callable() that executes the audit write.
    """

    def audit_callback() -> None:
        """Execute the audit write after route handler succeeds."""
        # If no authenticated user, do not audit. The operation succeeded,
        # but we cannot attribute it to anyone.
        if not user:
            logger.debug(
                "audit_action.skipped_no_user",
                action=action,
                object_type=object_type,
                reason="no_authenticated_user",
            )
            return

        try:
            # Extract object_id
            object_id = None
            if extract_object_id:
                if isinstance(extract_object_id, str):
                    # Extract from path parameters
                    object_id = request.path_params.get(extract_object_id)
                elif callable(extract_object_id):
                    # Call the extraction function
                    # We can only access request and path params at this point.
                    try:
                        object_id = extract_object_id(request, request.path_params)
                    except Exception as e:
                        logger.warning(
                            "audit_action.object_id_extraction_failed",
                            action=action,
                            object_type=object_type,
                            error=str(e),
                        )
                        object_id = None

            # Extract details metadata
            metadata = {}
            if extract_details:
                try:
                    metadata = extract_details(request, request.path_params)
                except Exception as e:
                    logger.warning(
                        "audit_action.details_extraction_failed",
                        action=action,
                        object_type=object_type,
                        error=str(e),
                    )

            # Extract source from X-Client-Source header
            source = request.headers.get("X-Client-Source")

            # Extract correlation_id from context variable
            correlation_id = correlation_id_var.get("no-corr")

            # Write the audit event
            event_id = write_audit_event(
                session=db,
                actor=f"user:{user.user_id}",
                action=action,
                object_id=object_id or "",
                object_type=object_type,
                metadata={
                    "correlation_id": correlation_id,
                    **(metadata or {}),
                },
                source=source,
            )

            logger.info(
                "audit_action.event_recorded",
                action=action,
                object_type=object_type,
                object_id=object_id,
                actor=user.user_id,
                correlation_id=correlation_id,
                event_id=event_id,
            )

        except Exception as e:
            # Never fail the request due to audit failure.
            # This is a soft failure — log it and continue.
            logger.error(
                "audit_action.write_failed",
                action=action,
                object_type=object_type,
                error=str(e),
                exc_info=True,
            )

    return audit_callback


__all__ = [
    "audit_action",
]
