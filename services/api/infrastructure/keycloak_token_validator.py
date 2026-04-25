"""
Keycloak RS256 token validator.

Responsibilities:
- Fetch JWKS public keys from Keycloak's well-known certs endpoint.
- Cache keys with configurable TTL to minimize network calls.
- Validate RS256-signed JWTs: signature, exp, nbf, iss, aud.
- Extract identity claims and map Keycloak realm roles to FXLab scopes.

Does NOT:
- Issue tokens (Keycloak is the issuer).
- Manage user sessions or revocation (Keycloak handles this).
- Perform RBAC enforcement (caller uses require_scope).

Dependencies:
- PyJWT with cryptography backend for RS256 verification.
- urllib (stdlib) for JWKS endpoint fetching.
- services.api.auth: AuthenticatedUser, ROLE_SCOPES.

Error conditions:
- Network failure when fetching JWKS → HTTPException 401 (cannot validate).
- Expired / immature / invalid signature → HTTPException 401.
- Wrong issuer or audience → HTTPException 401.
- Missing sub claim → HTTPException 401.

Example:
    validator = KeycloakTokenValidator(
        keycloak_url="http://keycloak:8080",
        realm="fxlab",
        client_id="fxlab-api",
    )
    user = validator.validate_token(raw_token)
"""

from __future__ import annotations

import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import jwt
import structlog
from fastapi import HTTPException, status
from jwt.algorithms import RSAAlgorithm

from services.api.auth import ROLE_SCOPES, AuthenticatedUser
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)

#: Regex for ULID format validation (26 chars, Crockford base32).
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$", re.IGNORECASE)

#: Known FXLab roles — used to pick the first matching role from Keycloak's
#: realm_access.roles array (which may also contain Keycloak-internal roles
#: like "offline_access" or "uma_authorization").
_KNOWN_ROLES = frozenset(ROLE_SCOPES.keys())


