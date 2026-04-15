"""
Admin API routes for secret management and Keycloak user administration.

Responsibilities:
- Expose secret metadata and rotation endpoints for the admin panel.
- Proxy user management operations to Keycloak via KeycloakAdminService.
- Enforce admin-only access via require_scope("admin:manage").

Does NOT:
- Contain business logic (delegates to SecretProvider and KeycloakAdminService).
- Manage authentication (handled by auth.py middleware).

Dependencies:
- SecretProviderInterface (injected via get_secret_provider dependency).
- KeycloakAdminServiceInterface (injected via get_keycloak_admin dependency).
- require_scope("admin:manage") for authorization.

Error conditions:
- 401: Missing or invalid authentication token.
- 403: Caller lacks admin:manage scope.
- 404: Requested secret key not found for rotation.
- 502: Keycloak Admin API communication failure.

Example:
    GET  /admin/secrets              → list secret metadata
    POST /admin/secrets/{key}/rotate → rotate a specific secret
    GET  /admin/users                → list Keycloak users
    POST /admin/users                → create Keycloak user
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import Field

from libs.contracts.base import FXLabBaseModel
from libs.contracts.interfaces.secret_provider import SecretProviderInterface
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SecretMetadataResponse(FXLabBaseModel):
    """Metadata about a managed secret (no values exposed)."""

    key: str = Field(..., description="Secret identifier")
    source: str = Field(..., description="Origin (environment, vault, memory)")
    is_set: bool = Field(..., description="Whether the secret has a value")
    last_rotated: str | None = Field(None, description="ISO timestamp of last rotation")
    description: str = Field("", description="Human-readable description")


class RotateSecretRequest(FXLabBaseModel):
    """Request body for secret rotation."""

    new_value: str = Field(..., description="New secret value", min_length=1)


class RotateSecretResponse(FXLabBaseModel):
    """Response after successful secret rotation."""

    key: str
    status: str = "rotated"


#: Maximum number of items returned per list request.
MAX_PAGE_SIZE = 500


class KeycloakUserResponse(FXLabBaseModel):
    """Typed representation of a Keycloak user (subset of Keycloak user entity)."""

    id: str = Field(..., description="Keycloak user UUID")
    username: str = Field("", description="Login username")
    email: str = Field("", description="Email address")
    firstName: str = Field("", description="First name")
    lastName: str = Field("", description="Last name")
    enabled: bool = Field(True, description="Whether account is active")
    emailVerified: bool = Field(False, description="Whether email is verified")


class CreateUserRequest(FXLabBaseModel):
    """Request to create a new Keycloak user."""

    username: str = Field(..., description="Login username", min_length=1)
    email: str = Field(..., description="Email address", min_length=3)
    first_name: str = Field("", description="First name")
    last_name: str = Field("", description="Last name")
    temporary_password: str | None = Field(None, description="Initial temporary password")


class CreateUserResponse(FXLabBaseModel):
    """Response after user creation."""

    user_id: str = Field(..., description="Keycloak user ID")
    status: str = "created"


class UpdateRolesRequest(FXLabBaseModel):
    """Request to update a user's realm roles."""

    roles: list[str] = Field(..., description="Realm role names to assign", min_length=1)


# ---------------------------------------------------------------------------
# Dependency injection — overridden by main.py wiring
# ---------------------------------------------------------------------------

_secret_provider: SecretProviderInterface | None = None
_keycloak_admin: Any = None


def set_secret_provider(provider: SecretProviderInterface) -> None:
    """Wire the SecretProvider instance for admin routes (called at app startup)."""
    global _secret_provider
    _secret_provider = provider


def set_keycloak_admin(service: Any) -> None:
    """Wire the KeycloakAdminService instance for admin routes (called at app startup)."""
    global _keycloak_admin
    _keycloak_admin = service


def get_secret_provider() -> SecretProviderInterface:
    """FastAPI dependency: return the wired SecretProvider."""
    if _secret_provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SecretProvider not configured.",
        )
    return _secret_provider


def get_keycloak_admin():
    """FastAPI dependency: return the wired KeycloakAdminService."""
    if _keycloak_admin is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak admin service not configured.",
        )
    return _keycloak_admin


