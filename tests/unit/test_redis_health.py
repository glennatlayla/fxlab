"""
Unit tests for Redis health check (redis_health.py).

Tests the health check utility that validates Redis availability and
configuration at application startup.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from libs.contracts.errors import ConfigError
from services.api.infrastructure.redis_health import (
    _parse_redis_version,
    _strip_credentials,
    verify_redis_connection,
)

# ---------------------------------------------------------------------------
# _parse_redis_version() tests
# ---------------------------------------------------------------------------


class TestParseRedisVersion:
    """Tests for version string parsing utility."""

    def test_parse_redis_version_standard_format(self) -> None:
        """Parse standard semver Redis version string."""
        result = _parse_redis_version("7.0.0")
        assert result == (7, 0, 0)

    def test_parse_redis_version_with_rc_suffix(self) -> None:
        """Parse version string with release candidate suffix."""
        result = _parse_redis_version("6.2.1-rc1")
        assert result == (6, 2, 1)

    def test_parse_redis_version_with_alpha_suffix(self) -> None:
        """Parse version string with alpha suffix."""
        result = _parse_redis_version("7.0.0-alpha1")
        assert result == (7, 0, 0)

    def test_parse_redis_version_with_multiple_suffixes(self) -> None:
        """Parse version string with complex suffix."""
        result = _parse_redis_version("6.2.1-rc1-patch1")
        assert result == (6, 2, 1)

    def test_parse_redis_version_raises_on_invalid_format(self) -> None:
        """Raise ValueError on unparseable version string."""
        with pytest.raises(ValueError, match="Cannot parse"):
            _parse_redis_version("invalid")

    def test_parse_redis_version_raises_on_missing_parts(self) -> None:
        """Raise ValueError when version has too few parts."""
        with pytest.raises(ValueError, match="Cannot parse"):
            _parse_redis_version("7.0")

    def test_parse_redis_version_comparison(self) -> None:
        """Version tuples can be compared correctly."""
        v6_2 = _parse_redis_version("6.2.0")
        v7_0 = _parse_redis_version("7.0.0")
        v6_0 = _parse_redis_version("6.0.0")

        assert v6_0 < v6_2 < v7_0
        assert v7_0 > v6_2
        assert v6_0 <= v6_2


# ---------------------------------------------------------------------------
# _strip_credentials() tests
# ---------------------------------------------------------------------------


class TestStripCredentials:
    """Tests for URL credential stripping utility."""

    def test_strip_credentials_with_password_only(self) -> None:
        """Strip password from redis://password@host URL."""
        url = "redis://mypassword@redis:6379/0"
        result = _strip_credentials(url)
        assert result == "redis://...@redis:6379/0"
        assert "mypassword" not in result

    def test_strip_credentials_with_user_and_password(self) -> None:
        """Strip user and password from redis://user:pass@host URL."""
        url = "redis://myuser:mypassword@redis:6379/0"
        result = _strip_credentials(url)
        assert result == "redis://...@redis:6379/0"
        assert "myuser" not in result
        assert "mypassword" not in result

    def test_strip_credentials_with_rediss_scheme(self) -> None:
        """Strip credentials from rediss:// (TLS) URL."""
        url = "rediss://secret@redis-cluster:6380/0"
        result = _strip_credentials(url)
        assert result == "rediss://...@redis-cluster:6380/0"

    def test_strip_credentials_no_credentials(self) -> None:
        """Leave URL unchanged if no credentials present."""
        url = "redis://redis:6379/0"
        result = _strip_credentials(url)
        assert result == "redis://redis:6379/0"

    def test_strip_credentials_preserves_port_and_db(self) -> None:
        """Preserve port and database selection in URL."""
        url = "redis://pass@redis:6380/5"
        result = _strip_credentials(url)
        assert result == "redis://...@redis:6380/5"


# ---------------------------------------------------------------------------
# verify_redis_connection() tests
# ---------------------------------------------------------------------------


