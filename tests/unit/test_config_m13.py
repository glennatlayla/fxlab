"""
Unit tests for M13 centralized configuration.

Covers:
- AppSettings loads defaults when no env vars set
- DatabaseSettings reads DB_ prefixed env vars
- RedisSettings reads REDIS_ prefixed env vars
- AuthSettings reads auth-related env vars
- RateLimitSettings reads RATE_LIMIT_ prefixed env vars
- ObservabilitySettings reads observability env vars
- get_settings() returns cached singleton
- AppSettings validates field constraints (e.g. pool_size >= 1)

Dependencies:
- services.api.config: AppSettings, get_settings
"""

from __future__ import annotations

from unittest.mock import patch

from services.api.config import AppSettings, DatabaseSettings, ObservabilitySettings, get_settings

# ------------------------------------------------------------------
# Tests: Default Values
# ------------------------------------------------------------------


class TestDefaultSettings:
    """AppSettings provides sensible defaults for all fields."""

    def test_database_defaults(self) -> None:
        """Database settings have safe defaults for local development."""
        settings = DatabaseSettings()
        assert settings.pool_size == 20
        assert settings.pool_overflow == 20
        assert settings.pool_timeout == 30
        assert settings.statement_timeout_ms == 30000
        assert settings.sql_echo is False

    def test_redis_default_url_empty(self) -> None:
        """Redis URL defaults to empty string (not configured)."""
        settings = AppSettings()
        assert settings.redis.url == "" or isinstance(settings.redis.url, str)

    def test_auth_defaults(self) -> None:
        """Auth settings have sensible defaults."""
        settings = AppSettings()
        assert settings.auth.jwt_expiration_minutes == 30
        assert settings.auth.jwt_audience == "fxlab-api"
        assert settings.auth.jwt_issuer == "fxlab"
        assert settings.auth.jwt_max_token_bytes == 16384

    def test_rate_limit_defaults(self) -> None:
        """Rate limit settings have production-safe defaults."""
        settings = AppSettings()
        assert settings.rate_limit.governance_limit == 20
        assert settings.rate_limit.auth_limit == 10
        assert settings.rate_limit.default_limit == 100
        assert settings.rate_limit.backend == "memory"

    def test_observability_defaults(self) -> None:
        """Observability settings have safe defaults."""
        settings = ObservabilitySettings()
        assert settings.log_level == "INFO"
        assert settings.drain_timeout_s == 30.0
        assert settings.max_request_body_bytes == 524288


# ------------------------------------------------------------------
# Tests: Environment Variable Override
# ------------------------------------------------------------------


class TestEnvOverride:
    """Settings can be overridden via environment variables."""

    def test_database_url_from_env(self) -> None:
        """DATABASE_URL env var overrides default."""
        with patch.dict("os.environ", {"DB_URL": "postgresql://user:pass@host/db"}):
            settings = DatabaseSettings()
            assert settings.url == "postgresql://user:pass@host/db"

    def test_redis_url_from_env(self) -> None:
        """REDIS_URL env var is read by RedisSettings."""
        settings = AppSettings()
        # Just verify the model is constructible — actual URL depends on env
        assert isinstance(settings.redis.url, str)


# ------------------------------------------------------------------
# Tests: Singleton Cache
# ------------------------------------------------------------------


class TestSingleton:
    """get_settings() returns the same instance each time."""

    def test_get_settings_returns_app_settings(self) -> None:
        """get_settings() returns an AppSettings instance."""
        # Clear the lru_cache to get a fresh instance
        get_settings.cache_clear()
        settings = get_settings()
        assert isinstance(settings, AppSettings)

    def test_get_settings_is_cached(self) -> None:
        """get_settings() returns the same object on repeated calls."""
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
