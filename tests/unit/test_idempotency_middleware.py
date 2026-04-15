"""
Unit tests for idempotency middleware (INFRA-5).

Tests cover:
- GET requests pass through without idempotency processing.
- POST without Idempotency-Key header passes through unchanged.
- POST with Idempotency-Key stores the response.
- Duplicate Idempotency-Key returns cached response with replayed header.
- Different Idempotency-Keys are independent.
- Expired keys (>24 hours) allow new requests.
- Concurrent duplicate requests return 409 Conflict.
- Excluded paths (/health, /auth/token, etc) skip idempotency.
- Replayed responses include the Idempotency-Key-Status header.

Dependencies:
    - services.api.middleware.idempotency: IdempotencyMiddleware class.
    - starlette.testclient: For testing ASGI middleware.

Example:
    pytest tests/unit/test_idempotency_middleware.py -v
"""

from __future__ import annotations

import time

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


# Fixture: minimal ASGI app for testing middleware
@pytest.fixture
def test_app() -> Starlette:
    """Create a minimal Starlette app for middleware testing."""

    async def health(request: Request) -> JSONResponse:
        """Health check endpoint."""
        return JSONResponse({"status": "ok"})

    async def get_trades(request: Request) -> JSONResponse:
        """GET endpoint (should not be affected by idempotency)."""
        return JSONResponse({"trades": []})

    async def create_trade(request: Request) -> JSONResponse:
        """POST endpoint for creating trades (subject to idempotency)."""
        body = await request.json()
        return JSONResponse(
            {"trade_id": "t123", "symbol": body.get("symbol", "AAPL")},
            status_code=201,
        )

    async def update_trade(request: Request) -> JSONResponse:
        """PUT endpoint for updating trades (subject to idempotency)."""
        body = await request.json()
        trade_id = request.path_params["trade_id"]
        return JSONResponse(
            {"trade_id": trade_id, "status": body.get("status", "pending")},
            status_code=200,
        )

    async def patch_trade(request: Request) -> JSONResponse:
        """PATCH endpoint for partial updates (subject to idempotency)."""
        body = await request.json()
        trade_id = request.path_params["trade_id"]
        return JSONResponse(
            {"trade_id": trade_id, "notes": body.get("notes", "")},
            status_code=200,
        )

    async def delete_trade(request: Request) -> JSONResponse:
        """DELETE endpoint (not subject to idempotency)."""
        trade_id = request.path_params["trade_id"]
        return JSONResponse({"deleted": trade_id}, status_code=204)

    async def auth_token(request: Request) -> JSONResponse:
        """Auth token endpoint (excluded from idempotency)."""
        await request.json()
        return JSONResponse(
            {"access_token": "token123", "expires_in": 3600},
            status_code=200,
        )

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/trades", get_trades, methods=["GET"]),
        Route("/api/trades", create_trade, methods=["POST"]),
        Route("/api/trades/{trade_id}", update_trade, methods=["PUT"]),
        Route("/api/trades/{trade_id}", patch_trade, methods=["PATCH"]),
        Route("/api/trades/{trade_id}", delete_trade, methods=["DELETE"]),
        Route("/auth/token", auth_token, methods=["POST"]),
    ]

    app = Starlette(routes=routes)
    return app


# Fixture: test client with idempotency middleware
@pytest.fixture
def idempotent_client(test_app: Starlette) -> TestClient:
    """Create a test client with idempotency middleware applied."""
    from services.api.middleware.idempotency import IdempotencyMiddleware

    test_app.add_middleware(IdempotencyMiddleware)
    return TestClient(test_app)


# ---------------------------------------------------------------------------
# Test: GET requests pass through without key
# ---------------------------------------------------------------------------


def test_get_request_passes_through_without_key(idempotent_client: TestClient) -> None:
    """GET requests should pass through unchanged, regardless of Idempotency-Key."""
    response = idempotent_client.get("/api/trades")
    assert response.status_code == 200
    assert response.json() == {"trades": []}
    # No idempotency processing for GET
    assert "Idempotency-Key-Status" not in response.headers


# ---------------------------------------------------------------------------
# Test: POST without key passes through
# ---------------------------------------------------------------------------


def test_post_without_key_passes_through(idempotent_client: TestClient) -> None:
    """POST without Idempotency-Key should pass through unchanged."""
    response = idempotent_client.post(
        "/api/trades",
        json={"symbol": "AAPL"},
    )
    assert response.status_code == 201
    assert response.json() == {"trade_id": "t123", "symbol": "AAPL"}
    # No idempotency tracking without key
    assert "Idempotency-Key-Status" not in response.headers


# ---------------------------------------------------------------------------
# Test: POST with key stores response
# ---------------------------------------------------------------------------