# ---------------------------------------------------------------------------
# Secret management endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/secrets",
    response_model=list[SecretMetadataResponse],
    summary="List secret metadata",
)
async def list_secrets(
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
    provider: SecretProviderInterface = Depends(get_secret_provider),
) -> list[SecretMetadataResponse]:
    """
    Return metadata for all managed secrets (admin only).

    Secret values are never exposed — only key names, source, and set/unset status.

    Returns:
        List of SecretMetadataResponse objects.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "admin.secrets.list",
        user_id=user.user_id,
        correlation_id=corr_id,
        component="admin",
    )

    secrets = provider.list_secrets()
    return [
        SecretMetadataResponse(
            key=s.key,
            source=s.source,
            is_set=s.is_set,
            last_rotated=s.last_rotated.isoformat() if s.last_rotated else None,
            description=s.description,
        )
        for s in secrets
    ]


@router.get(
    "/secrets/expiring",
    response_model=list[SecretMetadataResponse],
    summary="List secrets approaching rotation deadline",
)
async def list_expiring_secrets(
    threshold_days: int = 90,
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
    provider: SecretProviderInterface = Depends(get_secret_provider),
) -> list[SecretMetadataResponse]:
    """
    Return metadata for secrets that need rotation attention (admin only).

    A secret is "expiring" if it has never been rotated, or if its last
    rotation was more than threshold_days ago.

    Args:
        threshold_days: Number of days since last rotation to consider
            a secret as expiring. Default: 90.

    Returns:
        List of SecretMetadataResponse for secrets needing rotation.

    Example:
        GET /admin/secrets/expiring?threshold_days=90
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "admin.secrets.list_expiring",
        user_id=user.user_id,
        threshold_days=threshold_days,
        correlation_id=corr_id,
        component="admin",
    )

    # EnvSecretProvider has list_expiring(); fallback to list_secrets() for others
    if hasattr(provider, "list_expiring"):
        secrets = provider.list_expiring(threshold_days)
    else:
        # For providers without list_expiring, return all secrets as
        # a conservative "all need attention" response
        secrets = provider.list_secrets()

    return [
        SecretMetadataResponse(
            key=s.key,
            source=s.source,
            is_set=s.is_set,
            last_rotated=s.last_rotated.isoformat() if s.last_rotated else None,
            description=s.description,
        )
        for s in secrets
    ]


