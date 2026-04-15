"""
Unit tests for M11 DrainMiddleware — graceful shutdown request draining.

Covers:
- Middleware allows requests when accepting=True (normal operation)
- Middleware returns 503 when accepting=False (draining)
- In-flight request counter increments and decrements correctly
- wait_for_drain() blocks until in-flight count reaches 0
- wait_for_drain() respects timeout and returns remaining count
- Thread safety: concurrent requests increment/decrement safely
- Health endpoint (/health) is exempt from drain (always 200)
- 503 response includes Retry-After header

Dependencies:
- services.api.middleware.drain: DrainMiddleware
- starlette.testclient: TestClient
- fastapi: FastAPI test app
"""

from __future__ import annotations

import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.middleware.drain import DrainMiddleware

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_app(drain: DrainMiddleware | None = None) -> tuple[FastAPI, DrainMiddleware]:
    """Create a minimal FastAPI app with DrainMiddleware installed."""
    app = FastAPI()
    if drain is None:
        drain = DrainMiddleware(app)
    app.add_middleware(DrainMiddleware.__class__, drain_state=drain)

    @app.get("/test")
    async def test_route() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    async def health_route() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/slow")
    async def slow_route() -> dict[str, str]:
        import asyncio

        await asyncio.sleep(0.5)
        return {"status": "done"}

    return app, drain


# ------------------------------------------------------------------
# Tests: Normal Operation
# ------------------------------------------------------------------


class TestDrainMiddlewareNormalOperation:
    """DrainMiddleware allows requests when accepting=True."""

    def test_requests_allowed_when_accepting(self) -> None:
        """Normal request returns 200 when drain is not active."""
        drain = DrainMiddleware()
        app = FastAPI()

        @app.get("/test")
        async def test_route() -> dict[str, str]:
            return {"status": "ok"}

        app.add_middleware(type(drain), drain_state=drain)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_in_flight_count_zero_at_rest(self) -> None:
        """In-flight counter is 0 when no requests are active."""
        drain = DrainMiddleware()
        assert drain.in_flight_count == 0


# ------------------------------------------------------------------
# Tests: Drain Mode (503)
# ------------------------------------------------------------------


class TestDrainMiddleware503:
    """DrainMiddleware returns 503 when accepting is False."""

    def test_returns_503_when_draining(self) -> None:
        """New request returns 503 Service Unavailable during drain."""
        drain = DrainMiddleware()
        app = FastAPI()

        @app.get("/test")
        async def test_route() -> dict[str, str]:
            return {"status": "ok"}

        app.add_middleware(type(drain), drain_state=drain)
        drain.stop_accepting()
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 503

    def test_503_includes_retry_after_header(self) -> None:
        """503 response includes Retry-After header."""
        drain = DrainMiddleware()
        app = FastAPI()

        @app.get("/test")
        async def test_route() -> dict[str, str]:
            return {"status": "ok"}

        app.add_middleware(type(drain), drain_state=drain)
        drain.stop_accepting()
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 503
        assert "Retry-After" in resp.headers
        assert resp.headers["Retry-After"] == "5"

    def test_503_body_includes_detail(self) -> None:
        """503 response body includes a detail message."""
        drain = DrainMiddleware()
        app = FastAPI()

        @app.get("/test")
        async def test_route() -> dict[str, str]:
            return {"status": "ok"}

        app.add_middleware(type(drain), drain_state=drain)
        drain.stop_accepting()
        client = TestClient(app)
        resp = client.get("/test")
        body = resp.json()
        assert "detail" in body
        assert "shutting down" in body["detail"].lower()

    def test_health_endpoint_exempt_from_drain(self) -> None:
        """Health endpoint always returns 200, even during drain."""
        drain = DrainMiddleware()
        app = FastAPI()

        @app.get("/health")
        async def health_route() -> dict[str, str]:
            return {"status": "healthy"}

        app.add_middleware(type(drain), drain_state=drain)
        drain.stop_accepting()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200


# ------------------------------------------------------------------
# Tests: In-Flight Tracking
# ------------------------------------------------------------------


class TestInFlightTracking:
    """DrainMiddleware tracks in-flight request count atomically."""

    def test_in_flight_count_returns_to_zero_after_request(self) -> None:
        """After a request completes, in-flight count returns to 0."""
        drain = DrainMiddleware()
        app = FastAPI()

        @app.get("/test")
        async def test_route() -> dict[str, str]:
            return {"status": "ok"}

        app.add_middleware(type(drain), drain_state=drain)
        client = TestClient(app)
        client.get("/test")
        assert drain.in_flight_count == 0

    def test_accepting_state_toggle(self) -> None:
        """stop_accepting() sets accepting to False, resume_accepting() to True."""
        drain = DrainMiddleware()
        assert drain.is_accepting is True
        drain.stop_accepting()
        assert drain.is_accepting is False
        drain.resume_accepting()
        assert drain.is_accepting is True


# ------------------------------------------------------------------
# Tests: wait_for_drain
# ------------------------------------------------------------------


class TestWaitForDrain:
    """wait_for_drain() blocks until in-flight count reaches 0 or timeout."""

    def test_wait_for_drain_returns_zero_when_no_in_flight(self) -> None:
        """Immediate return with 0 when no requests are active."""
        drain = DrainMiddleware()
        remaining = drain.wait_for_drain(timeout_s=1.0)
        assert remaining == 0

    def test_wait_for_drain_respects_timeout(self) -> None:
        """Returns remaining count when timeout expires with in-flight requests."""
        drain = DrainMiddleware()
        # Simulate an in-flight request by manually incrementing
        drain._in_flight.increment()
        start = time.monotonic()
        remaining = drain.wait_for_drain(timeout_s=0.5)
        elapsed = time.monotonic() - start
        assert remaining == 1
        assert elapsed >= 0.4  # Should have waited close to timeout
        # Clean up
        drain._in_flight.decrement()

    def test_wait_for_drain_returns_when_requests_complete(self) -> None:
        """Returns 0 once all in-flight requests complete."""
        drain = DrainMiddleware()
        drain._in_flight.increment()

        def _complete_after_delay() -> None:
            time.sleep(0.2)
            drain._in_flight.decrement()

        t = threading.Thread(target=_complete_after_delay)
        t.start()
        remaining = drain.wait_for_drain(timeout_s=2.0)
        t.join()
        assert remaining == 0


# ------------------------------------------------------------------
# Tests: Thread Safety
# ------------------------------------------------------------------


class TestDrainThreadSafety:
    """In-flight counter is safe under concurrent access."""

    def test_concurrent_increments_and_decrements(self) -> None:
        """Counter remains accurate after many concurrent increments/decrements."""
        drain = DrainMiddleware()
        num_threads = 50

        def _inc_dec() -> None:
            drain._in_flight.increment()
            time.sleep(0.01)
            drain._in_flight.decrement()

        threads = [threading.Thread(target=_inc_dec) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert drain.in_flight_count == 0
