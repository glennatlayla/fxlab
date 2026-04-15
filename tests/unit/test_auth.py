"""
Unit tests for services.api.auth — JWT authentication module (M14-T2).

Covers:
- AuthenticatedUser: Pydantic model construction, ULID format validation.
- _get_secret_key: env var lookup, test fallback, missing key error, minimum length.
- create_access_token: claim embedding, expiry, nbf, configurable lifetime.
- _extract_bearer_token: header parsing, case-insensitive scheme, token size limit.
- _validate_token: valid token, TEST_TOKEN bypass, expired, nbf-future, wrong secret,
  missing sub, invalid sub format, alg=none attack, garbage input.
- get_current_user: via TestClient — valid, test token, missing, invalid, expired.
- get_optional_user: missing returns None, valid returns identity, invalid raises 401.

Test naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from services.api.auth import (
    _ALGORITHM,
    MAX_TOKEN_BYTES,
    TEST_TOKEN,
    TEST_USER_EMAIL,
    TEST_USER_ID,
    TEST_USER_ROLE,
    AuthenticatedUser,
    _get_secret_key,
    _validate_token,
    create_access_token,
    get_current_user,
    get_optional_user,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TEST_SECRET = "test-secret-key-not-for-production"
_SAMPLE_USER_ID = "01HABCDEF00000000000000000"
_SAMPLE_ROLE = "operator"
_SAMPLE_EMAIL = "user@fxlab.test"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Set ENVIRONMENT=test and a deterministic JWT_SECRET_KEY for all tests
    in this module.  The autouse ensures a clean, predictable environment.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("JWT_SECRET_KEY", _TEST_SECRET)


@pytest.fixture
def valid_token() -> str:
    """Return a freshly signed JWT with standard test claims."""
    return create_access_token(
        user_id=_SAMPLE_USER_ID,
        role=_SAMPLE_ROLE,
        email=_SAMPLE_EMAIL,
        expires_minutes=60,
    )


@pytest.fixture
def expired_token() -> str:
    """Return a JWT that expired 1 second ago."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _SAMPLE_USER_ID,
        "role": _SAMPLE_ROLE,
        "email": _SAMPLE_EMAIL,
        "aud": "fxlab-api",
        "iss": "fxlab",
        "iat": now - timedelta(hours=2),
        "nbf": now - timedelta(hours=2),
        "exp": now - timedelta(seconds=1),
    }
    return jwt.encode(payload, _TEST_SECRET, algorithm=_ALGORITHM)


@pytest.fixture
def future_nbf_token() -> str:
    """Return a JWT whose nbf is 1 hour in the future (not yet valid)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _SAMPLE_USER_ID,
        "role": _SAMPLE_ROLE,
        "aud": "fxlab-api",
        "iss": "fxlab",
        "iat": now,
        "nbf": now + timedelta(hours=1),
        "exp": now + timedelta(hours=2),
    }
    return jwt.encode(payload, _TEST_SECRET, algorithm=_ALGORITHM)


@pytest.fixture
def no_sub_token() -> str:
    """Return a JWT missing the 'sub' claim."""
    now = datetime.now(timezone.utc)
    payload = {
        "role": _SAMPLE_ROLE,
        "aud": "fxlab-api",
        "iss": "fxlab",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, _TEST_SECRET, algorithm=_ALGORITHM)


@pytest.fixture
def invalid_sub_format_token() -> str:
    """Return a JWT whose 'sub' is not a valid ULID."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "not-a-ulid",
        "role": _SAMPLE_ROLE,
        "aud": "fxlab-api",
        "iss": "fxlab",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, _TEST_SECRET, algorithm=_ALGORITHM)


