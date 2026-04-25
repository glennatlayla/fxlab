"""
JWT authentication module for FXLab API.

Purpose:
    Provide HS256 JWT authentication for all protected API endpoints via
    FastAPI's ``Depends()`` dependency injection.

Responsibilities:
    - Create HS256-signed JWTs with standard claims (sub, role, iat, exp, nbf).
    - Validate Bearer tokens on protected endpoints with full RFC 7519 compliance.
    - Enforce token size limits to prevent denial-of-service via oversized tokens.
    - Provide ``get_current_user`` and ``get_optional_user`` FastAPI dependencies.
    - Support a TEST_TOKEN bypass **only** when ``ENVIRONMENT == "test"``.
    - Propagate correlation IDs into all structured log events.
    - Never log token values, secrets, or raw exception messages containing tokens.

Does NOT:
    - Manage user registration or login flows (deferred to OIDC integration).
    - Perform role-based access control (RBAC is a separate concern in authz layer).
    - Store tokens, sessions, or revocation lists.
    - Handle key rotation (single symmetric key; RS256 migration planned).

Dependencies:
    - PyJWT (jwt): HS256 token signing and verification.
    - structlog: Structured logging.
    - FastAPI (Depends, HTTPException, Request): Request dependency injection.
    - services.api.middleware.correlation: Correlation ID context variable.

Error conditions:
    - Missing Authorization header       -> 401 Unauthorized.
    - Malformed Bearer prefix            -> 401 Unauthorized.
    - Token exceeds MAX_TOKEN_BYTES      -> 401 Unauthorized.
    - Expired token                      -> 401 Unauthorized.
    - Token not yet valid (nbf)          -> 401 Unauthorized.
    - Invalid signature / decode error   -> 401 Unauthorized.
    - Missing ``sub`` claim              -> 401 Unauthorized.
    - Missing JWT_SECRET_KEY in non-test -> RuntimeError at startup.

Example:
    from services.api.auth import get_current_user, AuthenticatedUser

    @router.post("/some-endpoint")
    async def endpoint(user: AuthenticatedUser = Depends(get_current_user)):
        print(user.user_id, user.role)
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt
import structlog
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALGORITHM = "HS256"
_ALGORITHMS_ALLOWED = [_ALGORITHM]

#: Maximum raw token size in bytes.  Tokens larger than this are rejected
#: before any cryptographic work is performed, preventing denial-of-service
#: via oversized payloads.  16 KB is generous for any real HS256 JWT.
MAX_TOKEN_BYTES = int(os.environ.get("JWT_MAX_TOKEN_BYTES", 16_384))

#: Default token lifetime in minutes, overridable via JWT_EXPIRATION_MINUTES.
#: Reduced from 60 to 30 to limit blast radius of compromised tokens.
_DEFAULT_EXPIRY_MINUTES = int(os.environ.get("JWT_EXPIRATION_MINUTES", 30))

#: Fallback audience when JWT_AUDIENCE env var is not set.
_FALLBACK_AUDIENCE = "fxlab-api"

#: Fallback issuer when JWT_ISSUER env var is not set.
_FALLBACK_ISSUER = "fxlab"


def _get_audience() -> str:
    """Return the configured JWT audience (read at call time for testability)."""
    return os.environ.get("JWT_AUDIENCE", _FALLBACK_AUDIENCE)


def _get_issuer() -> str:
    """Return the configured JWT issuer (read at call time for testability)."""
    return os.environ.get("JWT_ISSUER", _FALLBACK_ISSUER)


#: Magic token accepted when ENVIRONMENT == "test".
#: Avoids the need for a real secret key during unit test runs.
TEST_TOKEN = "TEST_TOKEN"

#: Fixed identity returned when TEST_TOKEN is used.
TEST_USER_ID = "01HTESTFAKE000000000000000"
TEST_USER_ROLE = "operator"
TEST_USER_EMAIL = "testuser@fxlab.test"

#: Regex for ULID format validation (26 chars, Crockford base32).
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class AuthMode(str, Enum):
    """
    Authentication mode indicating which validation path was used.

    Values:
        LOCAL_JWT: Self-rolled HS256 JWT validated locally.
        KEYCLOAK: RS256 JWT validated against Keycloak JWKS endpoint.

    Example:
        if user.auth_mode == AuthMode.KEYCLOAK:
            # Token was issued and validated by Keycloak
            ...
    """

    LOCAL_JWT = "local_jwt"
    KEYCLOAK = "keycloak"


# ---------------------------------------------------------------------------
# RBAC scope definitions — Phase 3 spec §7.7
# ---------------------------------------------------------------------------

#: Scopes defined in the Phase 3 spec.  Each role maps to the scopes it is
#: allowed to exercise.  Token claims carry a ``scope`` string (space-separated).
ROLE_SCOPES: dict[str, list[str]] = {
    "admin": [
        "strategies:write",
        "runs:write",
        "promotions:request",
        "approvals:write",
        "overrides:request",
        "overrides:approve",
        "exports:read",
        "feeds:read",
        "operator:read",
        "operator:write",
        "audit:read",
        "deployments:read",
        "deployments:write",
        "deployments:approve",
        "live:trade",
        "compliance:read",
        # admin:manage gates the admin sub-tree in the frontend
        # (frontend/src/pages/Admin/* and router.tsx /admin/*).
        # Without it, the seeded admin user gets 403 on every admin
        # page even after Tranche L's frontend↔backend scope alignment.
        # No other role gets this scope; the admin sub-tree is
        # admin-only by design.
        "admin:manage",
    ],
    "operator": [
        "strategies:write",
        "runs:write",
        "promotions:request",
        "overrides:request",
        "exports:read",
        "feeds:read",
        "operator:read",
        "operator:write",
        "audit:read",
        "deployments:read",
        "deployments:write",
        "compliance:read",
    ],
    "live_trader": [
        "strategies:write",
        "runs:write",
        "promotions:request",
        "overrides:request",
        "exports:read",
        "feeds:read",
        "operator:read",
        "audit:read",
        "deployments:read",
        "deployments:write",
        "live:trade",
        "compliance:read",
    ],
    "reviewer": [
        "approvals:write",
        "overrides:approve",
        "exports:read",
        "feeds:read",
        "operator:read",
        "audit:read",
        "deployments:read",
        "deployments:approve",
        "compliance:read",
    ],
    "viewer": [
        "exports:read",
        "feeds:read",
        "operator:read",
        "audit:read",
        "deployments:read",
        "compliance:read",
    ],
}


class AuthenticatedUser(BaseModel):
    """
    Identity extracted from a validated JWT.

    Attributes:
        user_id: ULID of the authenticated user (from ``sub`` claim).
        role: Role string (e.g. "operator", "reviewer", "admin").
        email: Email address from token claims (may be empty string).
        scopes: List of granted scope strings (from ``scope`` claim).
        auth_mode: Which authentication path validated this token.

    Example:
        user = AuthenticatedUser(user_id="01HABC...", role="operator")
        assert "feeds:read" in user.scopes
        assert user.auth_mode == AuthMode.LOCAL_JWT
    """

    user_id: str
    role: str
    email: str = ""
    scopes: list[str] = []
    auth_mode: AuthMode = AuthMode.LOCAL_JWT

    @field_validator("user_id")
    @classmethod
    def _validate_user_id_format(cls, v: str) -> str:
        """Ensure user_id looks like a ULID to reject garbage sub claims."""
        if not _ULID_RE.match(v):
            raise ValueError(f"user_id must be a valid ULID, got length={len(v)}")
        return v

    def has_scope(self, scope: str) -> bool:
        """
        Check whether this user holds a specific scope.

        Args:
            scope: The scope string to check (e.g. "feeds:read").

        Returns:
            True if the scope is in the user's scopes list.

        Example:
            if user.has_scope("overrides:approve"):
                ...
        """
        return scope in self.scopes


# ---------------------------------------------------------------------------
# Secret key management
# ---------------------------------------------------------------------------


def _get_secret_key() -> str:
    """
    Read JWT_SECRET_KEY via SecretProvider (with env fallback).

    In test mode (ENVIRONMENT=test), falls back to a deterministic test
    secret so that ``create_access_token`` works without requiring env
    configuration.  In all other environments, the key MUST be provided
    and MUST be at least 32 bytes.

    Returns:
        The secret key string.

    Raises:
        RuntimeError: If JWT_SECRET_KEY is not set and ENVIRONMENT != "test".
        RuntimeError: If JWT_SECRET_KEY is set but shorter than 32 bytes
            in non-test environments.
    """
    from services.api.infrastructure.secret_provider_factory import get_provider

    try:
        secret = get_provider().get_secret("JWT_SECRET_KEY")
    except KeyError:
        secret = ""
    env = os.environ.get("ENVIRONMENT", "")

    if not secret:
        if env == "test":
            # Deterministic secret for unit tests — NEVER used in production.
            return "test-secret-key-not-for-production"
        raise RuntimeError(
            "JWT_SECRET_KEY environment variable is required in non-test environments. "
            "Set it to a 32+ byte random secret."
        )

    # Enforce minimum key length in non-test environments to prevent weak secrets.
    if env != "test" and len(secret.encode("utf-8")) < 32:
        raise RuntimeError(
            f"JWT_SECRET_KEY must be at least 32 bytes for HS256 security. "
            f"Current key is {len(secret.encode('utf-8'))} bytes."
        )

    return secret


def _get_signing_key() -> str:
    """
    Return the key used to SIGN new tokens.

    When JWT_SECRET_KEY contains comma-separated keys for rotation, the
    first key is always the signing key.  When a single key is provided,
    this is equivalent to ``_get_secret_key()``.

    Returns:
        The signing key string (first key in the list).

    Example:
        key = _get_signing_key()
        token = jwt.encode(payload, key, algorithm="HS256")
    """
    raw = _get_secret_key()
    if "," in raw:
        return raw.split(",")[0].strip()
    return raw


def _get_validation_keys() -> list[str]:
    """
    Return all keys that should be tried when VALIDATING tokens.

    Supports zero-downtime key rotation via comma-separated keys in
    JWT_SECRET_KEY:
        JWT_SECRET_KEY=newkey,oldkey

    The list order is preserved — the first key is the current signing
    key, subsequent keys are previous keys still accepted during the
    rotation window.

    Constraints:
        - At most 3 keys allowed (current + 2 previous).
        - Each key must be at least 32 bytes in non-test environments.
        - Empty key segments are rejected.

    Returns:
        List of key strings, ordered current-first.

    Raises:
        RuntimeError: If any key is empty, too short, or more than 3 keys provided.

    Example:
        keys = _get_validation_keys()
        for key in keys:
            try:
                payload = jwt.decode(token, key, algorithms=["HS256"])
                break
            except jwt.InvalidSignatureError:
                continue
    """
    raw = _get_secret_key()
    env = os.environ.get("ENVIRONMENT", "")

    if "," not in raw:
        return [raw]

    keys = [k.strip() for k in raw.split(",")]

    # Validate: no empty segments
    for i, k in enumerate(keys):
        if not k:
            raise RuntimeError(
                f"JWT_SECRET_KEY contains an empty key segment at position {i}. "
                "Remove trailing commas or empty entries."
            )

    # Validate: max 3 keys to bound validation cost
    if len(keys) > 3:
        raise RuntimeError(
            f"JWT_SECRET_KEY contains {len(keys)} keys, but at most 3 are allowed "
            "(current + 2 previous). Remove older keys that are no longer needed."
        )

    # Validate: each key meets minimum length (non-test only)
    if env != "test":
        for i, k in enumerate(keys):
            if len(k.encode("utf-8")) < 32:
                raise RuntimeError(
                    f"JWT_SECRET_KEY key at position {i} is only "
                    f"{len(k.encode('utf-8'))} bytes — must be at least 32 bytes "
                    f"for HS256 security."
                )

    return keys


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------


def create_access_token(
    user_id: str,
    role: str,
    expires_minutes: int | None = None,
    email: str = "",
    scopes: list[str] | None = None,
) -> str:
    """
    Create an HS256-signed JWT for the given user identity.

    Includes standard claims: ``sub``, ``role``, ``email``, ``scope``,
    ``iat``, ``exp``, and ``nbf`` (not-before, set to ``iat`` so the
    token is immediately valid).

    Args:
        user_id: ULID of the user (placed in ``sub`` claim).
        role: Role string (e.g. "operator").
        expires_minutes: Token lifetime in minutes.  Defaults to
            JWT_EXPIRATION_MINUTES env var, or 60 if unset.
        email: Optional email address to embed in claims.
        scopes: Explicit scope list.  If None, defaults to the scopes
            defined for the given role in ROLE_SCOPES.

    Returns:
        Encoded JWT string.

    Raises:
        RuntimeError: If JWT_SECRET_KEY is missing in non-test environments.

    Example:
        token = create_access_token("01HABC...", "operator", expires_minutes=30)
        # Token will contain scope="strategies:write runs:write ..."
    """
    if expires_minutes is None:
        expires_minutes = _DEFAULT_EXPIRY_MINUTES

    if scopes is None:
        scopes = ROLE_SCOPES.get(role, [])

    # Use _get_signing_key() to always sign with the current (first) key,
    # even when multiple keys are configured for rotation.
    secret = _get_signing_key()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "email": email,
        "scope": " ".join(scopes),
        "jti": str(uuid.uuid4()),  # JWT ID for revocation blacklist lookup
        "aud": _get_audience(),
        "iss": _get_issuer(),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _log_context() -> dict[str, str]:
    """Build common structured log fields including correlation ID."""
    return {
        "component": "auth",
        "correlation_id": correlation_id_var.get("no-corr"),
    }


def _extract_bearer_token(request: Request) -> str | None:
    """
    Extract the Bearer token from the Authorization header.

    Handles RFC 7235 case-insensitive scheme matching (``bearer``,
    ``Bearer``, ``BEARER`` are all accepted).

    Args:
        request: The incoming FastAPI request.

    Returns:
        The raw token string, or None if no Authorization header is present.

    Raises:
        HTTPException(401): If the header is present but does not use
            the Bearer scheme.
        HTTPException(401): If the token exceeds MAX_TOKEN_BYTES.
    """
    auth_header: str | None = request.headers.get("Authorization")
    if auth_header is None:
        return None

    # RFC 7235 §2.1: authentication scheme is case-insensitive
    if auth_header[:7].lower() != "bearer ":
        logger.warning(
            "auth.invalid_scheme",
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must use Bearer scheme.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]

    # Guard against oversized tokens before any crypto work
    if len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
        logger.warning(
            "auth.token_too_large",
            token_bytes=len(token.encode("utf-8")),
            max_bytes=MAX_TOKEN_BYTES,
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token exceeds maximum allowed size.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


# ---------------------------------------------------------------------------
# Keycloak RS256 validator (lazy singleton)
# ---------------------------------------------------------------------------

_keycloak_validator: object | None = None  # noqa: F821, UP037 — lazy import (set to KeycloakTokenValidator at runtime)


def _get_keycloak_validator():
    """
    Return the singleton KeycloakTokenValidator, or None if Keycloak is not configured.

    The validator is created lazily on first call and reused for the process lifetime.
    Keycloak is considered configured when the KEYCLOAK_URL environment variable is set
    to a non-empty value.

    Returns:
        KeycloakTokenValidator instance, or None.
    """
    global _keycloak_validator
    keycloak_url = os.environ.get("KEYCLOAK_URL", "")
    if not keycloak_url:
        return None

    if _keycloak_validator is None:
        from services.api.infrastructure.keycloak_token_validator import (
            KeycloakTokenValidator,
        )

        realm = os.environ.get("KEYCLOAK_REALM", "fxlab")
        client_id = os.environ.get("KEYCLOAK_CLIENT_ID", "fxlab-api")
        _keycloak_validator = KeycloakTokenValidator(
            keycloak_url=keycloak_url,
            realm=realm,
            client_id=client_id,
        )
        logger.info(
            "auth.keycloak_validator_initialized",
            keycloak_url=keycloak_url,
            realm=realm,
            client_id=client_id,
            component="auth",
        )
    return _keycloak_validator


def _try_decode_with_keys(token: str, keys: list[str]) -> dict:
    """
    Attempt to decode a JWT using each key in order.

    Supports zero-downtime key rotation: tries the current key first,
    then falls back to previous keys. Non-signature errors (expired,
    audience mismatch, etc.) are raised immediately — they would fail
    with any key.

    Args:
        token: Raw JWT string.
        keys: List of secret keys to try, ordered current-first.

    Returns:
        Decoded JWT payload dict.

    Raises:
        HTTPException(401): On expired, not-yet-valid, invalid audience/issuer,
            or when no key produces a valid signature.
    """
    decode_options: dict[str, object] = {
        "require": ["sub", "exp", "iat"],
        "verify_exp": True,
        "verify_nbf": True,
        "verify_iat": True,
        "verify_aud": True,
        "verify_iss": True,
    }
    audience = _get_audience()
    issuer = _get_issuer()

    for key in keys:
        try:
            return jwt.decode(
                token,
                key,
                algorithms=_ALGORITHMS_ALLOWED,
                audience=audience,
                issuer=issuer,
                options=decode_options,  # type: ignore[arg-type]
            )
        except jwt.InvalidSignatureError:
            # Signature mismatch — try the next key in the rotation list
            continue
        except jwt.ExpiredSignatureError as exc:
            logger.warning("auth.token_expired", **_log_context())
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except jwt.ImmatureSignatureError as exc:
            logger.warning("auth.token_not_yet_valid", **_log_context())
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token is not yet valid.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except jwt.InvalidAudienceError as exc:
            logger.warning("auth.invalid_audience", **_log_context())
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token audience mismatch.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except jwt.InvalidIssuerError as exc:
            logger.warning("auth.invalid_issuer", **_log_context())
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token issuer mismatch.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except jwt.InvalidTokenError as exc:
            # Intentionally do NOT log exc details — may contain token fragments
            logger.warning("auth.token_invalid", **_log_context())
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    # All keys exhausted — signature did not match any key
    logger.warning(
        "auth.token_invalid_signature",
        keys_tried=len(keys),
        **_log_context(),
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _validate_token(token: str) -> AuthenticatedUser:
    """
    Validate a JWT string and return the authenticated identity.

    Delegation order:
    1. TEST_TOKEN bypass when ENVIRONMENT == "test".
    2. Keycloak RS256 validation when KEYCLOAK_URL is set.
    3. Self-rolled HS256 validation (backward compatibility fallback).
    4. Token revocation check (if jti claim present).

    Args:
        token: Raw JWT string (or the magic TEST_TOKEN).

    Returns:
        AuthenticatedUser with claims extracted from the token.

    Raises:
        HTTPException(401): On expired, not-yet-valid, invalid, revoked, or
            malformed tokens.
    """
    # Test bypass — accept magic token in test environment ONLY
    environment = os.environ.get("ENVIRONMENT", "")
    if environment == "test" and token == TEST_TOKEN:
        logger.debug(
            "auth.test_token_accepted",
            user_id=TEST_USER_ID,
            **_log_context(),
        )
        return AuthenticatedUser(
            user_id=TEST_USER_ID,
            role=TEST_USER_ROLE,
            email=TEST_USER_EMAIL,
            scopes=ROLE_SCOPES.get(TEST_USER_ROLE, []),
        )

    # Keycloak RS256 validation — delegates when KEYCLOAK_URL is configured
    kc_validator = _get_keycloak_validator()
    if kc_validator is not None:
        user = kc_validator.validate_token(token)
        user.auth_mode = AuthMode.KEYCLOAK
        return user

    # Fallback: self-rolled HS256 validation with multi-key rotation support.
    # _get_validation_keys() returns [current_key] or [current, previous, ...]
    # when JWT_SECRET_KEY contains comma-separated keys for zero-downtime rotation.
    validation_keys = _get_validation_keys()
    payload = _try_decode_with_keys(token, validation_keys)

    # Check token revocation (if jti claim present)
    jti = payload.get("jti")
    if jti:
        from services.api.db import SessionLocal
        from services.api.services.token_blacklist_service import TokenBlacklistService

        db = SessionLocal()
        try:
            if TokenBlacklistService(db).is_revoked(jti):
                logger.warning(
                    "auth.token_revoked",
                    jti=jti,
                    **_log_context(),
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        finally:
            db.close()

    # Extract claims — sub is required (enforced above), role defaults to "viewer"
    user_id = payload.get("sub", "")
    if not user_id:
        logger.warning("auth.missing_sub_claim", **_log_context())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required 'sub' claim.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate sub is a proper ULID
    if not _ULID_RE.match(user_id):
        logger.warning(
            "auth.invalid_sub_format",
            sub_length=len(user_id),
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 'sub' claim is not a valid ULID.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract scope claim — space-separated string per OIDC spec
    role = payload.get("role", "viewer")
    scope_str = payload.get("scope", "")
    # Fall back to role-based defaults if no scope claim present
    scopes = scope_str.split() if scope_str else ROLE_SCOPES.get(role, [])

    return AuthenticatedUser(
        user_id=user_id,
        role=role,
        email=payload.get("email", ""),
        scopes=scopes,
    )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def get_current_user(request: Request) -> AuthenticatedUser:
    """
    FastAPI dependency: require a valid JWT and return the identity.

    Use as ``Depends(get_current_user)`` on any route that requires
    authentication.

    Args:
        request: The incoming FastAPI request (injected by FastAPI).

    Returns:
        AuthenticatedUser with user_id, role, and email from the token.

    Raises:
        HTTPException(401): If the Authorization header is missing, the token
            is expired, or the token is invalid.

    Example:
        @router.post("/protected")
        async def protected_endpoint(
            user: AuthenticatedUser = Depends(get_current_user),
        ):
            return {"user_id": user.user_id}
    """
    token = _extract_bearer_token(request)
    if token is None:
        logger.warning("auth.missing_header", **_log_context())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _validate_token(token)


async def get_optional_user(request: Request) -> AuthenticatedUser | None:
    """
    FastAPI dependency: optionally extract identity from a JWT.

    Returns None if no Authorization header is present, allowing the
    endpoint to serve both authenticated and anonymous callers.

    Args:
        request: The incoming FastAPI request (injected by FastAPI).

    Returns:
        AuthenticatedUser if a valid token is present, None otherwise.

    Raises:
        HTTPException(401): If the Authorization header IS present but the
            token is invalid or expired (a bad token is never silently ignored).

    Example:
        @router.get("/public-or-private")
        async def endpoint(
            user: AuthenticatedUser | None = Depends(get_optional_user),
        ):
            if user:
                return {"greeting": f"Hello, {user.user_id}"}
            return {"greeting": "Hello, anonymous"}
    """
    token = _extract_bearer_token(request)
    if token is None:
        return None
    return _validate_token(token)


def require_scope(scope: str):
    """
    Factory that returns a FastAPI dependency enforcing a specific scope.

    Use as ``Depends(require_scope("overrides:approve"))`` on routes that
    require fine-grained authorization beyond authentication.

    Args:
        scope: The OIDC scope string that the caller must hold.

    Returns:
        An async FastAPI dependency function that raises 403 Forbidden
        if the authenticated user lacks the required scope.

    Example:
        @router.post("/overrides/{id}/approve")
        async def approve(
            user: AuthenticatedUser = Depends(require_scope("overrides:approve")),
        ):
            ...
    """

    async def _check_scope(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        """
        Verify the authenticated user holds the required scope.

        Args:
            user: The authenticated user (injected by get_current_user).

        Returns:
            The AuthenticatedUser if the scope check passes.

        Raises:
            HTTPException(403): If the user lacks the required scope.
        """
        if not user.has_scope(scope):
            logger.warning(
                "auth.scope_denied",
                required_scope=scope,
                user_id=user.user_id,
                user_scopes=user.scopes,
                **_log_context(),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient scope. Required: {scope}",
            )
        return user

    return _check_scope


def require_any_scope(*scopes: str):
    """
    Factory that returns a FastAPI dependency enforcing at least ONE of the
    listed scopes (OR logic).

    Use when a route should be accessible to users holding any one of
    several scopes, e.g. the governance list is readable by users with
    either ``approvals:write`` or ``overrides:request``.

    Args:
        *scopes: One or more OIDC scope strings.  The user must hold at
            least one of them.

    Returns:
        An async FastAPI dependency function that raises 403 Forbidden
        if the authenticated user holds none of the required scopes.

    Example:
        @router.get("/governance/")
        async def list_governance(
            user: AuthenticatedUser = Depends(
                require_any_scope("approvals:write", "overrides:request")
            ),
        ):
            ...
    """

    async def _check_any_scope(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        """
        Verify the authenticated user holds at least one of the required scopes.

        Args:
            user: The authenticated user (injected by get_current_user).

        Returns:
            The AuthenticatedUser if any scope check passes.

        Raises:
            HTTPException(403): If the user holds none of the required scopes.
        """
        for s in scopes:
            if user.has_scope(s):
                return user

        logger.warning(
            "auth.any_scope_denied",
            required_scopes=list(scopes),
            user_id=user.user_id,
            user_scopes=user.scopes,
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient scope. Required one of: {', '.join(scopes)}",
        )

    return _check_any_scope
