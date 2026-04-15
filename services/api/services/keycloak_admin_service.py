"""
Keycloak Admin REST API client service.

Responsibilities:
- Proxy user management operations to the Keycloak Admin REST API.
- Obtain and cache admin access tokens using client credentials grant.
- Translate Keycloak API responses to application-level dicts.

Does NOT:
- Enforce caller authorization (routes use require_scope).
- Manage Keycloak realm configuration or client setup.
- Handle token validation (see KeycloakTokenValidator).

Dependencies:
- SecretProviderInterface (injected): for KEYCLOAK_ADMIN_CLIENT_SECRET.
- urllib (stdlib): HTTP calls to Keycloak Admin API.
- structlog: Structured logging.

Error conditions:
- Network failure → ExternalServiceError.
- Keycloak 4xx/5xx → ExternalServiceError with status detail.

Example:
    service = KeycloakAdminService(
        keycloak_url="http://keycloak:8080",
        realm="fxlab",
        client_id="fxlab-api",
        secret_provider=env_secret_provider,
    )
    users = service.list_users()
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

import structlog

from libs.contracts.interfaces.secret_provider import SecretProviderInterface
from services.api.middleware.correlation import correlation_id_var
from services.api.services.interfaces.keycloak_admin_service_interface import (
    KeycloakAdminServiceInterface,
)

logger = structlog.get_logger(__name__)


class KeycloakAdminService(KeycloakAdminServiceInterface):
    """
    Wraps the Keycloak Admin REST API for user management.

    Responsibilities:
    - List, create, and manage users in the configured realm.
    - Obtain admin tokens via client_credentials grant.
    - Cache admin tokens for their lifetime (minus safety margin).

    Does NOT:
    - Validate caller authorization.
    - Manage realm or client configuration.

    Dependencies:
        keycloak_url: Base URL of the Keycloak server.
        realm: Keycloak realm name.
        client_id: Confidential client ID with service account enabled.
        secret_provider: SecretProviderInterface for client secret retrieval.

    Example:
        service = KeycloakAdminService(
            keycloak_url="http://keycloak:8080",
            realm="fxlab",
            client_id="fxlab-api",
            secret_provider=secret_provider,
        )
        users = service.list_users()
    """

    def __init__(
        self,
        keycloak_url: str,
        realm: str,
        client_id: str,
        secret_provider: SecretProviderInterface,
    ) -> None:
        self._keycloak_url = keycloak_url.rstrip("/")
        self._realm = realm
        self._client_id = client_id
        self._secret_provider = secret_provider

        # Fail-fast: validate required secret is available at init time,
        # not at first request time (where it would surface as a 502).
        try:
            secret_provider.get_secret("KEYCLOAK_ADMIN_CLIENT_SECRET")
        except KeyError:
            raise RuntimeError(
                "KEYCLOAK_ADMIN_CLIENT_SECRET is not configured in the SecretProvider. "
                "This secret is required for KeycloakAdminService to obtain admin tokens. "
                "Set it via environment variable or your secret management backend."
            )

        # Admin token cache
        self._admin_token: str = ""
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_users(self, first: int = 0, max_results: int = 100) -> list[dict[str, Any]]:
        """
        List users in the Keycloak realm.

        Args:
            first: Pagination offset.
            max_results: Maximum users to return.

        Returns:
            List of user representation dicts from Keycloak.

        Raises:
            RuntimeError: If the Keycloak API call fails.

        Example:
            users = service.list_users(first=0, max_results=50)
        """
        url = f"{self._admin_base_url}/users?first={first}&max={max_results}"
        return self._admin_get(url)

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
            RuntimeError: If the Keycloak API call fails.

        Example:
            result = service.create_user("newuser@fxlab.io", "newuser@fxlab.io")
        """
        body: dict[str, Any] = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": enabled,
            "emailVerified": False,
        }
        if temporary_password:
            body["credentials"] = [
                {
                    "type": "password",
                    "value": temporary_password,
                    "temporary": True,
                }
            ]

        url = f"{self._admin_base_url}/users"
        response_headers = self._admin_post(url, body)

        # Keycloak returns 201 with Location header containing the user URL
        location = response_headers.get("Location", "")
        user_id = location.rsplit("/", 1)[-1] if location else ""

        return {"user_id": user_id}

    def update_user_roles(self, user_id: str, roles: list[str]) -> None:
        """
        Assign realm roles to a user.

        Fetches available realm roles, filters to requested names, and
        assigns them via the Keycloak role-mapping endpoint.

        Args:
            user_id: Keycloak user ID.
            roles: List of realm role names to assign.

        Raises:
            RuntimeError: If the Keycloak API call fails.

        Example:
            service.update_user_roles("user-uuid", ["operator", "viewer"])
        """
        # Fetch available realm roles
        available_roles = self._admin_get(f"{self._admin_base_url}/roles")
        role_objects = [r for r in available_roles if r.get("name") in roles]

        # Assign via role-mapping endpoint
        url = f"{self._admin_base_url}/users/{user_id}/role-mappings/realm"
        self._admin_post(url, role_objects)

    def reset_password(self, user_id: str) -> None:
        """
        Set a temporary password for a user, forcing password change on next login.

        Args:
            user_id: Keycloak user ID.

        Raises:
            RuntimeError: If the Keycloak API call fails.

        Example:
            service.reset_password("user-uuid")
        """
        import secrets

        temp_password = secrets.token_urlsafe(16)
        url = f"{self._admin_base_url}/users/{user_id}/reset-password"
        body = {
            "type": "password",
            "value": temp_password,
            "temporary": True,
        }
        self._admin_put(url, body)

    # ------------------------------------------------------------------
    # Internal: admin token management
    # ------------------------------------------------------------------

    @property
    def _admin_base_url(self) -> str:
        """Admin API base URL for the configured realm."""
        return f"{self._keycloak_url}/admin/realms/{self._realm}"

    def _get_admin_token(self) -> str:
        """
        Obtain or return cached admin access token via client_credentials grant.

        Returns:
            Bearer access token string.

        Raises:
            RuntimeError: If token request fails.
        """
        now = time.monotonic()
        if self._admin_token and now < self._token_expires_at:
            return self._admin_token

        client_secret = self._secret_provider.get_secret("KEYCLOAK_ADMIN_CLIENT_SECRET")
        token_url = f"{self._keycloak_url}/realms/{self._realm}/protocol/openid-connect/token"
        data = (
            f"grant_type=client_credentials"
            f"&client_id={self._client_id}"
            f"&client_secret={client_secret}"
        ).encode()

        req = urllib.request.Request(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        ctx = self._log_context()
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                token_data = json.loads(response.read())
        except urllib.error.URLError as exc:
            logger.error(
                "keycloak_admin.token_request_failed",
                error=str(exc),
                **ctx,
            )
            raise RuntimeError(f"Failed to obtain Keycloak admin token: {exc}") from exc

        self._admin_token = token_data["access_token"]
        # Cache with 30s safety margin
        expires_in = token_data.get("expires_in", 60)
        self._token_expires_at = now + max(expires_in - 30, 10)

        logger.debug(
            "keycloak_admin.token_obtained",
            expires_in=expires_in,
            **ctx,
        )
        return self._admin_token

    # ------------------------------------------------------------------
    # Internal: HTTP helpers
    # ------------------------------------------------------------------

    def _admin_get(self, url: str) -> Any:
        """Execute authenticated GET against Keycloak Admin API."""
        token = self._get_admin_token()
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        ctx = self._log_context()
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read())
        except urllib.error.URLError as exc:
            logger.error("keycloak_admin.get_failed", url=url, error=str(exc), **ctx)
            raise RuntimeError(f"Keycloak Admin API GET failed: {exc}") from exc

    def _admin_post(self, url: str, body: Any) -> dict[str, str]:
        """Execute authenticated POST against Keycloak Admin API. Returns response headers."""
        token = self._get_admin_token()
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        ctx = self._log_context()
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return dict(response.headers)
        except urllib.error.URLError as exc:
            logger.error("keycloak_admin.post_failed", url=url, error=str(exc), **ctx)
            raise RuntimeError(f"Keycloak Admin API POST failed: {exc}") from exc

    def _admin_put(self, url: str, body: Any) -> None:
        """Execute authenticated PUT against Keycloak Admin API."""
        token = self._get_admin_token()
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        ctx = self._log_context()
        try:
            with urllib.request.urlopen(req, timeout=15):
                pass  # 204 No Content expected
        except urllib.error.URLError as exc:
            logger.error("keycloak_admin.put_failed", url=url, error=str(exc), **ctx)
            raise RuntimeError(f"Keycloak Admin API PUT failed: {exc}") from exc

    @staticmethod
    def _log_context() -> dict[str, str]:
        """Build common structured log fields."""
        return {
            "component": "keycloak_admin",
            "correlation_id": correlation_id_var.get("no-corr"),
        }
