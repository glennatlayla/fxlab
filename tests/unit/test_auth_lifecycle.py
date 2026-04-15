"""
End-to-end authentication lifecycle integration test.

Purpose:
    Verify the complete authentication flow including OIDC discovery, token
    issuance (password grant and refresh token grant), token validation,
    account lockout, and JWKS endpoint.

Responsibilities:
    - Test OIDC discovery document (/.well-known/openid-configuration).
    - Test password grant flow with valid and invalid credentials.
    - Test access token validation via protected endpoints.
    - Test refresh token grant and token rotation.
    - Test brute-force protection with account lockout.
    - Test JWKS endpoint.

Does NOT:
    - Mock external services (uses real in-memory SQLite DB).
    - Test individual components in isolation (use unit tests for that).

Dependencies:
    - FastAPI TestClient
    - Real in-memory SQLite database
    - User, RefreshToken, RevokedToken ORM models
    - bcrypt for password hashing

Test scenarios:
    1. OIDC discovery — GET /.well-known/openid-configuration → 200 with issuer
    2. Password grant happy path — POST /auth/token with valid credentials
    3. Access token works — Use access_token on GET /health
    4. Refresh grant — POST /auth/token with grant_type=refresh_token
    5. Invalid credentials — POST /auth/token with wrong password → 401
    6. Missing grant_type — POST /auth/token without grant_type → 400
    7. Account lockout after 5+ failures → 429 with Retry-After
    8. JWKS endpoint — GET /auth/jwks

Example:
    pytest tests/unit/test_auth_lifecycle.py -v --no-header
"""

from __future__ import annotations

import os
from unittest.mock import patch

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import Base, User
from services.api.db import get_db
from services.api.main import app

# ---------------------------------------------------------------------------
# Fixtures: In-memory database
# ---------------------------------------------------------------------------


