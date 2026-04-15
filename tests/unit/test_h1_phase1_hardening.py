"""
Phase 1 hardening tests — H1.6 through H1.9.

Verifies production-safety requirements identified in the enterprise
hardening audit (April 4, 2026):

  H1.6 — Rate limiter Redis failure returns DENY (not ALLOW).
  H1.7 — Production startup rejects DATABASE_URL without sslmode.
  H1.8 — PostgreSQL connect_args include statement_timeout.
  H1.9 — Default pool size increased to 20 (from 5).

Dependencies:
    - services.api.middleware.rate_limit
    - services.api.db
    - services.api.main (_validate_startup_secrets)

Example:
    pytest tests/unit/test_h1_phase1_hardening.py -v
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# H1.6 — Rate limiter MUST deny on Redis failure (fail-closed)
# ---------------------------------------------------------------------------


class TestRedisFailClosed:
    """
    Redis rate limiter must DENY requests when Redis is unreachable.

    Rationale:
        If Redis goes down and the limiter degrades to unlimited (permissive),
        an attacker gets unlimited access to /auth/token (brute-force) and
        all governance endpoints. For a financial trading platform handling
        real money, fail-closed is the only safe option.

    CLAUDE.md §9: Transient failures → retry with backoff.
                  Rate-limit failure is NOT transient from the client's
                  perspective — it's a service-protection mechanism.
    """

    def test_redis_error_returns_deny_not_allow(self) -> None:
        """
        When Redis pipeline.execute() raises, is_allowed MUST return
        (False, retry_after > 0) — NOT (True, 0).

        This is the critical behavioral change from permissive to restrictive.
        """
        from services.api.middleware.rate_limit import RedisRateLimitBackend

        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.side_effect = ConnectionError("Redis down")
        mock_redis.pipeline.return_value = mock_pipe
        backend = RedisRateLimitBackend(mock_redis)

        allowed, retry = backend.is_allowed("test:key", limit=10)

        assert allowed is False, (
            "Rate limiter must DENY on Redis failure (fail-closed). "
            "Permissive fallback allows unlimited requests including "
            "brute-force on /auth/token."
        )
        assert retry > 0, "retry_after must be positive so clients know when to retry."

    def test_redis_timeout_returns_deny(self) -> None:
        """Redis timeout (not just ConnectionError) must also deny."""
        from services.api.middleware.rate_limit import RedisRateLimitBackend

        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.side_effect = TimeoutError("Redis operation timed out")
        mock_redis.pipeline.return_value = mock_pipe
        backend = RedisRateLimitBackend(mock_redis)

        allowed, retry = backend.is_allowed("test:key", limit=10)

        assert allowed is False
        assert retry > 0

    def test_redis_generic_exception_returns_deny(self) -> None:
        """Any Exception subclass during Redis operation must deny."""
        from services.api.middleware.rate_limit import RedisRateLimitBackend

        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.side_effect = RuntimeError("Unexpected Redis error")
        mock_redis.pipeline.return_value = mock_pipe
        backend = RedisRateLimitBackend(mock_redis)

        allowed, retry = backend.is_allowed("test:key", limit=10)

        assert allowed is False
        assert retry > 0

    def test_redis_error_retry_after_is_reasonable(self) -> None:
        """retry_after on Redis error should be a short backoff (1-60s)."""
        from services.api.middleware.rate_limit import RedisRateLimitBackend

        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.side_effect = ConnectionError("Redis down")
        mock_redis.pipeline.return_value = mock_pipe
        backend = RedisRateLimitBackend(mock_redis)

        _, retry = backend.is_allowed("test:key", limit=10)

        assert 1 <= retry <= 60, f"retry_after should be 1-60 seconds, got {retry}"


# ---------------------------------------------------------------------------
# H1.7 — Production startup MUST reject DATABASE_URL without sslmode
# ---------------------------------------------------------------------------


class TestSSLEnforcement:
    """
    Production startup must block if DATABASE_URL is PostgreSQL without sslmode.

    Rationale:
        Without SSL, credentials and trading data travel in plaintext.
        Current code logs a warning but continues startup. For production,
        this must be a hard failure.
    """

    def test_production_rejects_postgresql_without_sslmode(self) -> None:
        """
        _validate_startup_secrets must raise RuntimeError when
        ENVIRONMENT=production and DATABASE_URL is PostgreSQL without sslmode.
        """
        from services.api.main import _validate_startup_secrets

        with (
            patch.dict(
                os.environ,
                {
                    "ENVIRONMENT": "production",
                    "DATABASE_URL": "postgresql://u:p@host:5432/db",
                    "JWT_SECRET_KEY": "a" * 64,
                },
                clear=False,
            ),
            pytest.raises(RuntimeError, match="sslmode"),
        ):
            _validate_startup_secrets()

    def test_production_accepts_postgresql_with_sslmode_require(self) -> None:
        """PostgreSQL with sslmode=require should pass validation."""
        from services.api.main import _validate_startup_secrets

        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "DATABASE_URL": "postgresql://u:p@host:5432/db?sslmode=require",
                "JWT_SECRET_KEY": "a" * 64,
            },
            clear=False,
        ):
            # Should not raise
            _validate_startup_secrets()

    def test_production_accepts_postgresql_with_sslmode_verify_full(self) -> None:
        """PostgreSQL with sslmode=verify-full should pass validation."""
        from services.api.main import _validate_startup_secrets

        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "DATABASE_URL": "postgresql://u:p@host:5432/db?sslmode=verify-full",
                "JWT_SECRET_KEY": "a" * 64,
            },
            clear=False,
        ):
            _validate_startup_secrets()

    def test_test_environment_allows_no_sslmode(self) -> None:
        """Non-production environments should not enforce sslmode."""
        from services.api.main import _validate_startup_secrets

        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "test",
                "DATABASE_URL": "postgresql://u:p@host:5432/db",
            },
            clear=False,
        ):
            # Should not raise
            _validate_startup_secrets()

    def test_sqlite_url_not_affected_by_ssl_check(self) -> None:
        """SQLite URLs should not trigger SSL enforcement."""
        from services.api.main import _validate_startup_secrets

        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "DATABASE_URL": "sqlite:///./test.db",
                "JWT_SECRET_KEY": "a" * 64,
            },
            clear=False,
        ):
            _validate_startup_secrets()


# ---------------------------------------------------------------------------
# H1.8 — PostgreSQL connect_args MUST include statement_timeout
# ---------------------------------------------------------------------------


class TestStatementTimeout:
    """
    PostgreSQL connections must have a statement_timeout to prevent
    runaway queries from hanging workers indefinitely.

    Rationale:
        A slow query (e.g., full table scan on large audit_events) can
        hold a connection pool slot for minutes, starving other requests.
        statement_timeout terminates queries exceeding the threshold.
    """

    def test_postgresql_pool_kwargs_include_statement_timeout(self) -> None:
        """
        _get_pool_kwargs for PostgreSQL must return connect_args with
        statement_timeout in the options string.
        """
        from services.api.db import _get_pool_kwargs

        result = _get_pool_kwargs("postgresql://u:p@host:5432/db")

        assert "connect_args" in result, (
            "PostgreSQL pool kwargs must include connect_args with statement_timeout"
        )
        options = result["connect_args"].get("options", "")
        assert "statement_timeout" in options, (
            f"connect_args options must include statement_timeout, got: {options}"
        )

    def test_statement_timeout_default_is_30_seconds(self) -> None:
        """Default statement_timeout should be 30000ms (30 seconds)."""
        from services.api.db import _get_pool_kwargs

        result = _get_pool_kwargs("postgresql://u:p@host:5432/db")

        options = result.get("connect_args", {}).get("options", "")
        assert "statement_timeout=30000" in options, (
            f"Default statement_timeout should be 30000ms, got: {options}"
        )

    def test_statement_timeout_configurable_via_env(self) -> None:
        """DB_STATEMENT_TIMEOUT_MS env var overrides the default."""
        with patch.dict(os.environ, {"DB_STATEMENT_TIMEOUT_MS": "60000"}, clear=False):
            from services.api.db import _get_pool_kwargs

            result = _get_pool_kwargs("postgresql://u:p@host:5432/db")

        options = result.get("connect_args", {}).get("options", "")
        assert "statement_timeout=60000" in options, (
            f"statement_timeout should be 60000 from env, got: {options}"
        )

    def test_sqlite_does_not_get_statement_timeout(self) -> None:
        """SQLite URLs should not have connect_args with statement_timeout."""
        from services.api.db import _get_pool_kwargs

        result = _get_pool_kwargs("sqlite:///./test.db")

        # SQLite returns StaticPool config, should not have connect_args
        assert "connect_args" not in result


# ---------------------------------------------------------------------------
# H1.9 — Default pool size increased from 5 to 20
# ---------------------------------------------------------------------------


class TestIncreasedPoolDefaults:
    """
    Default connection pool must support multi-worker production deployments.

    Rationale:
        With pool_size=5 and max_overflow=10, only 15 total connections
        are available across 2 Uvicorn workers. Under spike traffic,
        requests queue for up to 30 seconds. Increasing to pool_size=20
        and max_overflow=20 provides 40 total connections.
    """

    def test_default_pool_size_is_20(self) -> None:
        """Default pool_size must be 20 (up from 5)."""
        from services.api.db import _DEFAULT_POOL_SIZE

        assert _DEFAULT_POOL_SIZE == 20, (
            f"Default pool_size must be 20 for multi-worker production, got {_DEFAULT_POOL_SIZE}"
        )

    def test_default_pool_overflow_is_20(self) -> None:
        """Default max_overflow must be 20 (up from 10)."""
        from services.api.db import _DEFAULT_POOL_OVERFLOW

        assert _DEFAULT_POOL_OVERFLOW == 20, (
            f"Default max_overflow must be 20, got {_DEFAULT_POOL_OVERFLOW}"
        )

    def test_pool_kwargs_reflect_new_defaults(self) -> None:
        """_get_pool_kwargs with no env vars should use new defaults."""
        env_clean = {k: v for k, v in os.environ.items() if not k.startswith("DB_POOL")}
        with patch.dict(os.environ, env_clean, clear=True):
            from services.api.db import _get_pool_kwargs

            result = _get_pool_kwargs("postgresql://u:p@host:5432/db")

        assert result["pool_size"] == 20
        assert result["max_overflow"] == 20