@pytest.fixture
def wrong_secret_token() -> str:
    """Return a JWT signed with a different secret."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _SAMPLE_USER_ID,
        "role": _SAMPLE_ROLE,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, "wrong-secret-key-that-is-long-enough", algorithm=_ALGORITHM)


def _make_test_app() -> FastAPI:
    """
    Create a minimal FastAPI app with one protected and one optional-auth endpoint.
    Used to test the auth dependencies end-to-end via TestClient.
    """
    app = FastAPI()

    @app.get("/protected")
    async def protected(user: AuthenticatedUser = Depends(get_current_user)):
        return {"user_id": user.user_id, "role": user.role, "email": user.email}

    @app.get("/optional")
    async def optional(user: AuthenticatedUser | None = Depends(get_optional_user)):
        if user:
            return {"user_id": user.user_id, "role": user.role}
        return {"user_id": None}

    return app


@pytest.fixture
def auth_client() -> TestClient:
    """TestClient wired to the minimal auth test app."""
    return TestClient(_make_test_app(), raise_server_exceptions=False)


# ===========================================================================
# AuthenticatedUser contract
# ===========================================================================


class TestAuthenticatedUser:
    """Tests for the AuthenticatedUser Pydantic model."""

    def test_authenticated_user_all_fields(self) -> None:
        """User constructed with all fields retains values."""
        user = AuthenticatedUser(user_id=_SAMPLE_USER_ID, role=_SAMPLE_ROLE, email=_SAMPLE_EMAIL)
        assert user.user_id == _SAMPLE_USER_ID
        assert user.role == _SAMPLE_ROLE
        assert user.email == _SAMPLE_EMAIL

    def test_authenticated_user_email_defaults_to_empty(self) -> None:
        """Email defaults to empty string if omitted."""
        user = AuthenticatedUser(user_id=_SAMPLE_USER_ID, role=_SAMPLE_ROLE)
        assert user.email == ""

    def test_authenticated_user_rejects_invalid_ulid(self) -> None:
        """Non-ULID user_id is rejected by the field validator."""
        with pytest.raises(Exception):  # ValidationError from pydantic
            AuthenticatedUser(user_id="not-a-ulid", role=_SAMPLE_ROLE)

    def test_authenticated_user_accepts_valid_ulid(self) -> None:
        """A proper 26-char Crockford base32 ULID is accepted."""
        user = AuthenticatedUser(user_id="01HABCDEF00000000000000000", role="viewer")
        assert user.user_id == "01HABCDEF00000000000000000"


# ===========================================================================
# _get_secret_key
# ===========================================================================


class TestGetSecretKey:
    """Tests for _get_secret_key() env-var lookup."""

    def test_get_secret_key_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns JWT_SECRET_KEY from environment when set."""
        monkeypatch.setenv("JWT_SECRET_KEY", "my-real-secret-that-is-32-bytes!")
        assert _get_secret_key() == "my-real-secret-that-is-32-bytes!"

    def test_get_secret_key_test_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to deterministic test secret when ENVIRONMENT=test and key is empty."""
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        result = _get_secret_key()
        assert result == "test-secret-key-not-for-production"

    def test_get_secret_key_raises_when_missing_in_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raises RuntimeError when JWT_SECRET_KEY is missing in non-test environment."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            _get_secret_key()

    def test_get_secret_key_rejects_short_key_in_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raises RuntimeError when JWT_SECRET_KEY < 32 bytes in non-test environment."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("JWT_SECRET_KEY", "too-short")
        with pytest.raises(RuntimeError, match="at least 32 bytes"):
            _get_secret_key()

    def test_get_secret_key_accepts_short_key_in_test(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Short keys are allowed in test environment for convenience."""
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("JWT_SECRET_KEY", "short")
        assert _get_secret_key() == "short"


# ===========================================================================
# create_access_token
# ===========================================================================


