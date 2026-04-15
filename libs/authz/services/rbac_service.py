"""
Concrete RBAC service backed by the User database table.

Responsibilities:
- Look up a user's role from the ``users`` table via SQLAlchemy session.
- Check permissions against the canonical ROLE_PERMISSIONS mapping.
- Update a user's role in the database (admin operation).

Does NOT:
- Manage JWT tokens or sessions.
- Cache roles (the session handles identity-map caching).
- Contain HTTP or framework-specific logic.

Dependencies:
- SQLAlchemy Session (injected).
- libs.contracts.models.User (ORM model).
- libs.authz.interfaces.rbac (RBACInterface, Role, Permission, ROLE_PERMISSIONS).
- libs.contracts.errors (NotFoundError).

Example:
    from sqlalchemy.orm import Session
    from libs.authz.services.rbac_service import ConcreteRBACService

    svc = ConcreteRBACService(session=db_session)
    if not svc.has_permission(user_id, Permission.REQUEST_PROMOTION):
        raise HTTPException(403, "Forbidden")
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from libs.authz.interfaces.rbac import (
    ROLE_PERMISSIONS,
    Permission,
    RBACInterface,
    Role,
)
from libs.contracts.errors import NotFoundError
from libs.contracts.models import User

logger = structlog.get_logger(__name__)


class ConcreteRBACService(RBACInterface):
    """
    Database-backed RBAC service.

    Responsibilities:
    - Validate user roles against the actual User record in the database.
    - Enforce the ROLE_PERMISSIONS policy for permission checks.
    - Provide set_role to update a user's role (admin operation).

    Does NOT:
    - Trust JWT claims alone — always reads the DB.
    - Manage authentication tokens.
    - Perform I/O other than through the injected session.

    Dependencies:
    - session (injected): SQLAlchemy session for database access.

    Raises:
    - NotFoundError: When the user_id does not exist in the database.

    Example:
        svc = ConcreteRBACService(session=db_session)
        role = svc.get_role("01HUSER...")
        assert svc.has_permission("01HUSER...", Permission.VIEW_AUDIT)
    """

    def __init__(self, session: Session) -> None:
        """
        Initialise with a SQLAlchemy database session.

        Args:
            session: Active SQLAlchemy session for reading/writing User records.
        """
        self._session = session

    def _get_user(self, user_id: str) -> User:
        """
        Fetch the User record or raise NotFoundError.

        Args:
            user_id: ULID of the user.

        Returns:
            The User ORM instance.

        Raises:
            NotFoundError: If no user with this ID exists.
        """
        user = self._session.get(User, user_id)
        if user is None:
            logger.warning(
                "rbac.user_not_found",
                user_id=user_id,
                component="ConcreteRBACService",
            )
            raise NotFoundError(f"User {user_id!r} not found")
        return user

    def set_role(self, user_id: str, role: Role) -> None:
        """
        Update the user's role in the database.

        Args:
            user_id: ULID of the user.
            role: New role to assign.

        Raises:
            NotFoundError: If the user does not exist.
        """
        user = self._get_user(user_id)
        old_role = user.role
        user.role = role.value
        self._session.commit()
        logger.info(
            "rbac.role_updated",
            user_id=user_id,
            old_role=old_role,
            new_role=role.value,
            component="ConcreteRBACService",
        )

    def get_role(self, user_id: str) -> Role:
        """
        Return the user's role from the database.

        Args:
            user_id: ULID of the user.

        Returns:
            The user's Role enum value.

        Raises:
            NotFoundError: If the user does not exist.
        """
        user = self._get_user(user_id)
        return Role(user.role)

    def has_permission(self, user_id: str, permission: Permission) -> bool:
        """
        Check whether the user's DB-stored role grants the given permission.

        Args:
            user_id: ULID of the user.
            permission: Permission to check.

        Returns:
            True if the user's role grants the permission; False otherwise.

        Raises:
            NotFoundError: If the user does not exist.
        """
        role = self.get_role(user_id)
        granted = permission in ROLE_PERMISSIONS[role]
        logger.debug(
            "rbac.permission_check",
            user_id=user_id,
            role=role.value,
            permission=permission.value,
            granted=granted,
            component="ConcreteRBACService",
        )
        return granted


__all__ = ["ConcreteRBACService"]
