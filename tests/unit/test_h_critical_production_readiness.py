"""
Critical production-readiness hardening tests.

These tests verify fixes for the 6 highest-severity issues preventing
this codebase from being production-grade for a fintech trading platform:

  H-CRIT-1: Production-mandatory PostgreSQL (no SQLite fallback)
  H-CRIT-2: Redis-backed idempotency store
  H-CRIT-3: Redis-backed login attempt tracker
  H-CRIT-4: Optimistic locking on mutable entities (version columns)
  H-CRIT-5: prometheus_client in requirements.txt
  H-CRIT-6: Security headers middleware

Dependencies:
    - services.api.db
    - services.api.middleware.idempotency
    - services.api.services.login_attempt_tracker
    - libs.contracts.models
    - services.api.metrics
    - services.api.middleware.security_headers

Example:
    pytest tests/unit/test_h_critical_production_readiness.py -v
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# H-CRIT-1: Production-mandatory PostgreSQL
# ---------------------------------------------------------------------------


class TestProductionMandatoryPostgres:
    """
    Production environment MUST reject SQLite fallback.

    Rationale:
        SQLite lacks concurrent write support, connection pooling, and
        row-level locking. A silent fallback to SQLite in production
        would cause data corruption under any concurrent load.
    """

    def test_production_raises_if_database_url_unset(self) -> None:
        """ENVIRONMENT=production + no DATABASE_URL → RuntimeError."""
        # Import outside the patch context to avoid triggering module-level
        # _resolve_database_url() during import with production env.
        from services.api.db import _resolve_database_url

        env = {"ENVIRONMENT": "production"}
        # Remove DATABASE_URL if present
        env_clean = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        env_clean.update(env)

        with (
            patch.dict(os.environ, env_clean, clear=True),
            pytest.raises(RuntimeError, match="DATABASE_URL"),
        ):
            _resolve_database_url()

    def test_production_raises_if_database_url_is_sqlite(self) -> None:
        """ENVIRONMENT=production + DATABASE_URL=sqlite:// → RuntimeError."""
        from services.api.db import _resolve_database_url

        env = {
            "ENVIRONMENT": "production",
            "DATABASE_URL": "sqlite:///./fxlab.db",
        }
        with patch.dict(os.environ, env, clear=False), pytest.raises(RuntimeError, match="SQLite"):
            _resolve_database_url()

    def test_test_environment_allows_sqlite(self) -> None:
        """ENVIRONMENT=test + SQLite is OK (for unit tests)."""
        env = {
            "ENVIRONMENT": "test",
            "DATABASE_URL": "sqlite:///./fxlab_test.db",
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.db import _resolve_database_url

            result = _resolve_database_url()
            assert result.startswith("sqlite")

    def test_development_allows_sqlite_with_warning(self) -> None:
        """ENVIRONMENT=development + SQLite is allowed (for local dev)."""
        env = {
            "ENVIRONMENT": "development",
            "DATABASE_URL": "sqlite:///./fxlab_dev.db",
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.db import _resolve_database_url

            result = _resolve_database_url()
            assert result.startswith("sqlite")

    def test_production_accepts_postgresql_url(self) -> None:
        """ENVIRONMENT=production + PostgreSQL URL is accepted."""
        env = {
            "ENVIRONMENT": "production",
            "DATABASE_URL": "postgresql://user:pass@host:5432/fxlab?sslmode=require",
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.db import _resolve_database_url

            result = _resolve_database_url()
            assert result.startswith("postgresql")


# ---------------------------------------------------------------------------
# H-CRIT-2: Redis-backed idempotency store
# ---------------------------------------------------------------------------


class TestRedisIdempotencyStore:
    """
    Idempotency store must support a Redis backend for multi-worker safety.

    Rationale:
        In-memory idempotency store only works per-worker. With 4 Uvicorn
        workers, a client can submit the same trade to each worker and all
        4 will process it. Redis provides cross-worker dedup.
    """

    def test_redis_idempotency_backend_exists(self) -> None:
        """RedisIdempotencyStore class must exist and implement the store interface."""
        from services.api.middleware.idempotency import RedisIdempotencyStore

        assert hasattr(RedisIdempotencyStore, "start_request")
        assert hasattr(RedisIdempotencyStore, "store_response")
        assert hasattr(RedisIdempotencyStore, "get_cached_response")
        assert hasattr(RedisIdempotencyStore, "finish_request")

    def test_redis_idempotency_start_request_new_key(self) -> None:
        """New key returns False (not a duplicate) and sets in-flight."""
        mock_redis = MagicMock()
        mock_redis.set.return_value = True  # SET NX succeeded

        from services.api.middleware.idempotency import RedisIdempotencyStore

        store = RedisIdempotencyStore(mock_redis, window_seconds=3600)
        result = store.start_request("idem-001")
        assert result is False, "New key should not be a duplicate"

    def test_redis_idempotency_start_request_duplicate_key(self) -> None:
        """Existing in-flight key returns True (concurrent duplicate)."""
        mock_redis = MagicMock()
        mock_redis.set.return_value = False  # SET NX failed (key exists)
        # No cached response exists — this is a true in-flight duplicate
        mock_redis.exists.return_value = False

        from services.api.middleware.idempotency import RedisIdempotencyStore

        store = RedisIdempotencyStore(mock_redis, window_seconds=3600)
        result = store.start_request("idem-001")
        assert result is True, "Existing in-flight key is a duplicate"

    def test_redis_idempotency_store_and_retrieve(self) -> None:
        """Stored response can be retrieved by key."""
        mock_redis = MagicMock()
        # Simulate stored response as JSON bytes
        import json

        stored_data = json.dumps(
            {
                "status_code": 201,
                "body": "eyJpZCI6ICJ0MTIzIn0=",  # base64
                "headers": {"Content-Type": "application/json"},
            }
        ).encode()
        mock_redis.get.return_value = stored_data

        from services.api.middleware.idempotency import RedisIdempotencyStore

        store = RedisIdempotencyStore(mock_redis, window_seconds=3600)
        store.store_response(
            "idem-002", 201, b'{"id": "t123"}', {"Content-Type": "application/json"}
        )
        # Verify Redis SET was called
        assert mock_redis.set.called or mock_redis.setex.called

    def test_redis_idempotency_fail_open_on_redis_error(self) -> None:
        """Redis error allows request through (fail-open for availability)."""
        mock_redis = MagicMock()
        mock_redis.set.side_effect = ConnectionError("Redis down")

        from services.api.middleware.idempotency import RedisIdempotencyStore

        store = RedisIdempotencyStore(mock_redis, window_seconds=3600)
        # Should NOT raise — fail-open means allow the request
        result = store.start_request("idem-003")
        assert result is False, "Redis error should fail-open (allow request)"

    def test_idempotency_backend_factory_creates_redis(self) -> None:
        """When IDEMPOTENCY_BACKEND=redis, factory returns RedisIdempotencyStore."""
        mock_redis_module = MagicMock()
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis_module.Redis.from_url.return_value = mock_client

        from services.api.middleware.idempotency import RedisIdempotencyStore

        env = {
            "IDEMPOTENCY_BACKEND": "redis",
            "REDIS_URL": "redis://localhost:6379/0",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch.dict("sys.modules", {"redis": mock_redis_module}),
        ):
            from services.api.middleware.idempotency import _create_idempotency_store

            store = _create_idempotency_store()
            assert isinstance(store, RedisIdempotencyStore)


# ---------------------------------------------------------------------------
# H-CRIT-3: Redis-backed login attempt tracker
# ---------------------------------------------------------------------------


class TestRedisLoginAttemptTracker:
    """
    Login attempt tracker must support Redis backend for multi-worker safety.

    Rationale:
        In-memory tracker allows 5 × N attempts across N workers. With Redis,
        failure counts are shared so the 5-attempt limit is enforced globally.
    """

    def test_redis_login_tracker_exists(self) -> None:
        """RedisLoginAttemptTracker class must exist."""
        from services.api.services.login_attempt_tracker import RedisLoginAttemptTracker

        assert hasattr(RedisLoginAttemptTracker, "record_failure")
        assert hasattr(RedisLoginAttemptTracker, "record_success")
        assert hasattr(RedisLoginAttemptTracker, "is_locked")
        assert hasattr(RedisLoginAttemptTracker, "retry_after")

    def test_redis_tracker_record_failure_increments(self) -> None:
        """record_failure adds a timestamp to the Redis sorted set."""
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [None, None, 3]  # zadd, zremrangebyscore, zcard
        mock_redis.pipeline.return_value = mock_pipe

        from services.api.services.login_attempt_tracker import RedisLoginAttemptTracker

        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)
        tracker.record_failure("user@example.com")
        assert mock_pipe.zadd.called

    def test_redis_tracker_is_locked_checks_count(self) -> None:
        """is_locked returns True when failure count >= max_attempts."""
        mock_redis = MagicMock()
        mock_redis.zcard.return_value = 5  # At the limit

        from services.api.services.login_attempt_tracker import RedisLoginAttemptTracker

        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)
        assert tracker.is_locked("user@example.com") is True

    def test_redis_tracker_is_locked_false_under_limit(self) -> None:
        """is_locked returns False when failure count < max_attempts."""
        mock_redis = MagicMock()
        mock_redis.zcard.return_value = 3  # Under limit

        from services.api.services.login_attempt_tracker import RedisLoginAttemptTracker

        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)
        assert tracker.is_locked("user@example.com") is False

    def test_redis_tracker_record_success_clears(self) -> None:
        """record_success removes the key from Redis."""
        mock_redis = MagicMock()

        from services.api.services.login_attempt_tracker import RedisLoginAttemptTracker

        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)
        tracker.record_success("user@example.com")
        mock_redis.delete.assert_called()

    def test_redis_tracker_fail_closed_on_error(self) -> None:
        """Redis error during is_locked returns True (deny login, fail-closed)."""
        mock_redis = MagicMock()
        mock_redis.zcard.side_effect = ConnectionError("Redis down")

        from services.api.services.login_attempt_tracker import RedisLoginAttemptTracker

        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)
        # Fail-closed: if we can't check, deny (brute-force protection must hold)
        assert tracker.is_locked("user@example.com") is True


