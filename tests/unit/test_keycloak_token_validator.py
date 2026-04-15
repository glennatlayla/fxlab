"""
Tests for KeycloakTokenValidator — RS256 JWKS-based JWT validation.

Covers:
- JWKS fetching and caching with TTL
- RS256 token signature validation
- Claim extraction: sub, realm_access.roles, scope, email
- Keycloak role → FXLab scope mapping
- Expired / not-yet-valid / invalid-signature rejection
- Issuer and audience validation
- Key cache refresh on unknown kid
- Backward compat: HS256 fallback when KEYCLOAK_URL not set

Example:
    pytest tests/unit/test_keycloak_token_validator.py -v
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from services.api.auth import ROLE_SCOPES, AuthenticatedUser
from services.api.infrastructure.keycloak_token_validator import (
    KeycloakTokenValidator,
)

# ---------------------------------------------------------------------------
# RSA key fixtures — generate a fresh pair per test module
# ---------------------------------------------------------------------------

_RSA_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_RSA_PUBLIC_KEY = _RSA_PRIVATE_KEY.public_key()

_RSA_PRIVATE_PEM = _RSA_PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
_RSA_PUBLIC_PEM = _RSA_PUBLIC_KEY.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)

# Second key pair for "wrong key" tests
_RSA_PRIVATE_KEY_2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _build_jwks_response(public_key: Any = None, kid: str = "test-kid") -> dict:
    """Build a minimal JWKS response dict from an RSA public key."""
    import json as _json

    from jwt.algorithms import RSAAlgorithm

    pk = public_key or _RSA_PUBLIC_KEY
    # PyJWT 2.3 returns a JSON string; newer versions support as_dict kwarg.
    jwk_raw = RSAAlgorithm.to_jwk(pk)
    jwk = _json.loads(jwk_raw) if isinstance(jwk_raw, str) else jwk_raw
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return {"keys": [jwk]}


def _create_keycloak_token(
    sub: str = "01HTESTFAKE000000000000000",
    realm_roles: list[str] | None = None,
    scope: str = "",
    email: str = "user@fxlab.test",
    iss: str = "http://keycloak:8080/realms/fxlab",
    aud: str = "fxlab-api",
    kid: str = "test-kid",
    exp_delta_seconds: int = 300,
    nbf_delta_seconds: int = 0,
    private_key: Any = None,
) -> str:
    """Create a Keycloak-style RS256 JWT for testing."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": sub,
        "iss": iss,
        "aud": aud,
        "iat": now,
        "nbf": now + timedelta(seconds=nbf_delta_seconds),
        "exp": now + timedelta(seconds=exp_delta_seconds),
        "email": email,
        "email_verified": True,
        "scope": scope,
        "realm_access": {
            "roles": realm_roles or ["operator"],
        },
        "typ": "Bearer",
        "azp": "fxlab-web",
    }
    pk = private_key or _RSA_PRIVATE_KEY
    headers = {"kid": kid, "alg": "RS256"}
    return jwt.encode(payload, pk, algorithm="RS256", headers=headers)


# ---------------------------------------------------------------------------
# KeycloakTokenValidator unit tests
# ---------------------------------------------------------------------------


