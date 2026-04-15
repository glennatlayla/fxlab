"""
OIDC-compatible authentication routes for FXLab API.

Purpose:
    Provide OpenID Connect discovery, token issuance (password and refresh
    grants), token revocation, and JWKS endpoints. This makes the FXLab API
    compatible with standard OIDC client libraries (oidc-client-ts,
    @auth0/auth0-react, etc.).

Responsibilities:
    - ``GET /.well-known/openid-configuration`` — OIDC discovery document.
    - ``POST /auth/token`` — Issue access + refresh tokens (password grant
      or refresh_token grant).
    - ``POST /auth/revoke`` — Revoke a single refresh token or all tokens
      for a user.
    - ``GET /auth/jwks`` — JSON Web Key Set (501 for HS256; placeholder
      for future RS256 migration).

Does NOT:
    - Implement user registration or account management.
    - Handle external IdP federation (Auth0, Keycloak).
    - Manage password reset flows.

Dependencies:
    - services.api.auth: Token creation, validation, ROLE_SCOPES.
    - services.api.repositories.sql_refresh_token_repository: Refresh token storage.
    - libs.contracts.models: User, RefreshToken ORM models.
    - bcrypt: Password hash verification.

Error conditions:
    - Invalid credentials on password grant → 401.
    - Invalid/expired/revoked refresh token on refresh grant → 401.
    - Missing grant_type → 400.
    - Unknown grant_type → 400.

Example:
    # Password grant
    POST /auth/token
    Content-Type: application/x-www-form-urlencoded
    grant_type=password&username=admin@fxlab.io&password=secret

    # Refresh grant
    POST /auth/token
    Content-Type: application/x-www-form-urlencoded
    grant_type=refresh_token&refresh_token=<opaque_token>
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import structlog
import ulid as _ulid_mod
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from libs.contracts.interfaces.refresh_token_repository import (
    RefreshTokenRepositoryInterface,
)
from libs.contracts.models import User
from services.api.auth import (
    ROLE_SCOPES,
    AuthenticatedUser,
    create_access_token,
    get_current_user,
)
from services.api.db import get_db
from services.api.middleware.correlation import correlation_id_var
from services.api.repositories.sql_refresh_token_repository import (
    SqlRefreshTokenRepository,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# Dependency injection — wire concrete impl at controller layer
# ---------------------------------------------------------------------------


def _get_refresh_token_repo(
    db: Session = Depends(get_db),
) -> RefreshTokenRepositoryInterface:
    """
    Provide a RefreshTokenRepositoryInterface for route handlers.

    Wires the SQL concrete implementation at the controller layer,
    keeping route handler signatures typed to the interface.

    Args:
        db: SQLAlchemy session (injected by FastAPI).

    Returns:
        RefreshTokenRepositoryInterface backed by SQL.
    """
    return SqlRefreshTokenRepository(db=db)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Refresh token lifetime in days (default 7).
_REFRESH_TOKEN_DAYS = int(os.environ.get("REFRESH_TOKEN_DAYS", 7))

#: Access token lifetime in minutes (matches auth.py default).
_ACCESS_TOKEN_MINUTES = int(os.environ.get("JWT_EXPIRATION_MINUTES", 60))


# ---------------------------------------------------------------------------
# Request / response contracts
# ---------------------------------------------------------------------------


class TokenResponse(BaseModel):
    """
    OIDC-compatible token response.

    Attributes:
        access_token: The JWT access token.
        refresh_token: Opaque refresh token string.
        token_type: Always "Bearer".
        expires_in: Access token lifetime in seconds.
        scope: Space-separated scope string.

    Example:
        {"access_token": "eyJ...", "refresh_token": "abc...", "token_type": "Bearer",
         "expires_in": 3600, "scope": "feeds:read operator:read"}
    """

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    scope: str


class RevokeRequest(BaseModel):
    """
    Token revocation request body.

    Attributes:
        token: The refresh token to revoke (optional if revoke_all=True).
        revoke_all: If True, revoke all refresh tokens for the authenticated user.

    Example:
        {"token": "abc123..."} or {"revoke_all": true}
    """

    token: str = ""
    revoke_all: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_context() -> dict[str, str]:
    """Build common structured log fields."""
    return {
        "component": "auth_routes",
        "correlation_id": correlation_id_var.get("no-corr"),
    }


def _hash_token(plaintext: str) -> str:
    """
    SHA-256 hash a plaintext token for server-side storage.

    Args:
        plaintext: The raw refresh token string.

    Returns:
        Hex digest of the SHA-256 hash.

    Example:
        h = _hash_token("abc123")  # "ba7816bf8f01..."
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _generate_refresh_token() -> str:
    """
    Generate a cryptographically secure opaque refresh token.

    Returns:
        URL-safe random string (64 bytes of entropy).

    Example:
        token = _generate_refresh_token()  # "aB3x..."
    """
    return secrets.token_urlsafe(64)