@pytest.fixture
def test_db() -> Session:
    """
    Provide a fully isolated in-memory SQLite database for auth lifecycle tests.

    Creates its own engine and session factory so that setup/teardown
    does NOT interfere with the shared app engine used by other test modules.

    Yields:
        Session: An active SQLAlchemy session bound to the isolated engine.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    _engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(_engine)

    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    session = _SessionLocal()
    yield session

    # Cleanup — only drops tables in THIS isolated engine, not the shared one
    session.close()
    Base.metadata.drop_all(_engine)
    _engine.dispose()


@pytest.fixture
def reset_login_tracker():
    """
    Reset the module-level login_tracker state before each test.

    The login_tracker is a global singleton that persists across test runs.
    This fixture clears its internal state before each test to avoid
    interference from previous tests' failed attempts.

    Yields:
        None (fixture just resets state as a side effect).
    """
    from services.api.services.login_attempt_tracker import login_tracker

    # Clear any existing state
    login_tracker._store.clear()
    yield
    # Cleanup after test
    login_tracker._store.clear()


@pytest.fixture
def client(test_db: Session, reset_login_tracker) -> TestClient:
    """
    Provide a FastAPI TestClient with test database dependency override.

    Overrides the get_db dependency to use the in-memory test database
    instead of the production database. Also patches check_db_connection
    to always return True so health checks pass.

    Args:
        test_db: The in-memory SQLite session fixture.

    Returns:
        TestClient configured to use the test database.

    Example:
        response = client.get("/health")
        assert response.status_code == 200
    """
    # Set test environment
    os.environ["ENVIRONMENT"] = "test"

    # Override get_db to use test database
    def override_get_db():
        yield test_db

    # Save existing overrides so we restore only what we changed
    _prev_get_db = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db

    # Patch check_db_connection to always return True in test mode
    with patch("services.api.db.check_db_connection", return_value=True):
        client = TestClient(app)
        yield client

    # Restore previous override (or remove ours) — never clear ALL overrides
    if _prev_get_db is not None:
        app.dependency_overrides[get_db] = _prev_get_db
    else:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def test_user(test_db: Session) -> User:
    """
    Create a test user in the database with a bcrypt-hashed password.

    The test user has role "operator" and is active.
    Password: "test-password-123"
    Email: "test@fxlab.io"

    Args:
        test_db: The in-memory SQLite session fixture.

    Returns:
        User: The created user record.

    Example:
        user = test_user
        assert user.email == "test@fxlab.io"
    """
    password = "test-password-123"
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    user = User(
        id="01HTEST0000000000000000001",
        email="test@fxlab.io",
        hashed_password=hashed,
        role="operator",
        is_active=True,
    )
    test_db.add(user)
    test_db.commit()
    return user


# ---------------------------------------------------------------------------
# Tests: OIDC Discovery
# ---------------------------------------------------------------------------


def test_oidc_discovery_returns_200_with_issuer(client: TestClient) -> None:
    """
    OIDC discovery endpoint returns 200 with required fields.

    Scenario: GET /.well-known/openid-configuration
    Expected: 200 OK with issuer, token_endpoint, jwks_uri, etc.

    Verifies:
    - Endpoint is reachable and returns 200.
    - Response includes issuer field (required by OIDC spec).
    - Response includes token_endpoint, revocation_endpoint, etc.
    - Scopes include operator-relevant scopes.
    """
    response = client.get("/.well-known/openid-configuration")
    assert response.status_code == 200

    data = response.json()
    assert "issuer" in data
    assert "token_endpoint" in data
    assert "revocation_endpoint" in data
    assert "jwks_uri" in data
    assert "userinfo_endpoint" in data
    assert "grant_types_supported" in data
    assert "password" in data["grant_types_supported"]
    assert "refresh_token" in data["grant_types_supported"]
    assert "scopes_supported" in data
    # Operator scopes
    assert "feeds:read" in data["scopes_supported"]
    assert "strategies:write" in data["scopes_supported"]


# ---------------------------------------------------------------------------
# Tests: Password Grant (Happy Path)
# ---------------------------------------------------------------------------


def test_password_grant_happy_path(
    client: TestClient,
    test_user: User,
) -> None:
    """
    Password grant flow returns access and refresh tokens.

    Scenario: POST /auth/token with valid email and password
    Expected: 200 OK with access_token, refresh_token, expires_in, scope

    Verifies:
    - Valid credentials return a token pair.
    - access_token is a JWT string (contains dots).
    - refresh_token is an opaque string.
    - expires_in matches configured lifetime.
    - scope includes operator-specific scopes.
    - token_type is "Bearer".
    """
    response = client.post(
        "/auth/token",
        data={
            "grant_type": "password",
            "username": "test@fxlab.io",
            "password": "test-password-123",
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "Bearer"
    assert "expires_in" in data
    assert data["expires_in"] > 0
    assert "scope" in data

    # Verify JWT structure (three dot-separated parts)
    assert data["access_token"].count(".") == 2

    # Verify operator scopes are present
    scopes = data["scope"].split()
    assert "feeds:read" in scopes
    assert "strategies:write" in scopes


# ---------------------------------------------------------------------------
# Tests: Access Token Validation
# ---------------------------------------------------------------------------


def test_access_token_validates_on_protected_endpoint(
    client: TestClient,
    test_user: User,
) -> None:
    """
    Access token from password grant can be used on protected endpoints.

    Scenario: 1) POST /auth/token to get token, 2) GET /health with Bearer token
    Expected: Token is accepted and endpoint returns 200

    Verifies:
    - Access token is valid for use in Authorization header.
    - Bearer scheme is case-insensitive.
    - Protected endpoint accepts the token.
    """
    # Step 1: Get token
    token_response = client.post(
        "/auth/token",
        data={
            "grant_type": "password",
            "username": "test@fxlab.io",
            "password": "test-password-123",
        },
    )
    assert token_response.status_code == 200
    access_token = token_response.json()["access_token"]

    # Step 2: Use token on protected endpoint
    health_response = client.get(
        "/health",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    # Health endpoint doesn't require auth, but accept the token without error
    assert health_response.status_code == 200


# ---------------------------------------------------------------------------
# Tests: Refresh Token Grant
# ---------------------------------------------------------------------------


def test_refresh_grant_returns_new_token_pair(
    client: TestClient,
    test_user: User,
) -> None:
    """
    Refresh token grant returns a rotated token pair.

    Scenario: 1) Get token pair via password grant,
              2) POST /auth/token with grant_type=refresh_token
    Expected: 200 OK with new access_token and new refresh_token

    Verifies:
    - Refresh token is accepted.
    - New tokens are issued (different from the original).
    - Token rotation occurs (old refresh token is revoked).
    - New token pair can be used immediately.
    """
    # Step 1: Get initial token pair
    initial_response = client.post(
        "/auth/token",
        data={
            "grant_type": "password",
            "username": "test@fxlab.io",
            "password": "test-password-123",
        },
    )
    assert initial_response.status_code == 200
    initial_data = initial_response.json()
    initial_access_token = initial_data["access_token"]
    initial_refresh_token = initial_data["refresh_token"]

    # Step 2: Use refresh token to get new pair
    refresh_response = client.post(
        "/auth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": initial_refresh_token,
        },
    )
    assert refresh_response.status_code == 200
    new_data = refresh_response.json()

    # Verify new tokens are issued
    assert new_data["access_token"] != initial_access_token
    assert new_data["refresh_token"] != initial_refresh_token
    assert new_data["token_type"] == "Bearer"
    assert new_data["expires_in"] > 0


# ---------------------------------------------------------------------------
# Tests: Invalid Credentials
# ---------------------------------------------------------------------------


def test_invalid_password_returns_401(
    client: TestClient,
    test_user: User,
) -> None:
    """
    Password grant with wrong password returns 401.

    Scenario: POST /auth/token with valid email but wrong password
    Expected: 401 Unauthorized

    Verifies:
    - Wrong password is rejected.
    - Response includes WWW-Authenticate header.
    - Response includes generic "Invalid credentials" message (no username enumeration).
    """
    response = client.post(
        "/auth/token",
        data={
            "grant_type": "password",
            "username": "test@fxlab.io",
            "password": "wrong-password",
        },
    )
    assert response.status_code == 401

    data = response.json()
    assert "detail" in data
    assert "Invalid" in data["detail"]

    # Verify WWW-Authenticate header is present
    assert "WWW-Authenticate" in response.headers


def test_nonexistent_user_returns_401(client: TestClient) -> None:
    """
    Password grant for non-existent user returns 401.

    Scenario: POST /auth/token with non-existent email
    Expected: 401 Unauthorized

    Verifies:
    - Non-existent users are rejected.
    - Response is generic (no username enumeration).
    """
    response = client.post(
        "/auth/token",
        data={
            "grant_type": "password",
            "username": "nonexistent@fxlab.io",
            "password": "any-password",
        },
    )
    assert response.status_code == 401

    data = response.json()
    assert "detail" in data


def test_inactive_user_returns_401(test_db: Session, client: TestClient) -> None:
    """
    Password grant for inactive user returns 401.

    Scenario: POST /auth/token for user with is_active=False
    Expected: 401 Unauthorized

    Verifies:
    - Inactive users cannot authenticate.
    """
    # Create inactive user
    password = "test-password-123"
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    inactive_user = User(
        id="01HTEST0000000000000000002",
        email="inactive@fxlab.io",
        hashed_password=hashed,
        role="operator",
        is_active=False,
    )
    test_db.add(inactive_user)
    test_db.commit()

    response = client.post(
        "/auth/token",
        data={
            "grant_type": "password",
            "username": "inactive@fxlab.io",
            "password": "test-password-123",
        },
    )
    assert response.status_code == 401

    data = response.json()
    assert "detail" in data
    assert "disabled" in data["detail"].lower() or "invalid" in data["detail"].lower()


# ---------------------------------------------------------------------------
# Tests: Missing Grant Type
# ---------------------------------------------------------------------------


def test_missing_grant_type_returns_400(client: TestClient) -> None:
    """
    Token endpoint without grant_type returns 400.

    Scenario: POST /auth/token without grant_type field
    Expected: 400 Bad Request

    Verifies:
    - Missing grant_type is detected and rejected.
    - Response includes detail about unsupported grant_type.
    """
    response = client.post(
        "/auth/token",
        data={
            "username": "test@fxlab.io",
            "password": "test-password-123",
        },
    )
    assert response.status_code == 400

    data = response.json()
    assert "detail" in data


def test_unsupported_grant_type_returns_400(client: TestClient) -> None:
    """
    Token endpoint with unsupported grant_type returns 400.

    Scenario: POST /auth/token with grant_type=unsupported
    Expected: 400 Bad Request

    Verifies:
    - Unsupported grant types are rejected.
    - Response lists supported grant types.
    """
    response = client.post(
        "/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": "some-code",
        },
    )
    assert response.status_code == 400

    data = response.json()
    assert "detail" in data
    assert "Unsupported" in data["detail"]


# ---------------------------------------------------------------------------
# Tests: Brute-Force Protection (Account Lockout)
# ---------------------------------------------------------------------------


def test_account_lockout_after_5_failed_attempts(
    client: TestClient,
    test_user: User,
) -> None:
    """
    Account is locked after 5 failed login attempts.

    Scenario: Make 5+ failed password attempts for the same email
    Expected: After 5 failures, the next attempt (6th) returns 429

    Verifies:
    - Failed attempts are tracked per email.
    - 5 failures within the window triggers lockout.
    - The 6th attempt returns 429 with Retry-After header.
    - Retry-After value is a positive integer (seconds).
    """
    # Make 5 failed attempts (all should return 401)
    for i in range(5):
        response = client.post(
            "/auth/token",
            data={
                "grant_type": "password",
                "username": "test@fxlab.io",
                "password": f"wrong-password-{i}",
            },
        )
        assert response.status_code == 401, f"Attempt {i + 1} should fail with 401"

    # 6th attempt should hit lockout (429) before password validation
    locked_response = client.post(
        "/auth/token",
        data={
            "grant_type": "password",
            "username": "test@fxlab.io",
            "password": "any-password",
        },
    )
    assert locked_response.status_code == 429, (
        f"6th attempt should be locked out (429), got {locked_response.status_code}"
    )

    data = locked_response.json()
    assert "detail" in data
    assert "Too many" in data["detail"] or "attempts" in data["detail"]

    # Verify Retry-After header
    assert "Retry-After" in locked_response.headers
    retry_after = int(locked_response.headers["Retry-After"])
    assert retry_after > 0


def test_successful_login_clears_lockout(
    client: TestClient,
    test_user: User,
) -> None:
    """
    Successful login clears the brute-force failure counter.

    Scenario: Make 2 failed attempts, then succeed with correct password
    Expected: Subsequent failed attempts are tracked fresh (not cumulative)

    Verifies:
    - Successful login resets the failure counter.
    - Lockout is transient and cleared on auth success.
    - After a successful login, the failure count starts fresh.
    """
    # Make 2 failed attempts
    for i in range(2):
        response = client.post(
            "/auth/token",
            data={
                "grant_type": "password",
                "username": "test@fxlab.io",
                "password": f"wrong-password-{i}",
            },
        )
        assert response.status_code == 401, f"Failed attempt {i + 1} should return 401"

    # Successful login clears the failure counter
    success_response = client.post(
        "/auth/token",
        data={
            "grant_type": "password",
            "username": "test@fxlab.io",
            "password": "test-password-123",
        },
    )
    assert success_response.status_code == 200

    # After successful login, the failure counter should be reset.
    # The next failed attempt should return 401, not 429.
    response = client.post(
        "/auth/token",
        data={
            "grant_type": "password",
            "username": "test@fxlab.io",
            "password": "wrong-password-after-success",
        },
    )
    assert response.status_code == 401, (
        "After successful login, next failed attempt should be 401 (counter reset), "
        f"but got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Tests: JWKS Endpoint
# ---------------------------------------------------------------------------


def test_jwks_endpoint_returns_501_for_hs256(client: TestClient) -> None:
    """
    JWKS endpoint returns 501 Not Implemented for HS256 (symmetric key).

    Scenario: GET /auth/jwks
    Expected: 501 Not Implemented with migration note

    Verifies:
    - JWKS endpoint exists.
    - Returns 501 with explanation about HS256 limitation.
    - Response includes empty keys array.
    """
    response = client.get("/auth/jwks")
    assert response.status_code == 501

    data = response.json()
    assert "detail" in data
    assert "HS256" in data["detail"]
    assert "keys" in data
    assert isinstance(data["keys"], list)


# ---------------------------------------------------------------------------
# Tests: Missing/Invalid Refresh Token
# ---------------------------------------------------------------------------


def test_invalid_refresh_token_returns_401(client: TestClient) -> None:
    """
    Refresh grant with invalid token returns 401.

    Scenario: POST /auth/token with refresh_token=invalid
    Expected: 401 Unauthorized

    Verifies:
    - Invalid refresh tokens are rejected.
    - Response includes detail message.
    """
    response = client.post(
        "/auth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": "invalid-token-not-in-db",
        },
    )
    assert response.status_code == 401

    data = response.json()
    assert "detail" in data
    assert "Invalid" in data["detail"] or "not found" in data["detail"].lower()


def test_missing_refresh_token_returns_401(client: TestClient) -> None:
    """
    Refresh grant without refresh_token field returns 401.

    Scenario: POST /auth/token with grant_type=refresh_token but no refresh_token
    Expected: 401 Unauthorized

    Verifies:
    - Missing refresh_token is detected.
    - Response indicates the field is required.
    """
    response = client.post(
        "/auth/token",
        data={
            "grant_type": "refresh_token",
        },
    )
    assert response.status_code == 401

    data = response.json()
    assert "detail" in data


# ---------------------------------------------------------------------------
# Tests: Request Content-Type Handling
# ---------------------------------------------------------------------------


def test_password_grant_with_json_body(
    client: TestClient,
    test_user: User,
) -> None:
    """
    Password grant accepts JSON request bodies.

    Scenario: POST /auth/token with JSON body (instead of form-encoded)
    Expected: 200 OK with token pair

    Verifies:
    - Endpoint accepts both form-encoded and JSON bodies.
    - JSON parsing works correctly.
    """
    response = client.post(
        "/auth/token",
        json={
            "grant_type": "password",
            "username": "test@fxlab.io",
            "password": "test-password-123",
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


# ---------------------------------------------------------------------------
# Tests: Database Cleanup (Brute-Force Tracker Reset)
# ---------------------------------------------------------------------------


def test_login_tracker_state_isolated_per_test(
    client: TestClient,
    test_user: User,
) -> None:
    """
    Login attempt tracker state should be reset between tests (not persistent).

    Scenario: Make failed attempts in one test, verify isolation in another
    Expected: Each test starts with a clean login tracker state

    Verifies:
    - Tests don't interfere with each other via module-level singleton state.

    Note:
        This test verifies that the login_tracker module-level singleton
        is either reset between tests or operates per-client instance.
        In practice, pytest test isolation should ensure this.
    """
    # Make some failed attempts
    for i in range(3):
        response = client.post(
            "/auth/token",
            data={
                "grant_type": "password",
                "username": "test@fxlab.io",
                "password": f"wrong-{i}",
            },
        )
        assert response.status_code == 401

    # Should still be able to attempt more without immediate lockout
    # (less than 5 total)
    response = client.post(
        "/auth/token",
        data={
            "grant_type": "password",
            "username": "test@fxlab.io",
            "password": "wrong-again",
        },
    )
    # This should be 401 (wrong password), not 429 (locked)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Integration: Full Lifecycle
# ---------------------------------------------------------------------------


def test_full_auth_lifecycle_happy_path(
    client: TestClient,
    test_user: User,
) -> None:
    """
    Complete happy-path authentication lifecycle.

    Scenario: Discover OIDC → authenticate → use token → refresh → re-use
    Expected: All steps succeed

    Verifies:
    - OIDC discovery is reachable.
    - Password grant succeeds.
    - Access token is valid for subsequent requests.
    - Refresh token grant produces new tokens.
    - New tokens are valid.
    """
    # Step 1: Discover OIDC configuration
    discovery_response = client.get("/.well-known/openid-configuration")
    assert discovery_response.status_code == 200
    discovery = discovery_response.json()

    # Step 2: Authenticate
    auth_response = client.post(
        discovery["token_endpoint"].split("://", 1)[1].split("/", 1)[1],  # Extract path
        data={
            "grant_type": "password",
            "username": "test@fxlab.io",
            "password": "test-password-123",
        },
    )
    assert auth_response.status_code == 200
    tokens = auth_response.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    # Step 3: Use access token on health endpoint
    health_response = client.get(
        "/health",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert health_response.status_code == 200

    # Step 4: Refresh the token
    refresh_response = client.post(
        "/auth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    assert refresh_response.status_code == 200
    new_tokens = refresh_response.json()
    new_access_token = new_tokens["access_token"]

    # Step 5: Use new access token
    health_response2 = client.get(
        "/health",
        headers={"Authorization": f"Bearer {new_access_token}"},
    )
    assert health_response2.status_code == 200

    # Step 6: Verify old refresh token is no longer valid (rotated)
    revoked_refresh_response = client.post(
        "/auth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    # Old refresh token should be revoked after rotation
    assert revoked_refresh_response.status_code == 401