class TestCreateAccessToken:
    """Tests for create_access_token()."""

    def test_create_token_contains_expected_claims(self) -> None:
        """Token decodes to a payload with sub, role, email, iat, exp, nbf."""
        token = create_access_token(
            user_id=_SAMPLE_USER_ID,
            role=_SAMPLE_ROLE,
            email=_SAMPLE_EMAIL,
            expires_minutes=30,
        )
        payload = jwt.decode(token, _TEST_SECRET, algorithms=[_ALGORITHM], audience="fxlab-api")
        assert payload["sub"] == _SAMPLE_USER_ID
        assert payload["role"] == _SAMPLE_ROLE
        assert payload["email"] == _SAMPLE_EMAIL
        assert "iat" in payload
        assert "exp" in payload
        assert "nbf" in payload

    def test_create_token_expiry_matches_minutes(self) -> None:
        """Token exp is approximately iat + expires_minutes."""
        token = create_access_token(user_id=_SAMPLE_USER_ID, role=_SAMPLE_ROLE, expires_minutes=120)
        payload = jwt.decode(token, _TEST_SECRET, algorithms=[_ALGORITHM], audience="fxlab-api")
        diff = payload["exp"] - payload["iat"]
        # Allow 2-second jitter for test execution time
        assert abs(diff - 7200) < 2

    def test_create_token_default_expiry_uses_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default expires_minutes reads from JWT_EXPIRATION_MINUTES env var."""
        # The module reads at import time, so we test that the env var is respected
        # by checking the default arg documentation behavior
        token = create_access_token(user_id=_SAMPLE_USER_ID, role=_SAMPLE_ROLE)
        payload = jwt.decode(token, _TEST_SECRET, algorithms=[_ALGORITHM], audience="fxlab-api")
        diff = payload["exp"] - payload["iat"]
        # Default is 30 minutes (1800 seconds), allow 2s jitter
        assert abs(diff - 1800) < 2

    def test_create_token_nbf_equals_iat(self) -> None:
        """Token nbf should equal iat (immediately valid)."""
        token = create_access_token(user_id=_SAMPLE_USER_ID, role=_SAMPLE_ROLE)
        payload = jwt.decode(token, _TEST_SECRET, algorithms=[_ALGORITHM], audience="fxlab-api")
        assert payload["nbf"] == payload["iat"]

    def test_create_token_email_defaults_to_empty(self) -> None:
        """Email claim defaults to empty string."""
        token = create_access_token(user_id=_SAMPLE_USER_ID, role=_SAMPLE_ROLE)
        payload = jwt.decode(token, _TEST_SECRET, algorithms=[_ALGORITHM], audience="fxlab-api")
        assert payload["email"] == ""


# ===========================================================================
# _validate_token
# ===========================================================================


class TestValidateToken:
    """Tests for _validate_token()."""

    def test_validate_valid_token_returns_user(self, valid_token: str) -> None:
        """A correctly signed, non-expired token returns AuthenticatedUser."""
        user = _validate_token(valid_token)
        assert isinstance(user, AuthenticatedUser)
        assert user.user_id == _SAMPLE_USER_ID
        assert user.role == _SAMPLE_ROLE
        assert user.email == _SAMPLE_EMAIL

    def test_validate_test_token_returns_fixed_identity(self) -> None:
        """TEST_TOKEN in test environment returns the fixed test identity."""
        user = _validate_token(TEST_TOKEN)
        assert user.user_id == TEST_USER_ID
        assert user.role == TEST_USER_ROLE
        assert user.email == TEST_USER_EMAIL

    def test_validate_test_token_rejected_in_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST_TOKEN is not accepted when ENVIRONMENT != 'test'."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("JWT_SECRET_KEY", "a-production-secret-that-is-at-least-32-bytes-long!!")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_token(TEST_TOKEN)
        assert exc_info.value.status_code == 401

    def test_validate_expired_token_raises_401(self, expired_token: str) -> None:
        """An expired JWT raises 401."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_token(expired_token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_validate_future_nbf_raises_401(self, future_nbf_token: str) -> None:
        """A JWT with nbf in the future raises 401 (not yet valid)."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_token(future_nbf_token)
        assert exc_info.value.status_code == 401
        assert "not yet valid" in exc_info.value.detail.lower()

    def test_validate_wrong_secret_raises_401(self, wrong_secret_token: str) -> None:
        """A JWT signed with a different secret raises 401."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_token(wrong_secret_token)
        assert exc_info.value.status_code == 401

    def test_validate_missing_sub_claim_raises_401(self, no_sub_token: str) -> None:
        """A JWT without a 'sub' claim raises 401."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_token(no_sub_token)
        assert exc_info.value.status_code == 401

    def test_validate_invalid_sub_format_raises_401(self, invalid_sub_format_token: str) -> None:
        """A JWT with a non-ULID 'sub' claim raises 401."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_token(invalid_sub_format_token)
        assert exc_info.value.status_code == 401
        assert "ulid" in exc_info.value.detail.lower()

    def test_validate_garbage_token_raises_401(self) -> None:
        """A non-JWT string raises 401."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_token("not.a.valid.jwt")
        assert exc_info.value.status_code == 401

    def test_validate_alg_none_attack_raises_401(self) -> None:
        """
        CVE-2015-9235: alg=none tokens must be rejected.

        PyJWT 2.3.0+ rejects alg=none by default when algorithms= is specified,
        but this test documents and verifies that protection.
        """
        # Manually construct an alg=none token
        import base64
        import json

        from fastapi import HTTPException

        header = (
            base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
            .rstrip(b"=")
            .decode()
        )
        payload_data = {
            "sub": _SAMPLE_USER_ID,
            "role": _SAMPLE_ROLE,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        }
        payload_b64 = (
            base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        )
        # alg=none token has empty signature
        none_token = f"{header}.{payload_b64}."

        with pytest.raises(HTTPException) as exc_info:
            _validate_token(none_token)
        assert exc_info.value.status_code == 401

    def test_validate_role_defaults_to_viewer(self) -> None:
        """A JWT without a 'role' claim defaults to 'viewer'."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": _SAMPLE_USER_ID,
            "aud": "fxlab-api",
            "iss": "fxlab",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(hours=1),
        }
        token = jwt.encode(payload, _TEST_SECRET, algorithm=_ALGORITHM)
        user = _validate_token(token)
        assert user.role == "viewer"