def _verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a bcrypt hash.

    Args:
        plain_password: User-supplied plaintext password.
        hashed_password: Stored bcrypt hash from database.

    Returns:
        True if the password matches.

    Example:
        ok = _verify_password("secret", "$2b$12$...")
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# ---------------------------------------------------------------------------
# OIDC Discovery
# ---------------------------------------------------------------------------


@router.get(
    "/.well-known/openid-configuration",
    summary="OIDC Discovery Document",
    response_class=JSONResponse,
)
async def openid_configuration(request: Request) -> JSONResponse:
    """
    Return an OIDC-compatible discovery document.

    The document follows the OpenID Connect Discovery 1.0 specification
    and provides the information that OIDC client libraries (e.g.
    oidc-client-ts, @auth0/auth0-react) need to auto-configure.

    Args:
        request: The incoming FastAPI request (used to derive the issuer URL).

    Returns:
        JSONResponse with the OIDC discovery fields.

    Example:
        GET /.well-known/openid-configuration
        → {"issuer": "https://api.fxlab.example.com", ...}
    """
    # Derive issuer from the request URL (handles proxy scenarios)
    issuer = str(request.base_url).rstrip("/")

    discovery = {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/auth/authorize",
        "token_endpoint": f"{issuer}/auth/token",
        "revocation_endpoint": f"{issuer}/auth/revoke",
        "jwks_uri": f"{issuer}/auth/jwks",
        "userinfo_endpoint": f"{issuer}/auth/userinfo",
        "response_types_supported": ["code"],
        "grant_types_supported": ["password", "refresh_token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["HS256"],
        "scopes_supported": sorted({s for scopes in ROLE_SCOPES.values() for s in scopes}),
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "claims_supported": ["sub", "role", "email", "scope", "iat", "exp"],
    }

    logger.info("auth.discovery_requested", **_log_context())
    return JSONResponse(content=discovery)


# ---------------------------------------------------------------------------
# Token Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/auth/token",
    summary="Issue access and refresh tokens",
    response_model=TokenResponse,
)
async def token_endpoint(
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """
    Issue access and refresh tokens via password or refresh_token grant.

    Accepts ``application/x-www-form-urlencoded`` or
    ``application/json`` request bodies.

    **Password grant:** Requires ``grant_type=password``, ``username`` (email),
    and ``password``. Returns an access token + refresh token pair.

    **Refresh grant:** Requires ``grant_type=refresh_token`` and
    ``refresh_token``. Returns a new access token + new refresh token
    (token rotation).

    Args:
        request: The incoming FastAPI request.
        db: Database session (injected).

    Returns:
        TokenResponse with access_token, refresh_token, expires_in, scope.

    Raises:
        HTTPException(400): If grant_type is missing or unsupported.
        HTTPException(401): If credentials are invalid or refresh token
            is expired/revoked.

    Example:
        POST /auth/token
        Content-Type: application/x-www-form-urlencoded
        grant_type=password&username=admin@fxlab.io&password=secret
    """
    # Parse form or JSON body
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        form_data = await request.form()
        body: dict[str, Any] = dict(form_data)
    else:
        body = await request.json()

    grant_type = body.get("grant_type", "")

    if grant_type == "password":
        return _handle_password_grant(body, db)
    elif grant_type == "refresh_token":
        return _handle_refresh_grant(body, db)
    else:
        logger.warning(
            "auth.unsupported_grant_type",
            grant_type=grant_type,
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported grant_type: '{grant_type}'. "
            "Supported: 'password', 'refresh_token'.",
        )


def _handle_password_grant(body: dict[str, Any], db: Session) -> TokenResponse:
    """
    Handle the password grant type.

    Authenticates the user via email + password, issues an access token
    and a refresh token. Enforces per-account brute-force lockout via
    LoginAttemptTracker (AUTH-4): after 5 failed attempts within 15 minutes,
    the account is temporarily locked and subsequent attempts receive 429.

    Args:
        body: Parsed request body with username and password fields.
        db: Database session.

    Returns:
        TokenResponse with fresh access and refresh tokens.

    Raises:
        HTTPException(401): If user not found, inactive, or wrong password.
        HTTPException(429): If the account is locked due to repeated failures.
    """
    from services.api.services.login_attempt_tracker import login_tracker

    username = body.get("username", "")
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username and password are required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check brute-force lockout BEFORE hitting the database — prevents
    # credential-stuffing from causing unnecessary DB load.
    if login_tracker.is_locked(username):
        retry = login_tracker.retry_after(username)
        logger.warning(
            "auth.account_locked",
            username=username,
            retry_after=retry,
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in {retry} seconds.",
            headers={"Retry-After": str(retry)},
        )

    # Look up user by email
    user = db.query(User).filter(User.email == username).first()
    if user is None:
        # Record failure for brute-force tracking — even for unknown users,
        # to prevent username enumeration via timing differences.
        login_tracker.record_failure(username)
        logger.warning(
            "auth.user_not_found",
            username=username,
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        login_tracker.record_failure(username)
        logger.warning(
            "auth.user_inactive",
            user_id=user.id,
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password
    if not _verify_password(password, user.hashed_password):
        login_tracker.record_failure(username)
        logger.warning(
            "auth.invalid_password",
            user_id=user.id,
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Clear brute-force lockout on successful authentication
    login_tracker.record_success(username)

    # Issue tokens
    scopes = ROLE_SCOPES.get(user.role, [])
    access_token = create_access_token(
        user_id=user.id,
        role=user.role,
        email=user.email,
        expires_minutes=_ACCESS_TOKEN_MINUTES,
        scopes=scopes,
    )

    refresh_plaintext = _generate_refresh_token()
    refresh_hash = _hash_token(refresh_plaintext)
    token_id = str(_ulid_mod.ULID())

    repo = SqlRefreshTokenRepository(db=db)
    repo.create(
        token_id=token_id,
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=_REFRESH_TOKEN_DAYS),
    )

    logger.info(
        "auth.password_grant_success",
        user_id=user.id,
        **_log_context(),
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_plaintext,
        token_type="Bearer",
        expires_in=_ACCESS_TOKEN_MINUTES * 60,
        scope=" ".join(scopes),
    )


def _handle_refresh_grant(body: dict[str, Any], db: Session) -> TokenResponse:
    """
    Handle the refresh_token grant type.

    Validates the refresh token, rotates it (revoke old, issue new),
    and returns a new access + refresh token pair.

    Args:
        body: Parsed request body with refresh_token field.
        db: Database session.

    Returns:
        TokenResponse with rotated access and refresh tokens.

    Raises:
        HTTPException(401): If refresh token is missing, invalid,
            expired, or revoked.
    """
    refresh_token = body.get("refresh_token", "")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh_token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    repo = SqlRefreshTokenRepository(db=db)
    token_hash = _hash_token(refresh_token)
    record = repo.find_by_hash(token_hash)

    if record is None:
        logger.warning("auth.refresh_token_not_found", **_log_context())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if revoked
    if record["revoked_at"] is not None:
        logger.warning(
            "auth.refresh_token_revoked",
            token_id=record["id"],
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if expired
    expires_at = record["expires_at"]
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        logger.warning(
            "auth.refresh_token_expired",
            token_id=record["id"],
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Look up user
    user = db.query(User).filter(User.id == record["user_id"]).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or disabled.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Token rotation: revoke old, issue new
    repo.revoke(record["id"])

    scopes = ROLE_SCOPES.get(user.role, [])
    access_token = create_access_token(
        user_id=user.id,
        role=user.role,
        email=user.email,
        expires_minutes=_ACCESS_TOKEN_MINUTES,
        scopes=scopes,
    )

    new_refresh_plaintext = _generate_refresh_token()
    new_refresh_hash = _hash_token(new_refresh_plaintext)
    new_token_id = str(_ulid_mod.ULID())

    repo.create(
        token_id=new_token_id,
        user_id=user.id,
        token_hash=new_refresh_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=_REFRESH_TOKEN_DAYS),
    )

    logger.info(
        "auth.refresh_grant_success",
        user_id=user.id,
        old_token_id=record["id"],
        **_log_context(),
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_plaintext,
        token_type="Bearer",
        expires_in=_ACCESS_TOKEN_MINUTES * 60,
        scope=" ".join(scopes),
    )


# ---------------------------------------------------------------------------
# Revocation Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/auth/revoke",
    summary="Revoke refresh tokens",
    status_code=200,
)
async def revoke_endpoint(
    body: RevokeRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Revoke a single refresh token (logout) or all tokens for the user
    (force logout / security incident).

    Args:
        body: RevokeRequest with token or revoke_all flag.
        user: Authenticated user (from JWT).
        db: Database session (injected).

    Returns:
        Dict with status and count of revoked tokens.

    Example:
        POST /auth/revoke
        Authorization: Bearer <access_token>
        {"token": "<refresh_token>"}
        → {"status": "revoked", "count": 1}

        POST /auth/revoke
        Authorization: Bearer <access_token>
        {"revoke_all": true}
        → {"status": "revoked", "count": 5}
    """
    repo = SqlRefreshTokenRepository(db=db)

    if body.revoke_all:
        count = repo.revoke_all_for_user(user.user_id)
        logger.info(
            "auth.revoke_all",
            user_id=user.user_id,
            count=count,
            **_log_context(),
        )
        return {"status": "revoked", "count": count}

    if not body.token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide 'token' or set 'revoke_all' to true.",
        )

    token_hash = _hash_token(body.token)
    record = repo.find_by_hash(token_hash)

    if record is None:
        # RFC 7009 §2.2: invalid tokens are acknowledged without error
        logger.info("auth.revoke_unknown_token", **_log_context())
        return {"status": "revoked", "count": 0}

    # Only allow revoking own tokens
    if record["user_id"] != user.user_id:
        logger.warning(
            "auth.revoke_forbidden",
            token_owner=record["user_id"],
            requester=user.user_id,
            **_log_context(),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot revoke tokens belonging to another user.",
        )

    if record["revoked_at"] is not None:
        return {"status": "already_revoked", "count": 0}

    repo.revoke(record["id"])
    logger.info(
        "auth.revoke_single",
        token_id=record["id"],
        user_id=user.user_id,
        **_log_context(),
    )
    return {"status": "revoked", "count": 1}


# ---------------------------------------------------------------------------
# JWKS Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/auth/jwks",
    summary="JSON Web Key Set",
)
async def jwks_endpoint() -> JSONResponse:
    """
    Return the JSON Web Key Set for token verification.

    Currently returns 501 because FXLab uses HS256 (symmetric key) which
    cannot be exposed publicly. When RS256 migration occurs, this endpoint
    will expose the public key.

    Returns:
        JSONResponse with 501 status and migration note.

    Example:
        GET /auth/jwks → 501 {"detail": "JWKS not available for HS256..."}
    """
    logger.info("auth.jwks_requested", **_log_context())
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "detail": "JWKS not available for HS256 symmetric signing. "
            "Will be implemented when RS256 asymmetric signing is adopted.",
            "keys": [],
        },
    )
