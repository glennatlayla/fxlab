"""
RBAC (Role-Based Access Control) interface.

Responsibilities:
- Define the abstract port for permission checking.
- Declare the Role enum used across all layers.
- Define the Permission enum for granular action-based access control.

Does NOT:
- Contain implementation logic.
- Import from services or infrastructure.

Dependencies:
- None (pure Python + enum)

Example:
    from libs.authz.interfaces.rbac import RBACInterface, Role, Permission

    class MyRBACService(RBACInterface):
        def has_permission(self, user_id: str, permission: Permission) -> bool:
            ...
"""

from abc import ABC, abstractmethod
from enum import Enum


class Role(str, Enum):
    """
    User roles within the FXLab platform.

    Values map directly to the 'role' column in the User ORM model.
    """

    ADMIN = "admin"
    OPERATOR = "operator"
    RESEARCHER = "researcher"
    VIEWER = "viewer"


class Permission(str, Enum):
    """
    Granular permissions for FXLab platform actions.

    Each permission maps to one or more roles via the RBAC policy.
    """

    # Promotion workflow
    REQUEST_PROMOTION = "request_promotion"
    APPROVE_PROMOTION = "approve_promotion"
    REJECT_PROMOTION = "reject_promotion"

    # Override workflow
    REQUEST_OVERRIDE = "request_override"
    VIEW_OVERRIDE = "view_override"

    # Audit
    VIEW_AUDIT = "view_audit"

    # Runs
    VIEW_RUNS = "view_runs"
    VIEW_RUN_RESULTS = "view_run_results"

    # Feeds
    VIEW_FEEDS = "view_feeds"
    VIEW_FEED_HEALTH = "view_feed_health"

    # Queues
    VIEW_QUEUE_CONTENTION = "view_queue_contention"


# ---------------------------------------------------------------------------
# Default role → permission mapping
# ---------------------------------------------------------------------------

#: Maps each Role to the set of Permissions it grants.
#: admin has all permissions.
#: operator can approve/reject and manage overrides.
#: researcher can request promotions and view everything.
#: viewer is read-only.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),  # all permissions
    Role.OPERATOR: frozenset(
        {
            Permission.APPROVE_PROMOTION,
            Permission.REJECT_PROMOTION,
            Permission.REQUEST_OVERRIDE,
            Permission.VIEW_OVERRIDE,
            Permission.VIEW_AUDIT,
            Permission.VIEW_RUNS,
            Permission.VIEW_RUN_RESULTS,
            Permission.VIEW_FEEDS,
            Permission.VIEW_FEED_HEALTH,
            Permission.VIEW_QUEUE_CONTENTION,
        }
    ),
    Role.RESEARCHER: frozenset(
        {
            Permission.REQUEST_PROMOTION,
            Permission.VIEW_OVERRIDE,
            Permission.VIEW_AUDIT,
            Permission.VIEW_RUNS,
            Permission.VIEW_RUN_RESULTS,
            Permission.VIEW_FEEDS,
            Permission.VIEW_FEED_HEALTH,
            Permission.VIEW_QUEUE_CONTENTION,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Permission.VIEW_AUDIT,
            Permission.VIEW_RUNS,
            Permission.VIEW_RUN_RESULTS,
            Permission.VIEW_FEEDS,
            Permission.VIEW_FEED_HEALTH,
            Permission.VIEW_QUEUE_CONTENTION,
        }
    ),
}


class RBACInterface(ABC):
    """
    Abstract port for role-based access control.

    Responsibilities:
    - Assign and look up a user's role.
    - Check whether a user has a specific permission.

    Does NOT:
    - Manage user sessions or JWT tokens.
    - Perform I/O directly (use repository interfaces for that).
    - Cache or pre-load role data from a database.

    Example:
        rbac = ConcreteRBACService(user_repo=repo)
        if not rbac.has_permission(user_id="01HQ...", permission=Permission.REQUEST_PROMOTION):
            raise HTTPException(status_code=403, detail="Forbidden")
    """

    @abstractmethod
    def set_role(self, user_id: str, role: Role) -> None:
        """
        Assign a role to the given user.

        Args:
            user_id: ULID of the user.
            role: Role to assign.
        """

    @abstractmethod
    def get_role(self, user_id: str) -> Role:
        """
        Return the role for the given user.

        Args:
            user_id: ULID of the user.

        Returns:
            The user's Role.

        Raises:
            NotFoundError: If the user does not exist.
        """

    @abstractmethod
    def has_permission(self, user_id: str, permission: Permission) -> bool:
        """
        Check whether a user has the given permission.

        Args:
            user_id: ULID of the user.
            permission: Permission to check.

        Returns:
            True if the user's role grants the permission; False otherwise.

        Raises:
            NotFoundError: If the user does not exist.
        """


__all__ = [
    "Permission",
    "RBACInterface",
    "Role",
    "ROLE_PERMISSIONS",
]