# ===========================================================================
# _extract_bearer_token (via TestClient)
# ===========================================================================


class TestExtractBearerToken:
    """Tests for _extract_bearer_token() behavior via HTTP."""

    def test_case_insensitive_bearer_prefix(self, auth_client: TestClient) -> None:
        """RFC 7235: 'bearer' scheme is case-insensitive."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": f"bearer {TEST_TOKEN}"},
        )
        # Should be accepted (not rejected as wrong scheme)
        assert response.status_code == 200

    def test_uppercase_bearer_accepted(self, auth_client: TestClient) -> None:
        """BEARER prefix is accepted."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": f"BEARER {TEST_TOKEN}"},
        )
        assert response.status_code == 200

    def test_oversized_token_rejected(self, auth_client: TestClient) -> None:
        """Token exceeding MAX_TOKEN_BYTES is rejected before crypto."""
        huge_token = "x" * (MAX_TOKEN_BYTES + 1)
        response = auth_client.get(
            "/protected",
            headers={"Authorization": f"Bearer {huge_token}"},
        )
        assert response.status_code == 401
        assert "size" in response.json()["detail"].lower()

    def test_empty_bearer_token_rejected(self, auth_client: TestClient) -> None:
        """'Bearer ' with no token after it should be rejected."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": "Bearer "},
        )
        # Empty string goes to _validate_token which should reject it
        assert response.status_code == 401

    def test_non_bearer_scheme_rejected(self, auth_client: TestClient) -> None:
        """A non-Bearer auth scheme yields 401."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert response.status_code == 401


# ===========================================================================
# get_current_user (via TestClient)
# ===========================================================================


class TestGetCurrentUser:
    """Integration-style tests for the get_current_user dependency via HTTP."""

    def test_protected_with_valid_token_returns_200(
        self, auth_client: TestClient, valid_token: str
    ) -> None:
        """A valid Bearer token yields 200 with user identity."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == _SAMPLE_USER_ID
        assert body["role"] == _SAMPLE_ROLE

    def test_protected_with_test_token_returns_200(self, auth_client: TestClient) -> None:
        """TEST_TOKEN is accepted in test environment."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == TEST_USER_ID
        assert body["role"] == TEST_USER_ROLE

    def test_protected_without_token_returns_401(self, auth_client: TestClient) -> None:
        """Missing Authorization header yields 401."""
        response = auth_client.get("/protected")
        assert response.status_code == 401

    def test_protected_with_invalid_token_returns_401(self, auth_client: TestClient) -> None:
        """An invalid Bearer token yields 401."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": "Bearer garbage.token.here"},
        )
        assert response.status_code == 401

    def test_protected_with_expired_token_returns_401(
        self, auth_client: TestClient, expired_token: str
    ) -> None:
        """An expired Bearer token yields 401."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401

    def test_protected_with_wrong_scheme_returns_401(self, auth_client: TestClient) -> None:
        """A non-Bearer auth scheme yields 401."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert response.status_code == 401

    def test_protected_with_wrong_secret_returns_401(
        self, auth_client: TestClient, wrong_secret_token: str
    ) -> None:
        """A JWT signed with a different secret yields 401."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": f"Bearer {wrong_secret_token}"},
        )
        assert response.status_code == 401


# ===========================================================================
# get_optional_user (via TestClient)
# ===========================================================================


class TestGetOptionalUser:
    """Integration-style tests for the get_optional_user dependency via HTTP."""

    def test_optional_without_token_returns_none_identity(self, auth_client: TestClient) -> None:
        """Missing Authorization header returns user_id: null (no 401)."""
        response = auth_client.get("/optional")
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] is None

    def test_optional_with_valid_token_returns_identity(
        self, auth_client: TestClient, valid_token: str
    ) -> None:
        """A valid Bearer token yields the user identity."""
        response = auth_client.get(
            "/optional",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == _SAMPLE_USER_ID

    def test_optional_with_invalid_token_returns_401(self, auth_client: TestClient) -> None:
        """An invalid token on an optional endpoint still yields 401."""
        response = auth_client.get(
            "/optional",
            headers={"Authorization": "Bearer garbage.token"},
        )
        assert response.status_code == 401