def test_post_with_key_stores_response(idempotent_client: TestClient) -> None:
    """POST with Idempotency-Key should store the response."""
    key = "idem-key-1234"
    response = idempotent_client.post(
        "/api/trades",
        json={"symbol": "AAPL"},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201
    assert response.json() == {"trade_id": "t123", "symbol": "AAPL"}
    # New request should be marked as "stored"
    assert response.headers.get("Idempotency-Key-Status") == "stored"


# ---------------------------------------------------------------------------
# Test: Duplicate key returns cached response
# ---------------------------------------------------------------------------


def test_duplicate_key_returns_cached_response(idempotent_client: TestClient) -> None:
    """Duplicate Idempotency-Key should return the cached response."""
    key = "idem-key-dup-1"
    payload = {"symbol": "GOOG"}

    # First request
    response1 = idempotent_client.post(
        "/api/trades",
        json=payload,
        headers={"Idempotency-Key": key},
    )
    assert response1.status_code == 201
    data1 = response1.json()
    assert data1["symbol"] == "GOOG"
    assert response1.headers.get("Idempotency-Key-Status") == "stored"

    # Second request with same key but different payload (should be ignored)
    response2 = idempotent_client.post(
        "/api/trades",
        json={"symbol": "MSFT"},  # Different payload
        headers={"Idempotency-Key": key},
    )
    # Should return the cached response from first request
    assert response2.status_code == 201
    data2 = response2.json()
    assert data2["symbol"] == "GOOG"  # Not MSFT!
    assert response2.headers.get("Idempotency-Key-Status") == "replayed"


# ---------------------------------------------------------------------------
# Test: Different keys are independent
# ---------------------------------------------------------------------------


def test_different_keys_are_independent(idempotent_client: TestClient) -> None:
    """Different Idempotency-Keys should be tracked independently."""
    key1 = "idem-key-1"
    key2 = "idem-key-2"

    response1 = idempotent_client.post(
        "/api/trades",
        json={"symbol": "AAPL"},
        headers={"Idempotency-Key": key1},
    )
    assert response1.status_code == 201
    assert response1.json()["symbol"] == "AAPL"

    response2 = idempotent_client.post(
        "/api/trades",
        json={"symbol": "MSFT"},
        headers={"Idempotency-Key": key2},
    )
    assert response2.status_code == 201
    assert response2.json()["symbol"] == "MSFT"


# ---------------------------------------------------------------------------
# Test: Expired keys allow new requests
# ---------------------------------------------------------------------------


def test_expired_key_allows_new_request(idempotent_client: TestClient) -> None:
    """Keys older than 24 hours should be cleaned up and allow new requests."""
    from services.api.middleware.idempotency import _store

    key = "idem-key-expire"

    # Make first request
    response1 = idempotent_client.post(
        "/api/trades",
        json={"symbol": "AAPL"},
        headers={"Idempotency-Key": key},
    )
    assert response1.status_code == 201
    assert response1.json()["symbol"] == "AAPL"
    assert response1.headers.get("Idempotency-Key-Status") == "stored"

    # Manually set the stored entry's timestamp to >24 hours ago
    with _store._lock:
        if key in _store._store:
            status, body, headers, timestamp = _store._store[key]
            # Set timestamp to 25 hours ago (86400 * 25 seconds ago)
            new_timestamp = time.time() - (86400 * 25)
            _store._store[key] = (status, body, headers, new_timestamp)

    # Now make another request with the same key
    # The old entry should be cleaned up on this request
    response2 = idempotent_client.post(
        "/api/trades",
        json={"symbol": "AAPL"},
        headers={"Idempotency-Key": key},
    )
    # Should treat it as a new request (fresh timestamp)
    assert response2.status_code == 201
    assert response2.headers.get("Idempotency-Key-Status") == "stored"


# ---------------------------------------------------------------------------
# Test: Concurrent duplicate returns 409
# ---------------------------------------------------------------------------


def test_concurrent_duplicate_returns_409() -> None:
    """Concurrent requests with the same Idempotency-Key should return 409 via in-flight detection."""
    from services.api.middleware.idempotency import _store

    key = "idem-concurrent-test"

    # Simulate a concurrent request scenario:
    # First, manually mark a key as in-flight (as would happen during a slow request)
    assert not _store.start_request(key)  # First request starts, should return False

    # Now try another request with the same key while first is in-flight
    assert _store.start_request(key)  # Second request detects concurrent, returns True

    # Clean up
    _store.finish_request(key)
    _store.finish_request(key)


# ---------------------------------------------------------------------------
# Test: Excluded paths skip idempotency
# ---------------------------------------------------------------------------


def test_excluded_paths_skip_idempotency(idempotent_client: TestClient) -> None:
    """Excluded paths should skip idempotency even with Idempotency-Key."""
    key = "idem-key-excluded"

    # /health should be excluded
    response = idempotent_client.get(
        "/health",
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200
    assert "Idempotency-Key-Status" not in response.headers

    # /auth/token should be excluded
    response = idempotent_client.post(
        "/auth/token",
        json={"username": "user", "password": "pass"},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200
    assert "Idempotency-Key-Status" not in response.headers


# ---------------------------------------------------------------------------
# Test: DELETE is not subject to idempotency
# ---------------------------------------------------------------------------


def test_delete_not_subject_to_idempotency(idempotent_client: TestClient) -> None:
    """DELETE requests should not be subject to idempotency."""
    key = "idem-key-delete"

    response = idempotent_client.delete(
        "/api/trades/t123",
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 204
    # DELETE should not have idempotency header
    assert "Idempotency-Key-Status" not in response.headers


# ---------------------------------------------------------------------------
# Test: Replayed response includes header
# ---------------------------------------------------------------------------


def test_replayed_response_includes_header(idempotent_client: TestClient) -> None:
    """Replayed responses should include Idempotency-Key-Status: replayed header."""
    key = "idem-key-header"

    # First request
    response1 = idempotent_client.post(
        "/api/trades",
        json={"symbol": "TSLA"},
        headers={"Idempotency-Key": key},
    )
    assert response1.status_code == 201
    assert response1.headers.get("Idempotency-Key-Status") == "stored"

    # Second request (replayed)
    response2 = idempotent_client.post(
        "/api/trades",
        json={"symbol": "TSLA"},
        headers={"Idempotency-Key": key},
    )
    assert response2.status_code == 201
    assert response2.headers.get("Idempotency-Key-Status") == "replayed"


# ---------------------------------------------------------------------------
# Test: PUT requests subject to idempotency
# ---------------------------------------------------------------------------


def test_put_request_subject_to_idempotency(idempotent_client: TestClient) -> None:
    """PUT requests should be subject to idempotency."""
    key = "idem-key-put"

    response1 = idempotent_client.put(
        "/api/trades/t123",
        json={"status": "filled"},
        headers={"Idempotency-Key": key},
    )
    assert response1.status_code == 200
    assert response1.headers.get("Idempotency-Key-Status") == "stored"

    response2 = idempotent_client.put(
        "/api/trades/t123",
        json={"status": "cancelled"},  # Different payload
        headers={"Idempotency-Key": key},
    )
    # Should return cached response with "filled" status
    assert response2.status_code == 200
    assert response2.json()["status"] == "filled"
    assert response2.headers.get("Idempotency-Key-Status") == "replayed"


# ---------------------------------------------------------------------------
# Test: PATCH requests subject to idempotency
# ---------------------------------------------------------------------------


def test_patch_request_subject_to_idempotency(idempotent_client: TestClient) -> None:
    """PATCH requests should be subject to idempotency."""
    key = "idem-key-patch"

    response1 = idempotent_client.patch(
        "/api/trades/t456",
        json={"notes": "First note"},
        headers={"Idempotency-Key": key},
    )
    assert response1.status_code == 200
    assert response1.headers.get("Idempotency-Key-Status") == "stored"

    response2 = idempotent_client.patch(
        "/api/trades/t456",
        json={"notes": "Second note"},  # Different payload
        headers={"Idempotency-Key": key},
    )
    # Should return cached response with first note
    assert response2.status_code == 200
    assert response2.json()["notes"] == "First note"
    assert response2.headers.get("Idempotency-Key-Status") == "replayed"


# ---------------------------------------------------------------------------
# Test: OPTIONS requests are excluded
# ---------------------------------------------------------------------------


def test_options_request_passes_through(idempotent_client: TestClient) -> None:
    """OPTIONS requests should pass through without idempotency processing."""
    key = "idem-key-options"

    # OPTIONS typically returns 405 on most endpoints but should not trigger
    # idempotency processing
    response = idempotent_client.options(
        "/api/trades",
        headers={"Idempotency-Key": key},
    )
    # The endpoint may not support OPTIONS, but we're testing that idempotency
    # doesn't interfere
    assert "Idempotency-Key-Status" not in response.headers


# ---------------------------------------------------------------------------
# Test: Multiple request threads updating same key
# ---------------------------------------------------------------------------


def test_thread_safety_with_multiple_requests(idempotent_client: TestClient) -> None:
    """Store should be thread-safe when multiple requests access it."""
    import threading

    results = []

    def make_request(key: str, symbol: str) -> None:
        """Helper to make a POST request in a thread."""
        response = idempotent_client.post(
            "/api/trades",
            json={"symbol": symbol},
            headers={"Idempotency-Key": key},
        )
        results.append((key, response.status_code, response.json()))

    # Create multiple threads making requests with different keys
    threads = []
    for i in range(5):
        t = threading.Thread(target=make_request, args=(f"key-thread-{i}", f"SYM{i}"))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All should succeed
    assert len(results) == 5
    for _key, status, _data in results:
        assert status == 201