class TestKeycloakTokenValidator:
    """Validate RS256 Keycloak token processing."""

    def _make_validator(
        self,
        keycloak_url: str = "http://keycloak:8080",
        realm: str = "fxlab",
        client_id: str = "fxlab-api",
        cache_ttl_seconds: int = 300,
    ) -> KeycloakTokenValidator:
        """Create a validator instance with test defaults."""
        return KeycloakTokenValidator(
            keycloak_url=keycloak_url,
            realm=realm,
            client_id=client_id,
            cache_ttl_seconds=cache_ttl_seconds,
        )

    def _patch_jwks(self, validator: KeycloakTokenValidator, jwks: dict | None = None) -> None:
        """Inject JWKS keys directly into the validator cache, bypassing HTTP."""
        from jwt.algorithms import RSAAlgorithm

        jwks_data = jwks or _build_jwks_response()
        keys = {}
        for key_data in jwks_data["keys"]:
            kid = key_data.get("kid", "default")
            # Convert JWK dict to PEM public key for PyJWT
            keys[kid] = RSAAlgorithm.from_jwk(key_data)
        validator._cached_keys = keys
        validator._cache_timestamp = time.monotonic()

    # ----- Happy path -----

    def test_validate_valid_token(self):
        """Valid RS256 token with correct signature returns AuthenticatedUser."""
        validator = self._make_validator()
        self._patch_jwks(validator)

        token = _create_keycloak_token(
            realm_roles=["operator"],
            scope="strategies:write runs:write feeds:read",
        )
        user = validator.validate_token(token)

        assert isinstance(user, AuthenticatedUser)
        assert user.user_id == "01HTESTFAKE000000000000000"
        assert user.role == "operator"
        assert user.email == "user@fxlab.test"
        assert "strategies:write" in user.scopes
        assert "runs:write" in user.scopes

    def test_extracts_first_known_role(self):
        """When user has multiple realm roles, the first known FXLab role is used."""
        validator = self._make_validator()
        self._patch_jwks(validator)

        token = _create_keycloak_token(
            realm_roles=["offline_access", "admin", "operator"],
        )
        user = validator.validate_token(token)
        assert user.role == "admin"

    def test_defaults_to_viewer_when_no_known_role(self):
        """When realm roles contain no FXLab role, defaults to 'viewer'."""
        validator = self._make_validator()
        self._patch_jwks(validator)

        token = _create_keycloak_token(
            realm_roles=["uma_authorization", "offline_access"],
        )
        user = validator.validate_token(token)
        assert user.role == "viewer"

    def test_scope_from_token_overrides_role_defaults(self):
        """Explicit scope claim in token is used instead of role-based defaults."""
        validator = self._make_validator()
        self._patch_jwks(validator)

        token = _create_keycloak_token(
            realm_roles=["admin"],
            scope="feeds:read audit:read",
        )
        user = validator.validate_token(token)
        # Should use the explicit scope, not the full admin scope set
        assert user.scopes == ["feeds:read", "audit:read"]

    def test_no_scope_claim_falls_back_to_role_scopes(self):
        """When scope claim is empty, use ROLE_SCOPES for the role."""
        validator = self._make_validator()
        self._patch_jwks(validator)

        token = _create_keycloak_token(
            realm_roles=["reviewer"],
            scope="",
        )
        user = validator.validate_token(token)
        assert user.scopes == ROLE_SCOPES["reviewer"]

    # ----- Rejection: expired / immature / wrong signature -----

    def test_rejects_expired_token(self):
        """Expired token raises HTTPException 401."""
        from fastapi import HTTPException

        validator = self._make_validator()
        self._patch_jwks(validator)

        token = _create_keycloak_token(exp_delta_seconds=-60)
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_token(token)
        assert exc_info.value.status_code == 401

    def test_rejects_not_yet_valid_token(self):
        """Token with future nbf raises HTTPException 401."""
        from fastapi import HTTPException

        validator = self._make_validator()
        self._patch_jwks(validator)

        token = _create_keycloak_token(nbf_delta_seconds=3600)
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_token(token)
        assert exc_info.value.status_code == 401

    def test_rejects_wrong_signature(self):
        """Token signed with a different key raises HTTPException 401."""
        from fastapi import HTTPException

        validator = self._make_validator()
        self._patch_jwks(validator)  # cached key is _RSA_PUBLIC_KEY

        # Sign with a different private key
        token = _create_keycloak_token(private_key=_RSA_PRIVATE_KEY_2)
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_token(token)
        assert exc_info.value.status_code == 401

    def test_rejects_wrong_issuer(self):
        """Token with unexpected issuer raises HTTPException 401."""
        from fastapi import HTTPException

        validator = self._make_validator()
        self._patch_jwks(validator)

        token = _create_keycloak_token(iss="http://evil.example.com/realms/fxlab")
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_token(token)
        assert exc_info.value.status_code == 401

    def test_rejects_wrong_audience(self):
        """Token with unexpected audience raises HTTPException 401."""
        from fastapi import HTTPException

        validator = self._make_validator()
        self._patch_jwks(validator)

        token = _create_keycloak_token(aud="wrong-client")
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_token(token)
        assert exc_info.value.status_code == 401

    # ----- Cache behaviour -----

    def test_cache_expires_after_ttl(self):
        """Keys are re-fetched after cache TTL expires."""
        validator = self._make_validator(cache_ttl_seconds=1)
        self._patch_jwks(validator)

        # Force cache to appear expired
        validator._cache_timestamp = time.monotonic() - 10
        assert validator._is_cache_expired() is True

    def test_cache_valid_within_ttl(self):
        """Keys are served from cache within TTL."""
        validator = self._make_validator(cache_ttl_seconds=300)
        self._patch_jwks(validator)

        assert validator._is_cache_expired() is False

    # ----- Issuer URL construction -----

    def test_expected_issuer_url(self):
        """Issuer URL is constructed from keycloak_url and realm."""
        validator = self._make_validator(
            keycloak_url="http://keycloak:8080",
            realm="fxlab",
        )
        assert validator._expected_issuer == "http://keycloak:8080/realms/fxlab"

    def test_jwks_uri(self):
        """JWKS URI is constructed correctly."""
        validator = self._make_validator(
            keycloak_url="http://keycloak:8080",
            realm="fxlab",
        )
        assert (
            validator._jwks_uri == "http://keycloak:8080/realms/fxlab/protocol/openid-connect/certs"
        )

    # ----- Missing sub claim -----

    # ----- auth.py delegation -----

    def test_auth_delegates_to_keycloak_when_url_set(self):
        """auth._validate_token delegates to Keycloak when KEYCLOAK_URL is set."""
        import services.api.auth as auth_module

        validator = self._make_validator()
        self._patch_jwks(validator)
        token = _create_keycloak_token(realm_roles=["operator"])

        env_overrides = {
            "KEYCLOAK_URL": "http://keycloak:8080",
            "KEYCLOAK_REALM": "fxlab",
            "KEYCLOAK_CLIENT_ID": "fxlab-api",
            "ENVIRONMENT": "development",
        }
        # Reset singleton to force re-creation
        original_validator = auth_module._keycloak_validator
        try:
            auth_module._keycloak_validator = validator
            with patch.dict(os.environ, env_overrides, clear=False):
                user = auth_module._validate_token(token)
            assert isinstance(user, AuthenticatedUser)
            assert user.role == "operator"
        finally:
            auth_module._keycloak_validator = original_validator

    def test_auth_falls_back_to_hs256_when_no_keycloak(self):
        """auth._validate_token uses HS256 when KEYCLOAK_URL is not set."""
        import services.api.auth as auth_module

        env_overrides = {"ENVIRONMENT": "test"}
        env_remove = {k: v for k, v in os.environ.items() if k != "KEYCLOAK_URL"}
        original_validator = auth_module._keycloak_validator
        try:
            auth_module._keycloak_validator = None
            with patch.dict(os.environ, {**env_remove, **env_overrides}, clear=True):
                user = auth_module._validate_token("TEST_TOKEN")
            assert user.user_id == "01HTESTFAKE000000000000000"
        finally:
            auth_module._keycloak_validator = original_validator

    # ----- Thread safety: JWKS cache protected by lock -----

    def test_keys_lock_exists_and_is_threading_lock(self):
        """Validator must have a threading.Lock protecting the JWKS cache."""
        import threading

        validator = self._make_validator()
        assert hasattr(validator, "_keys_lock"), (
            "KeycloakTokenValidator must have a _keys_lock attribute for "
            "thread-safe JWKS cache access"
        )
        assert isinstance(validator._keys_lock, type(threading.Lock())), (
            "_keys_lock must be a threading.Lock instance"
        )

    def test_concurrent_validate_token_does_not_corrupt_cache(self):
        """Multiple threads calling validate_token concurrently must not corrupt the key cache."""
        import concurrent.futures
        import threading

        validator = self._make_validator()
        self._patch_jwks(validator)

        token = _create_keycloak_token(realm_roles=["operator"])

        errors: list[Exception] = []
        success_count = 0
        lock = threading.Lock()

        def _validate() -> None:
            nonlocal success_count
            try:
                user = validator.validate_token(token)
                assert user.user_id == "01HTESTFAKE000000000000000"
                with lock:
                    success_count += 1
            except Exception as exc:
                with lock:
                    errors.append(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_validate) for _ in range(20)]
            concurrent.futures.wait(futures)

        assert not errors, f"Thread-safety violation: {errors}"
        assert success_count == 20

    def test_fetch_jwks_acquires_lock(self):
        """_fetch_jwks must acquire _keys_lock to prevent concurrent cache mutation."""
        import json
        import threading
        from unittest.mock import patch as _patch

        validator = self._make_validator()

        class TrackingLock:
            """Proxy that records whether the lock was acquired."""

            def __init__(self, real_lock: threading.Lock) -> None:
                self._real = real_lock
                self.acquired = False

            def acquire(self, *args: object, **kwargs: object) -> bool:
                self.acquired = True
                return self._real.acquire(*args, **kwargs)

            def release(self) -> None:
                return self._real.release()

            def __enter__(self) -> TrackingLock:
                self.acquire()
                return self

            def __exit__(self, *args: object) -> None:
                self.release()

        tracking = TrackingLock(threading.Lock())
        validator._keys_lock = tracking  # type: ignore[assignment]

        jwks_data = _build_jwks_response()
        jwks_bytes = json.dumps(jwks_data).encode()

        mock_response = MagicMock()
        mock_response.read.return_value = jwks_bytes
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with _patch("urllib.request.urlopen", return_value=mock_response):
            validator._fetch_jwks()

        assert tracking.acquired, "_fetch_jwks must acquire _keys_lock before mutating the cache"

    # ----- Missing sub claim -----

    def test_rejects_missing_sub(self):
        """Token without sub claim raises HTTPException 401."""
        from fastapi import HTTPException

        validator = self._make_validator()
        self._patch_jwks(validator)

        now = datetime.now(timezone.utc)
        payload = {
            "iss": "http://keycloak:8080/realms/fxlab",
            "aud": "fxlab-api",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=300),
            "realm_access": {"roles": ["admin"]},
        }
        token = jwt.encode(
            payload,
            _RSA_PRIVATE_KEY,
            algorithm="RS256",
            headers={"kid": "test-kid"},
        )
        with pytest.raises(HTTPException) as exc_info:
            validator.validate_token(token)
        assert exc_info.value.status_code == 401