class TestVerifyRedisConnectionSuccess:
    """Happy path: Redis is available and healthy."""

    def test_verify_redis_connection_success(self) -> None:
        """
        Redis connection, PING, and config checks all succeed.
        """
        # Mock Redis client
        mock_client = MagicMock()

        # Mock PING success
        mock_client.ping.return_value = True

        # Mock INFO response with version 7.0.0
        mock_client.info.return_value = {"redis_version": "7.0.0"}

        # Mock CONFIG GET response
        mock_client.config_get.return_value = {"maxmemory-policy": "allkeys-lru"}

        with patch("redis.Redis.from_url", return_value=mock_client):
            # Should not raise
            verify_redis_connection("redis://localhost:6379/0", timeout_seconds=5.0)

        # Verify connection was attempted
        mock_client.ping.assert_called_once()
        mock_client.close.assert_called_once()

    def test_verify_redis_connection_closes_client_on_success(self) -> None:
        """
        Connection is properly closed after successful check.
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.info.return_value = {"redis_version": "7.0.0"}
        mock_client.config_get.return_value = {"maxmemory-policy": "allkeys-lru"}

        with patch("redis.Redis.from_url", return_value=mock_client):
            verify_redis_connection("redis://localhost:6379/0")

        # Close must be called
        mock_client.close.assert_called_once()


class TestVerifyRedisConnectionFailures:
    """Error cases: Redis unavailable, old version, or misconfigured."""

    def test_verify_redis_connection_import_error_raises_config_error(self) -> None:
        """
        If redis library is not installed, raise ConfigError.
        """
        # Simulate ImportError when redis is not available
        with patch.dict(sys.modules, {"redis": None}):
            with pytest.raises(ConfigError, match="redis library is not installed"):
                verify_redis_connection("redis://localhost:6379/0")

    def test_verify_redis_connection_connection_error_raises_config_error(
        self,
    ) -> None:
        """
        If Redis is unreachable, raise ConfigError with connection details.
        """
        mock_client = MagicMock()

        # Mock connection failure
        mock_client.ping.side_effect = Exception("Connection refused")

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError, match="Cannot connect to Redis"):
                verify_redis_connection("redis://localhost:6379/0")

        # Client should still be closed
        mock_client.close.assert_called_once()

    def test_verify_redis_connection_timeout_raises_config_error(self) -> None:
        """
        If Redis connection times out, raise ConfigError with timeout details.
        """
        mock_client = MagicMock()

        # Mock timeout error
        import redis

        mock_client.ping.side_effect = redis.TimeoutError("Timeout")

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError, match="timed out"):
                verify_redis_connection("redis://localhost:6379/0", timeout_seconds=3.0)

        mock_client.close.assert_called_once()

    def test_verify_redis_connection_ping_returns_false_raises_config_error(
        self,
    ) -> None:
        """
        If PING does not return True, raise ConfigError.
        """
        mock_client = MagicMock()

        # Mock PING returning unexpected value
        mock_client.ping.return_value = False

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError, match="PING failed"):
                verify_redis_connection("redis://localhost:6379/0")

        mock_client.close.assert_called_once()

    def test_verify_redis_connection_old_version_raises_config_error(
        self,
    ) -> None:
        """
        If Redis version is < 6.0, raise ConfigError.
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True

        # Mock old Redis version
        mock_client.info.return_value = {"redis_version": "5.0.0"}

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError, match="too old"):
                verify_redis_connection("redis://localhost:6379/0")

        mock_client.close.assert_called_once()

    def test_verify_redis_connection_version_check_error_raises_config_error(
        self,
    ) -> None:
        """
        If version cannot be determined, raise ConfigError.
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True

        # Mock INFO returning invalid version
        mock_client.info.return_value = {"redis_version": "invalid_format"}

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError, match="Cannot determine Redis version"):
                verify_redis_connection("redis://localhost:6379/0")

        mock_client.close.assert_called_once()

    def test_verify_redis_connection_version_missing_raises_config_error(
        self,
    ) -> None:
        """
        If redis_version key is missing from INFO, raise ConfigError.
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True

        # Mock INFO with missing version
        mock_client.info.return_value = {}

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError, match="Cannot determine Redis version"):
                verify_redis_connection("redis://localhost:6379/0")

        mock_client.close.assert_called_once()

    def test_verify_redis_connection_closes_client_on_error(self) -> None:
        """
        Connection is properly closed even when check fails.
        """
        mock_client = MagicMock()
        mock_client.ping.side_effect = Exception("Connection failed")

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError):
                verify_redis_connection("redis://localhost:6379/0")

        # Close must still be called
        mock_client.close.assert_called_once()