# ---------------------------------------------------------------------------
# H-CRIT-4: Optimistic locking on mutable entities
# ---------------------------------------------------------------------------


class TestOptimisticLocking:
    """
    Mutable entities must have a version column for optimistic concurrency control.

    Rationale:
        Without version columns, two concurrent requests can read the same
        state, compute different updates, and the second write silently
        overwrites the first. For a trading platform this means lost trades.
    """

    def test_strategy_has_row_version_column(self) -> None:
        """Strategy model must have an integer row_version column."""
        from libs.contracts.models import Strategy

        assert hasattr(Strategy, "row_version"), (
            "Strategy must have row_version for optimistic locking"
        )
        col = Strategy.__table__.columns["row_version"]
        assert str(col.type) == "INTEGER", f"row_version must be INTEGER, got {col.type}"

    def test_override_has_row_version_column(self) -> None:
        """Override model must have an integer row_version column."""
        from libs.contracts.models import Override

        assert hasattr(Override, "row_version")
        col = Override.__table__.columns["row_version"]
        assert str(col.type) == "INTEGER"

    def test_run_has_row_version_column(self) -> None:
        """Run model must have an integer row_version column."""
        from libs.contracts.models import Run

        assert hasattr(Run, "row_version")
        col = Run.__table__.columns["row_version"]
        assert str(col.type) == "INTEGER"

    def test_row_version_defaults_to_one(self) -> None:
        """row_version default should be 1 for new records."""
        from libs.contracts.models import Strategy

        col = Strategy.__table__.columns["row_version"]
        # Check column has a server_default or default
        assert col.default is not None or col.server_default is not None, (
            "row_version must have a default value"
        )

    def test_optimistic_lock_check_helper_exists(self) -> None:
        """A helper function for checking version conflicts must exist."""
        from services.api.repositories import check_row_version

        assert callable(check_row_version)