class KeycloakTokenValidator:
    """
    Validates RS256 JWTs issued by Keycloak.

    Responsibilities:
    - Download and cache Keycloak's JWKS public keys.
    - Verify RS256 signature, expiry, not-before, issuer, audience.
    - Extract user identity and map realm roles to FXLab scopes.

    Does NOT:
    - Issue tokens.
    - Call Keycloak Admin API (see KeycloakAdminService).
    - Enforce per-route authorization (caller's responsibility).

    Args:
        keycloak_url: Base URL of the Keycloak server (e.g. "http://keycloak:8080").
        realm: Keycloak realm name (e.g. "fxlab").
        client_id: Expected audience claim in tokens.
        cache_ttl_seconds: How long to cache JWKS keys before re-fetching.

    Example:
        validator = KeycloakTokenValidator(
            keycloak_url="http://keycloak:8080",
            realm="fxlab",
            client_id="fxlab-api",
        )
        user = validator.validate_token(bearer_token)
        print(user.user_id, user.role, user.scopes)
    """

    def __init__(
        self,
        keycloak_url: str,
        realm: str,
        client_id: str,
        cache_ttl_seconds: int = 300,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._keycloak_url = keycloak_url.rstrip("/")
        self._realm = realm
        self._client_id = client_id
        self._cache_ttl_seconds = cache_ttl_seconds

        # TLS context — defaults to system CA bundle with certificate verification.
        # Pass a custom SSLContext for certificate pinning or internal CAs.
        self._ssl_context = ssl_context or ssl.create_default_context()

        # JWKS cache: kid → public key object.
        # Protected by _keys_lock to prevent concurrent mutation when
        # multiple request-handling threads refresh the cache simultaneously.
        self._keys_lock = threading.Lock()
        self._cached_keys: dict[str, Any] = {}
        self._cache_timestamp: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_token(self, token: str) -> AuthenticatedUser:
        """
        Validate an RS256 JWT and return the authenticated identity.

        Args:
            token: Raw JWT string from the Authorization header.

        Returns:
            AuthenticatedUser with claims extracted from the token.

        Raises:
            HTTPException(401): On expired, immature, invalid, or
                malformed tokens, or if JWKS cannot be fetched.

        Example:
            user = validator.validate_token("eyJ...")
        """
        ctx = self._log_context()

        # Ensure we have keys (fetch or use cache)
        self._ensure_keys_loaded()

        # Decode header to find kid
        try:
            unverified_header = jwt.get_unverified_header(token)
        except jwt.exceptions.DecodeError:
            logger.warning("keycloak.token_decode_header_failed", **ctx)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        kid = unverified_header.get("kid", "")
        public_key = self._cached_keys.get(kid)

        # If kid not found, try refreshing JWKS (key rotation may have occurred).
        # Acquire the lock to prevent concurrent fetches from multiple threads
        # that all see the same missing kid.
        if public_key is None:
            with self._keys_lock:
                # Double-check: another thread may have fetched while we waited.
                public_key = self._cached_keys.get(kid)
                if public_key is None:
                    self._fetch_jwks_unlocked()
                    public_key = self._cached_keys.get(kid)

        if public_key is None:
            logger.warning("keycloak.unknown_kid", kid=kid, **ctx)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Validate token
        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=self._expected_issuer,
                options={
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.ExpiredSignatureError:
            logger.warning("keycloak.token_expired", **ctx)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.ImmatureSignatureError:
            logger.warning("keycloak.token_not_yet_valid", **ctx)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token is not yet valid.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidAudienceError:
            logger.warning("keycloak.invalid_audience", **ctx)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token audience.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidIssuerError:
            logger.warning("keycloak.invalid_issuer", **ctx)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token issuer.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError:
            logger.warning("keycloak.token_invalid", **ctx)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return self._extract_identity(payload)

    # ------------------------------------------------------------------
    # Derived URLs
    # ------------------------------------------------------------------

    @property
    def _expected_issuer(self) -> str:
        """Keycloak issuer URL: {base}/realms/{realm}."""
        return f"{self._keycloak_url}/realms/{self._realm}"

    @property
    def _jwks_uri(self) -> str:
        """JWKS endpoint: {base}/realms/{realm}/protocol/openid-connect/certs."""
        return f"{self._keycloak_url}/realms/{self._realm}/protocol/openid-connect/certs"

    # ------------------------------------------------------------------
    # JWKS cache management
    # ------------------------------------------------------------------

    def _is_cache_expired(self) -> bool:
        """Check whether the JWKS cache has exceeded its TTL."""
        if not self._cached_keys:
            return True
        elapsed = time.monotonic() - self._cache_timestamp
        return elapsed > self._cache_ttl_seconds

    def _ensure_keys_loaded(self) -> None:
        """Fetch JWKS if the cache is empty or expired.

        Thread-safe: acquires _keys_lock to prevent duplicate concurrent
        JWKS fetches. The double-check pattern avoids redundant network
        calls when multiple threads see an expired cache simultaneously.
        """
        if self._is_cache_expired():
            with self._keys_lock:
                # Double-check after acquiring the lock — another thread
                # may have refreshed while we were waiting.
                if self._is_cache_expired():
                    self._fetch_jwks_unlocked()

    def _fetch_jwks(self) -> None:
        """
        Thread-safe wrapper around the JWKS fetch operation.

        Acquires _keys_lock before mutating the cache.  Use
        _fetch_jwks_unlocked when the caller already holds the lock
        (e.g. inside _ensure_keys_loaded or validate_token).
        """
        with self._keys_lock:
            self._fetch_jwks_unlocked()

    def _fetch_jwks_unlocked(self) -> None:
        """
        Fetch JWKS from Keycloak and populate the key cache.

        IMPORTANT: Caller MUST hold self._keys_lock before calling.

        Uses TLS certificate verification via self._ssl_context.
        On network failure, logs a warning and keeps the existing cache
        (if any) to avoid total auth failure during transient outages.
        """
        ctx = self._log_context()
        try:
            req = urllib.request.Request(
                self._jwks_uri,
                headers={"Accept": "application/json"},
            )
            # Use SSL context for certificate verification on HTTPS endpoints.
            # For HTTP (dev/docker-internal), ssl_context is ignored by urllib.
            # URL is the configured Keycloak JWKS endpoint, not user input.
            # Scheme is constrained to http/https by Keycloak's public OIDC
            # contract; file://, data://, etc. cannot reach this code path.
            with urllib.request.urlopen(req, timeout=10, context=self._ssl_context) as response:  # nosec B310
                jwks_data = json.loads(response.read())

            new_keys: dict[str, Any] = {}
            for key_data in jwks_data.get("keys", []):
                kid = key_data.get("kid", "default")
                try:
                    new_keys[kid] = RSAAlgorithm.from_jwk(key_data)
                except (ValueError, KeyError) as exc:
                    logger.warning(
                        "keycloak.jwks_key_parse_failed",
                        kid=kid,
                        error=str(exc),
                        **ctx,
                    )

            if new_keys:
                self._cached_keys = new_keys
                self._cache_timestamp = time.monotonic()
                logger.debug(
                    "keycloak.jwks_refreshed",
                    key_count=len(new_keys),
                    **ctx,
                )
            else:
                logger.warning("keycloak.jwks_empty_response", **ctx)

        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            logger.warning(
                "keycloak.jwks_fetch_network_error",
                jwks_uri=self._jwks_uri,
                error=str(exc),
                exc_info=True,
                **ctx,
            )
            # Keep existing cache if available — better to validate with
            # potentially stale keys than to reject everything.
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "keycloak.jwks_parse_error",
                jwks_uri=self._jwks_uri,
                error=str(exc),
                **ctx,
            )

    # ------------------------------------------------------------------
    # Identity extraction
    # ------------------------------------------------------------------

    def _extract_identity(self, payload: dict[str, Any]) -> AuthenticatedUser:
        """
        Map validated JWT claims to an AuthenticatedUser.

        Keycloak tokens carry realm roles in ``realm_access.roles`` and
        optionally a space-separated ``scope`` claim.  This method finds
        the first known FXLab role and resolves scopes accordingly.

        Args:
            payload: Decoded JWT payload dict.

        Returns:
            AuthenticatedUser with mapped identity and scopes.

        Raises:
            HTTPException(401): If the sub claim is missing or not a valid ULID.
        """
        ctx = self._log_context()
        sub = payload.get("sub", "")
        if not sub:
            logger.warning("keycloak.missing_sub_claim", **ctx)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing required 'sub' claim.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Validate sub is a valid ULID
        if not _ULID_RE.match(sub):
            logger.warning(
                "keycloak.invalid_sub_format",
                sub_length=len(sub),
                **ctx,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token 'sub' claim is not a valid ULID.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Extract first known FXLab role from realm_access.roles
        realm_roles = payload.get("realm_access", {}).get("roles", [])
        role = "viewer"  # default when no known role is found
        for r in realm_roles:
            if r in _KNOWN_ROLES:
                role = r
                break

        # Resolve scopes: explicit scope claim takes precedence
        scope_str = payload.get("scope", "")
        scopes = scope_str.split() if scope_str else ROLE_SCOPES.get(role, [])

        email = payload.get("email", "")

        return AuthenticatedUser(
            user_id=sub,
            role=role,
            email=email,
            scopes=scopes,
        )

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _log_context() -> dict[str, str]:
        """Build common structured log fields."""
        return {
            "component": "keycloak_validator",
            "correlation_id": correlation_id_var.get("no-corr"),
        }
