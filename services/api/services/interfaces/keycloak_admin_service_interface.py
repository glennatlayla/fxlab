"""
Interface for Keycloak Admin operations.

Responsibilities:
- Define the abstract contract for Keycloak user management proxying.

Does NOT:
- Contain any implementation (see KeycloakAdminService).
- Handle authentication or authorization (caller enforces RBAC).

Dependencies:
- None (pure interface).

Example:
    class KeycloakAdminService(KeycloakAdminServiceInterface):
        def list_users(self) -> list[dict]: ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class KeycloakAdminServiceInterface(ABC):
    """
    Abstract contract for Keycloak Admin REST API operations.

    Responsibilities:
    - List, create, and manage Keycloak users.
    - Assign roles and trigger password resets.

    Does NOT:
    - Validate caller authorization (routes enforce RBAC).
    - Manage Keycloak realm or client configuration.

    Example:
        service: KeycloakAdminServiceInterface = keycloak_admin
        users = service.list_users()
    """

    @abstractmethod
    def list_users(self, first: int = 0, max_results: int = 100) -> list[dict[str, Any]]:
        """
        List users in the Keycloak realm.

        Args:
            first: Pagination offset.
            max_results: Maximum number of users to return.

        Returns:
            List of user representation dicts.
        """

    @abstractmethod
    def create_user(
        self,
        username: str,
        email: str,
        first_name: str = "",
        last_name: str = "",
        enabled: bool = True,
        temporary_password: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new user in Keycloak.

        Args:
            username: Login username.
            email: Email address.
            first_name: First name.
            last_name: Last name.
            enabled: Whether the account is active.
            temporary_password: Initial password (marked temporary).

        Returns:
            Dict with user_id of the created user.

        Raises:
            ExternalServiceError: If Keycloak API call fails.
        """

    @abstractmethod
    def update_user_roles(self, user_id: str, roles: list[str]) -> None:
        """
        Assign realm roles to a user (replaces existing realm role assignments).

        Args:
            user_id: Keycloak user ID.
            roles: List of realm role names to assign.

        Raises:
            ExternalServiceError: If Keycloak API call fails.
        """

    @abstractmethod
    def reset_password(self, user_id: str) -> None:
        """
        Trigger a password reset for a user (sends reset email or sets temporary password).

        Args:
            user_id: Keycloak user ID.

        Raises:
            ExternalServiceError: If Keycloak API call fails.
        """