@router.post(
    "/secrets/{key}/rotate",
    response_model=RotateSecretResponse,
    summary="Rotate a secret",
)
async def rotate_secret(
    key: str,
    body: RotateSecretRequest,
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
    provider: SecretProviderInterface = Depends(get_secret_provider),
) -> RotateSecretResponse:
    """
    Rotate (replace) a secret value (admin only).

    The new value is written through the SecretProvider. Not all providers
    support rotation (e.g. EnvSecretProvider raises NotImplementedError).

    Returns:
        RotateSecretResponse with key and status.

    Raises:
        HTTPException 400: If the provider does not support rotation.
        HTTPException 404: If the key is not a recognized secret.
    """
    import hashlib
    from datetime import datetime, timezone

    corr_id = correlation_id_var.get("no-corr")
    rotation_timestamp = datetime.now(timezone.utc).isoformat()

    logger.info(
        "admin.secrets.rotate.initiated",
        key=key,
        user_id=user.user_id,
        user_email=user.email,
        user_role=user.role,
        correlation_id=corr_id,
        timestamp=rotation_timestamp,
        component="admin",
        operation="secret_rotation",
    )

    try:
        provider.rotate_secret(key, body.new_value)
    except NotImplementedError:
        logger.warning(
            "admin.secrets.rotate.unsupported",
            key=key,
            user_id=user.user_id,
            provider_type=type(provider).__name__,
            correlation_id=corr_id,
            component="admin",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This secret provider does not support rotation. "
            "Environment variables cannot be rotated at runtime.",
        )
    except KeyError as exc:
        # EnvSecretProvider raises KeyError when KEY_NEW env var is not set
        logger.warning(
            "admin.secrets.rotate.missing_new_env",
            key=key,
            user_id=user.user_id,
            detail=str(exc),
            correlation_id=corr_id,
            component="admin",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot rotate '{key}': environment variable {key}_NEW "
            "is not set. Set it before triggering rotation.",
        ) from None
    except ValueError as exc:
        # EnvSecretProvider raises ValueError when new_value mismatches KEY_NEW
        logger.warning(
            "admin.secrets.rotate.value_mismatch",
            key=key,
            user_id=user.user_id,
            detail=str(exc),
            correlation_id=corr_id,
            component="admin",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None

    # Audit: log new value fingerprint (first 8 chars of SHA-256) — never log the value itself.
    new_value_fingerprint = hashlib.sha256(body.new_value.encode()).hexdigest()[:8]
    logger.info(
        "admin.secrets.rotate.completed",
        key=key,
        user_id=user.user_id,
        user_email=user.email,
        new_value_fingerprint=new_value_fingerprint,
        correlation_id=corr_id,
        timestamp=rotation_timestamp,
        component="admin",
        operation="secret_rotation",
        result="success",
    )

    return RotateSecretResponse(key=key, status="rotated")


# ---------------------------------------------------------------------------
# Keycloak user management endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/users",
    response_model=list[KeycloakUserResponse],
    summary="List Keycloak users",
)
async def list_users(
    first: int = 0,
    max_results: int = 100,
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
    keycloak_admin=Depends(get_keycloak_admin),
) -> list[dict[str, Any]]:
    """
    List users in the Keycloak realm (admin only).

    Proxies to Keycloak Admin REST API.  Pagination is capped at MAX_PAGE_SIZE
    to prevent resource exhaustion.

    Returns:
        List of typed user representations.
    """
    # Enforce pagination bounds to prevent resource exhaustion
    if first < 0:
        first = 0
    if max_results < 1:
        max_results = 1
    if max_results > MAX_PAGE_SIZE:
        max_results = MAX_PAGE_SIZE

    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "admin.users.list",
        user_id=user.user_id,
        first=first,
        max_results=max_results,
        correlation_id=corr_id,
        component="admin",
    )

    try:
        return keycloak_admin.list_users(first=first, max_results=max_results)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Keycloak communication error: {exc}",
        )


@router.post(
    "/users",
    response_model=CreateUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Keycloak user",
)
async def create_user(
    body: CreateUserRequest,
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
    keycloak_admin=Depends(get_keycloak_admin),
) -> CreateUserResponse:
    """
    Create a new user in Keycloak (admin only).

    Returns:
        CreateUserResponse with user_id.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "admin.users.create",
        username=body.username,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="admin",
    )

    try:
        result = keycloak_admin.create_user(
            username=body.username,
            email=body.email,
            first_name=body.first_name,
            last_name=body.last_name,
            temporary_password=body.temporary_password,
        )
        return CreateUserResponse(user_id=result.get("user_id", ""), status="created")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Keycloak communication error: {exc}",
        )


@router.put(
    "/users/{user_id}/roles",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Assign roles to user",
)
async def update_user_roles(
    user_id: str,
    body: UpdateRolesRequest,
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
    keycloak_admin=Depends(get_keycloak_admin),
) -> None:
    """
    Assign realm roles to a Keycloak user (admin only).
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "admin.users.update_roles",
        target_user_id=user_id,
        roles=body.roles,
        admin_user_id=user.user_id,
        correlation_id=corr_id,
        component="admin",
    )

    try:
        keycloak_admin.update_user_roles(user_id, body.roles)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Keycloak communication error: {exc}",
        )


@router.post(
    "/users/{user_id}/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Reset user password",
)
async def reset_user_password(
    user_id: str,
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
    keycloak_admin=Depends(get_keycloak_admin),
) -> None:
    """
    Trigger a password reset for a Keycloak user (admin only).
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "admin.users.reset_password",
        target_user_id=user_id,
        admin_user_id=user.user_id,
        correlation_id=corr_id,
        component="admin",
    )

    try:
        keycloak_admin.reset_password(user_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Keycloak communication error: {exc}",
        )