class TestVerifyRedisConnectionConfigWarnings:
    """Config warnings: maxmemory-policy not optimal but startup succeeds."""

    def test_verify_redis_connection_maxmemory_policy_missing_allows_startup(
        self,
    ) -> None:
        """
        If maxmemory-policy is not set, log warning but allow startup.
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.info.return_value = {"redis_version": "7.0.0"}

        # Mock CONFIG GET with missing/empty policy
        mock_client.config_get.return_value = {"maxmemory-policy": ""}

        with patch("redis.Redis.from_url", return_value=mock_client):
            # Should NOT raise — only warns
            verify_redis_connection("redis://localhost:6379/0")

        mock_client.close.assert_called_once()

    def test_verify_redis_connection_maxmemory_policy_noeviction_allows_startup(
        self,
    ) -> None:
        """
        If maxmemory-policy is 'noeviction', log warning but allow startup.
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.info.return_value = {"redis_version": "7.0.0"}

        # Mock CONFIG GET with noeviction policy
        mock_client.config_get.return_value = {"maxmemory-policy": "noeviction"}

        with patch("redis.Redis.from_url", return_value=mock_client):
            # Should NOT raise — only warns
            verify_redis_connection("redis://localhost:6379/0")

        mock_client.close.assert_called_once()

    def test_verify_redis_connection_config_check_error_allows_startup(
        self,
    ) -> None:
        """
        If config check fails (advisory), log warning but allow startup.
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.info.return_value = {"redis_version": "7.0.0"}

        # Mock CONFIG GET failure
        mock_client.config_get.side_effect = Exception("config command failed")

        with patch("redis.Redis.from_url", return_value=mock_client):
            # Should NOT raise — only warns
            verify_redis_connection("redis://localhost:6379/0")

        mock_client.close.assert_called_once()


class TestVerifyRedisConnectionIntegration:
    """Integration-like tests (with mocks) for startup scenarios."""

    def test_verify_redis_connection_with_credentials_in_url(self) -> None:
        """
        Verify connection works with credentials in URL (redis-py handles).
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.info.return_value = {"redis_version": "7.0.0"}
        mock_client.config_get.return_value = {"maxmemory-policy": "allkeys-lru"}

        with patch("redis.Redis.from_url", return_value=mock_client) as mock_from_url:
            # Should handle URL with credentials
            verify_redis_connection("redis://user:pass@redis:6379/0")

            # Verify Redis.from_url was called with the URL
            mock_from_url.assert_called_once()
            call_args = mock_from_url.call_args
            assert call_args[0][0] == "redis://user:pass@redis:6379/0"

    def test_verify_redis_connection_with_rediss_tls(self) -> None:
        """
        Verify connection works with rediss:// (TLS) scheme.
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.info.return_value = {"redis_version": "7.0.0"}
        mock_client.config_get.return_value = {"maxmemory-policy": "allkeys-lfu"}

        with patch("redis.Redis.from_url", return_value=mock_client) as mock_from_url:
            # Should handle rediss:// (TLS)
            verify_redis_connection("rediss://redis-cluster:6380/0")

            mock_from_url.assert_called_once()
            call_args = mock_from_url.call_args
            assert call_args[0][0] == "rediss://redis-cluster:6380/0"

    def test_verify_redis_connection_timeout_parameter_passed(self) -> None:
        """
        Verify timeout_seconds parameter is passed to Redis client.
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.info.return_value = {"redis_version": "7.0.0"}
        mock_client.config_get.return_value = {"maxmemory-policy": "allkeys-lru"}

        with patch("redis.Redis.from_url", return_value=mock_client) as mock_from_url:
            verify_redis_connection("redis://localhost:6379/0", timeout_seconds=10.0)

            # Verify socket_connect_timeout was set
            call_kwargs = mock_from_url.call_args[1]
            assert call_kwargs["socket_connect_timeout"] == 10.0