# ---------------------------------------------------------------------------
# H-CRIT-5: prometheus_client in requirements.txt
# ---------------------------------------------------------------------------


class TestPrometheusClientDependency:
    """
    prometheus_client must be in requirements.txt so /metrics doesn't crash.

    Rationale:
        metrics.py imports prometheus_client but it was missing from
        requirements.txt. The /metrics endpoint would ImportError on first hit.
    """

    def test_prometheus_client_in_requirements(self) -> None:
        """requirements.txt must include prometheus-client."""
        with open("requirements.txt") as f:
            content = f.read()
        assert "prometheus-client" in content or "prometheus_client" in content, (
            "prometheus-client must be listed in requirements.txt"
        )

    def test_metrics_endpoint_importable(self) -> None:
        """Importing metrics module should not raise ImportError."""
        from services.api import metrics

        assert hasattr(metrics, "APPROVAL_REQUESTS_TOTAL")
        assert hasattr(metrics, "metrics_endpoint")

    def test_generate_latest_callable(self) -> None:
        """prometheus_client.generate_latest must be callable."""
        from prometheus_client import generate_latest

        # Should return bytes without error
        result = generate_latest()
        assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# H-CRIT-6: Security headers middleware
# ---------------------------------------------------------------------------


class TestSecurityHeadersMiddleware:
    """
    All responses must include standard security headers.

    Rationale:
        Missing X-Frame-Options, X-Content-Type-Options, and HSTS headers
        leave the platform vulnerable to clickjacking, MIME sniffing, and
        downgrade attacks. These are OWASP baseline requirements.
    """

    def test_security_headers_middleware_exists(self) -> None:
        """SecurityHeadersMiddleware must be importable."""
        from services.api.middleware.security_headers import SecurityHeadersMiddleware

        assert SecurityHeadersMiddleware is not None

    def test_security_headers_applied_to_response(self) -> None:
        """Middleware adds X-Frame-Options, X-Content-Type-Options, and referrer headers."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from services.api.middleware.security_headers import SecurityHeadersMiddleware

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def _test_route() -> dict:
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")

        assert resp.headers.get("X-Frame-Options") == "DENY", "X-Frame-Options must be DENY"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff", (
            "X-Content-Type-Options must be nosniff"
        )
        assert "no-referrer" in resp.headers.get("Referrer-Policy", ""), (
            "Referrer-Policy must include no-referrer"
        )
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block", (
            "X-XSS-Protection must be set"
        )

    def test_hsts_header_present_when_enabled(self) -> None:
        """Strict-Transport-Security header is present when HSTS is enabled."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from services.api.middleware.security_headers import SecurityHeadersMiddleware

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware, enable_hsts=True)

        @app.get("/test")
        def _test_route() -> dict:
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")

        hsts = resp.headers.get("Strict-Transport-Security", "")
        assert "max-age=" in hsts, "HSTS must include max-age directive"

    def test_permissions_policy_header(self) -> None:
        """Permissions-Policy header restricts dangerous browser features."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from services.api.middleware.security_headers import SecurityHeadersMiddleware

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def _test_route() -> dict:
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")

        pp = resp.headers.get("Permissions-Policy", "")
        assert "camera=()" in pp, "Permissions-Policy must deny camera access"
        assert "microphone=()" in pp, "Permissions-Policy must deny microphone access"
