"""
Mock RBAC implementation for unit and integration testing.

Responsibilities:
- Provide an in-memory implementation of RBACInterface.
- Allow test fixtures to configure per-user roles programmatically.
- Enable test assertions on permission checks via call tracking.

Does NOT:
- Connect to a database or external service.
- Contain business logic beyond permission lookup.

Example:
    rbac = MockRBACService()
    rbac.set_role("01HQ...", Role.RESEARCHER)
    assert rbac.has_permission("01HQ...", Permission.REQUEST_PROMOTION)
"""

from typing import Optional

from libs.authz.interfaces.rbac import (
    Permission,
    RBACInterface,
    Role,
    ROLE_PERMISSIONS,
)
from libs.contracts.errors import NotFoundError


class MockRBACService(RBACInterface):
    """
    In-memory RBAC service for unit testing.

    Responsibilities:
    - Store user → role mappings in memory.
    - Return deterministic permission decisions based on ROLE_PERMISSIONS.
    - Track calls for test assertions.

    Does NOT:
    - Persist data between tests.
    - Validate ULIDs.

    Example:
        rbac = MockRBACService()
        rbac.set_role("01HQ...", Role.OPERATOR)
        assert rbac.has_permission("01HQ...", Permission.APPROVE_PROMOTION)
        assert rbac.call_count == 1
    """

    def __init__(self, default_role: Optional[Role] = None) -> None:
        """
        Initialise the mock RBAC service.

        Args:
            default_role: Role to return for any user_id not explicitly
                          registered via set_role().  If None, an unknown
                          user raises NotFoundError.
        """
        self._roles: dict[str, Role] = {}
        self._default_role = default_role
        self.call_count = 0  # total has_permission calls (for assertions)
        self.last_checked_permission: Optional[Permission] = None

    def set_role(self, user_id: str, role: Role) -> None:
        """
        Register a user → role mapping.

        Args:
            user_id: ULID of the user.
            role: Role to assign.
        """
        self._roles[user_id] = role

    def get_role(self, user_id: str) -> Role:
        """
        Return the role for the given user.

        Args:
            user_id: ULID of the user.

        Returns:
            The registered Role, or the default_role if set.

        Raises:
            NotFoundError: If user_id is not registered and no default_role.
        """
        if user_id in self._roles:
            return self._roles[user_id]
        if self._default_role is not None:
            return self._default_role
        raise NotFoundError(f"User {user_id!r} not found in MockRBACService")

    def has_permission(self, user_id: str, permission: Permission) -> bool:
        """
        Check whether the user has the given permission.

        Args:
            user_id: ULID of the user.
            permission: Permission to check.

        Returns:
            True if the user's role grants the permission; False otherwise.

        Raises:
            NotFoundError: If the user is not registered and no default_role.
        """
        self.call_count += 1
        self.last_checked_permission = permission
        role = self.get_role(user_id)
        return permission in ROLE_PERMISSIONS[role]

    # ------------------------------------------------------------------
    # Introspection helpers — for test assertions only
    # ------------------------------------------------------------------

    def get_all_roles(self) -> dict[str, Role]:
        """
        Return a snapshot of all registered user → role mappings.

        Returns:
            A shallow copy of the internal role store, keyed by user_id.

        Example:
            rbac.set_role("01HQ...", Role.ADMIN)
            assert rbac.get_all_roles() == {"01HQ...": Role.ADMIN}
        """
        return dict(self._roles)

    def count_registered(self) -> int:
        """
        Return the number of explicitly registered user → role mappings.

        Returns:
            Integer count of registered users (not counting default_role users).
        """
        return len(self._roles)

    def clear(self) -> None:
        """Reset all registered roles and call tracking (test helper)."""
        self._roles.clear()
        self.call_count = 0
        self.last_checked_permission = None


__all__ = ["MockRBACService"]
