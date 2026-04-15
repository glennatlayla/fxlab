"""
Unit tests for SchwabOAuthManager (M4 — Schwab Broker Adapter).

Tests cover:
- initialize(): first token exchange via refresh token
- get_access_token(): returns valid token, auto-refreshes when expiring
- get_access_token(): thread safety (lock prevents race conditions)
- get_access_token(): not initialized raises AuthError
- _refresh(): 400/401 → AuthError (token revoked)
- _refresh(): 5xx → TransientError
- _refresh(): timeout → TransientError
- _refresh(): connection error → ExternalServiceError
- _refresh(): unexpected status → ExternalServiceError
- Token rotation: server returns new refresh token
- Properties: current_refresh_token, is_initialized

Dependencies:
    - services.api.infrastructure.schwab_auth: SchwabOAuthManager, TokenState
    - libs.contracts.schwab_config: SchwabConfig
    - httpx: MockTransport for HTTP interception
    - libs.contracts.errors: domain exceptions

Example:
    pytest tests/unit/test_schwab_auth.py -v
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx
import pytest

from libs.contracts.errors import AuthError, ExternalServiceError, TransientError
from libs.contracts.schwab_config import SchwabConfig
from services.api.infrastructure.schwab_auth import (
    _REFRESH_BUFFER_SECONDS,
    SchwabOAuthManager,
    TokenState,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_TEST_CONFIG = SchwabConfig(
    client_id="test-client-id",
    client_secret="test-client-secret",
    redirect_uri="https://localhost/callback",
    account_hash="TEST_ACCOUNT_HASH",
)

_TOKEN_RESPONSE: dict[str, Any] = {
    "access_token": "new-access-token-abc123",
    "refresh_token": "new-refresh-token-xyz789",
    "expires_in": 1800,
    "token_type": "Bearer",
    "scope": "api",
}

_TOKEN_RESPONSE_NO_REFRESH: dict[str, Any] = {
    "access_token": "new-access-token-abc123",
    "expires_in": 1800,
    "token_type": "Bearer",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_transport(
    *,
    status: int = 200,
    body: dict[str, Any] | None = None,
    side_effect: Exception | None = None,
) -> httpx.MockTransport:
    """
    Create a mock transport for the Schwab token endpoint.

    Args:
        status: HTTP status code to return.
        body: JSON response body.
        side_effect: Exception to raise instead of returning a response.

    Returns:
        httpx.MockTransport instance.
    """
    resp_body = body if body is not None else _TOKEN_RESPONSE

    def handler(request: httpx.Request) -> httpx.Response:
        if side_effect is not None:
            raise side_effect
        content = json.dumps(resp_body)
        return httpx.Response(
            status,
            content=content,
            headers={"content-type": "application/json"},
        )

    return httpx.MockTransport(handler)


def _make_manager(
    transport: httpx.MockTransport | None = None,
    config: SchwabConfig | None = None,
) -> SchwabOAuthManager:
    """Create a SchwabOAuthManager with a mock HTTP client."""
    cfg = config or _TEST_CONFIG
    if transport is not None:
        client = httpx.Client(transport=transport)
        return SchwabOAuthManager(config=cfg, http_client=client)
    return SchwabOAuthManager(config=cfg)


# ---------------------------------------------------------------------------
# TokenState tests
# ---------------------------------------------------------------------------


class TestTokenState:
    """Tests for the TokenState dataclass."""

    def test_token_state_stores_fields(self) -> None:
        """TokenState should store access_token, refresh_token, expires_at."""
        ts = TokenState(
            access_token="at",
            refresh_token="rt",
            expires_at=1234567890.0,
        )
        assert ts.access_token == "at"
        assert ts.refresh_token == "rt"
        assert ts.expires_at == 1234567890.0


# ---------------------------------------------------------------------------
# Initialize tests
# ---------------------------------------------------------------------------


class TestSchwabOAuthInitialize:
    """Tests for initialize()."""

    def test_initialize_obtains_first_token(self) -> None:
        """initialize() should exchange refresh token for access token."""
        transport = _make_transport(status=200, body=_TOKEN_RESPONSE)
        manager = _make_manager(transport)

        manager.initialize(refresh_token="initial-refresh-token")

        assert manager.is_initialized is True
        assert manager.current_refresh_token == "new-refresh-token-xyz789"

    def test_initialize_stores_access_token(self) -> None:
        """After initialize(), get_access_token() should return the new token."""
        transport = _make_transport(status=200, body=_TOKEN_RESPONSE)
        manager = _make_manager(transport)

        manager.initialize(refresh_token="initial-rt")

        token = manager.get_access_token()
        assert token == "new-access-token-abc123"

    def test_initialize_auth_error_400(self) -> None:
        """initialize() with revoked token (400) should raise AuthError."""
        transport = _make_transport(status=400, body={"error": "invalid_grant"})
        manager = _make_manager(transport)

        with pytest.raises(AuthError, match="invalid or revoked"):
            manager.initialize(refresh_token="revoked-token")

        assert manager.is_initialized is False

    def test_initialize_auth_error_401(self) -> None:
        """initialize() with invalid credentials (401) should raise AuthError."""
        transport = _make_transport(status=401, body={"error": "unauthorized"})
        manager = _make_manager(transport)

        with pytest.raises(AuthError, match="invalid or revoked"):
            manager.initialize(refresh_token="bad-token")

    def test_initialize_server_error_500(self) -> None:
        """initialize() with 500 from token endpoint should raise TransientError."""
        transport = _make_transport(status=500, body={"error": "internal"})
        manager = _make_manager(transport)

        with pytest.raises(TransientError, match="500"):
            manager.initialize(refresh_token="valid-token")

    def test_initialize_server_error_503(self) -> None:
        """initialize() with 503 from token endpoint should raise TransientError."""
        transport = _make_transport(status=503, body={"error": "unavailable"})
        manager = _make_manager(transport)

        with pytest.raises(TransientError, match="503"):
            manager.initialize(refresh_token="valid-token")

    def test_initialize_unexpected_status(self) -> None:
        """initialize() with unexpected status (e.g. 403) should raise ExternalServiceError."""
        transport = _make_transport(status=403, body={"error": "forbidden"})
        manager = _make_manager(transport)

        with pytest.raises(ExternalServiceError, match="unexpected status 403"):
            manager.initialize(refresh_token="valid-token")

    def test_initialize_timeout(self) -> None:
        """initialize() with timeout should raise TransientError."""
        transport = _make_transport(side_effect=httpx.TimeoutException("timed out"))
        manager = _make_manager(transport)

        with pytest.raises(TransientError, match="timed out"):
            manager.initialize(refresh_token="valid-token")

    def test_initialize_connection_error(self) -> None:
        """initialize() with connection failure should raise ExternalServiceError."""
        transport = _make_transport(side_effect=httpx.ConnectError("connection refused"))
        manager = _make_manager(transport)

        with pytest.raises(ExternalServiceError, match="unreachable"):
            manager.initialize(refresh_token="valid-token")


# ---------------------------------------------------------------------------
# get_access_token tests
# ---------------------------------------------------------------------------


class TestSchwabOAuthGetAccessToken:
    """Tests for get_access_token()."""

    def test_get_access_token_not_initialized_raises(self) -> None:
        """get_access_token() without initialize() should raise AuthError."""
        manager = _make_manager(_make_transport())

        with pytest.raises(AuthError, match="not initialized"):
            manager.get_access_token()

    def test_get_access_token_returns_valid_token(self) -> None:
        """get_access_token() should return current access token."""
        transport = _make_transport(status=200, body=_TOKEN_RESPONSE)
        manager = _make_manager(transport)
        manager.initialize(refresh_token="rt-initial")

        token = manager.get_access_token()
        assert token == "new-access-token-abc123"

    def test_get_access_token_auto_refresh_when_expiring(self) -> None:
        """get_access_token() should auto-refresh when token is about to expire."""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            body = {
                "access_token": f"access-token-{call_count['n']}",
                "refresh_token": f"refresh-token-{call_count['n']}",
                "expires_in": 1800,
            }
            return httpx.Response(
                200,
                content=json.dumps(body),
                headers={"content-type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        manager = _make_manager(transport)
        manager.initialize(refresh_token="rt-initial")

        assert call_count["n"] == 1
        assert manager.get_access_token() == "access-token-1"

        # Simulate token expiring by setting expires_at to past
        manager._token_state = TokenState(
            access_token="old-token",
            refresh_token="refresh-token-1",
            expires_at=time.time() - 10,  # Already expired
        )

        # get_access_token() should trigger a refresh
        token = manager.get_access_token()
        assert call_count["n"] == 2
        assert token == "access-token-2"

    def test_get_access_token_no_refresh_when_not_expiring(self) -> None:
        """get_access_token() should NOT refresh if token is still valid."""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            body = {
                "access_token": f"access-token-{call_count['n']}",
                "refresh_token": "rt",
                "expires_in": 1800,
            }
            return httpx.Response(
                200,
                content=json.dumps(body),
                headers={"content-type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        manager = _make_manager(transport)
        manager.initialize(refresh_token="rt-initial")

        # First call from initialize
        assert call_count["n"] == 1

        # Multiple get_access_token calls should NOT trigger refresh
        manager.get_access_token()
        manager.get_access_token()
        manager.get_access_token()
        assert call_count["n"] == 1  # Still just the initial call

    def test_get_access_token_refresh_within_buffer(self) -> None:
        """Token should be refreshed when within REFRESH_BUFFER_SECONDS of expiry."""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            body = {
                "access_token": f"access-token-{call_count['n']}",
                "refresh_token": "rt",
                "expires_in": 1800,
            }
            return httpx.Response(
                200,
                content=json.dumps(body),
                headers={"content-type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        manager = _make_manager(transport)
        manager.initialize(refresh_token="rt-initial")

        # Set expiry to within buffer window (e.g., 60 seconds from now)
        manager._token_state = TokenState(
            access_token="nearly-expired",
            refresh_token="rt",
            expires_at=time.time() + _REFRESH_BUFFER_SECONDS - 10,
        )

        token = manager.get_access_token()
        assert call_count["n"] == 2  # Refresh triggered
        assert token == "access-token-2"


# ---------------------------------------------------------------------------
# Token rotation tests
# ---------------------------------------------------------------------------


class TestSchwabOAuthTokenRotation:
    """Tests for refresh token rotation behavior."""

    def test_refresh_updates_refresh_token(self) -> None:
        """Server-returned refresh token should replace the old one."""
        transport = _make_transport(
            status=200,
            body={
                "access_token": "at-new",
                "refresh_token": "rt-rotated",
                "expires_in": 1800,
            },
        )
        manager = _make_manager(transport)
        manager.initialize(refresh_token="rt-original")

        assert manager.current_refresh_token == "rt-rotated"

    def test_refresh_keeps_old_refresh_token_if_not_returned(self) -> None:
        """If server omits refresh_token, the old one should be preserved."""
        transport = _make_transport(
            status=200,
            body=_TOKEN_RESPONSE_NO_REFRESH,
        )
        manager = _make_manager(transport)
        manager.initialize(refresh_token="rt-original")

        # Server did not return a new refresh token, so the original is kept
        assert manager.current_refresh_token == "rt-original"


# ---------------------------------------------------------------------------
# Properties tests
# ---------------------------------------------------------------------------


class TestSchwabOAuthProperties:
    """Tests for read-only properties."""

    def test_current_refresh_token_none_before_init(self) -> None:
        """current_refresh_token should be None before initialize()."""
        manager = _make_manager(_make_transport())
        assert manager.current_refresh_token is None

    def test_is_initialized_false_before_init(self) -> None:
        """is_initialized should be False before initialize()."""
        manager = _make_manager(_make_transport())
        assert manager.is_initialized is False

    def test_is_initialized_true_after_init(self) -> None:
        """is_initialized should be True after successful initialize()."""
        transport = _make_transport(status=200, body=_TOKEN_RESPONSE)
        manager = _make_manager(transport)
        manager.initialize(refresh_token="rt")
        assert manager.is_initialized is True


# ---------------------------------------------------------------------------
# Thread safety tests
# ---------------------------------------------------------------------------


class TestSchwabOAuthThreadSafety:
    """Tests for thread-safe token access."""

    def test_concurrent_get_access_token(self) -> None:
        """Multiple threads calling get_access_token() should not corrupt state."""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            body = {
                "access_token": f"access-token-{call_count['n']}",
                "refresh_token": "rt",
                "expires_in": 1800,
            }
            return httpx.Response(
                200,
                content=json.dumps(body),
                headers={"content-type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        manager = _make_manager(transport)
        manager.initialize(refresh_token="rt-initial")

        results: list[str] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                token = manager.get_access_token()
                results.append(token)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(results) == 10
        # All tokens should be valid strings (non-empty)
        assert all(t.startswith("access-token") for t in results)


# ---------------------------------------------------------------------------
# Request validation tests
# ---------------------------------------------------------------------------


class TestSchwabOAuthRequestFormat:
    """Tests verifying the OAuth token request is correctly formatted."""

    def test_refresh_sends_basic_auth(self) -> None:
        """Token request should include Basic auth header with base64(client_id:client_secret)."""
        import base64

        captured_request: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_request.append(request)
            body = json.dumps(_TOKEN_RESPONSE)
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        manager = _make_manager(transport)
        manager.initialize(refresh_token="rt-test")

        assert len(captured_request) == 1
        req = captured_request[0]

        # Verify Basic auth header
        auth_header = req.headers.get("authorization", "")
        assert auth_header.startswith("Basic ")
        decoded = base64.b64decode(auth_header.split(" ", 1)[1]).decode()
        assert decoded == "test-client-id:test-client-secret"

    def test_refresh_sends_correct_form_data(self) -> None:
        """Token request should send grant_type=refresh_token in form body."""
        captured_request: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_request.append(request)
            body = json.dumps(_TOKEN_RESPONSE)
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        manager = _make_manager(transport)
        manager.initialize(refresh_token="rt-test-form")

        assert len(captured_request) == 1
        req = captured_request[0]

        # Verify Content-Type
        assert "application/x-www-form-urlencoded" in req.headers.get("content-type", "")

        # Verify form data
        body_str = req.content.decode()
        assert "grant_type=refresh_token" in body_str
        assert "refresh_token=rt-test-form" in body_str

    def test_refresh_posts_to_token_url(self) -> None:
        """Token request should POST to the configured token_url."""
        captured_request: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_request.append(request)
            body = json.dumps(_TOKEN_RESPONSE)
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        manager = _make_manager(transport)
        manager.initialize(refresh_token="rt-test")

        assert len(captured_request) == 1
        req = captured_request[0]
        assert req.method == "POST"
        assert str(req.url) == _TEST_CONFIG.token_url


# ---------------------------------------------------------------------------
# SchwabConfig tests
# ---------------------------------------------------------------------------


class TestSchwabConfig:
    """Tests for SchwabConfig model."""

    def test_paper_factory(self) -> None:
        """SchwabConfig.paper() should use Schwab API base URL."""
        config = SchwabConfig.paper(
            client_id="cid",
            client_secret="cs",
            account_hash="hash",
        )
        assert "schwabapi.com" in config.base_url

    def test_live_factory(self) -> None:
        """SchwabConfig.live() should use Schwab API base URL."""
        config = SchwabConfig.live(
            client_id="cid",
            client_secret="cs",
            account_hash="hash",
        )
        assert "schwabapi.com" in config.base_url

    def test_url_properties(self) -> None:
        """URL properties should construct correct Schwab endpoints."""
        config = SchwabConfig(
            client_id="cid",
            client_secret="cs",
            account_hash="ACCT_HASH",
        )
        assert config.orders_url.endswith("/accounts/ACCT_HASH/orders")
        assert config.account_url.endswith("/accounts/ACCT_HASH")
        assert "fields=positions" in config.positions_url

    def test_config_is_frozen(self) -> None:
        """SchwabConfig should be immutable."""
        config = SchwabConfig(
            client_id="cid",
            client_secret="cs",
            account_hash="hash",
        )
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="frozen"):
            config.client_id = "new"  # type: ignore[misc]

    def test_base_url_trailing_slash_stripped(self) -> None:
        """base_url trailing slash should be stripped."""
        config = SchwabConfig(
            client_id="cid",
            client_secret="cs",
            account_hash="hash",
            base_url="https://api.schwabapi.com/trader/v1/",
        )
        assert not config.base_url.endswith("/")
        assert config.orders_url.endswith("/accounts/hash/orders")
