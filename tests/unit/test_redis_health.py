"""
Unit tests for Redis health check (redis_health.py).

Tests the health check utility that validates Redis availability and
configuration at application startup.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import errno
import socket
import sys
from unittest.mock import MagicMock, patch

import pytest

from libs.contracts.errors import ConfigError
from services.api.infrastructure.redis_health import (
    _build_keepalive_options,
    _classify_connection_error,
    _compute_backoff_seconds,
    _parse_redis_version,
    _strip_credentials,
    verify_redis_connection,
)


@pytest.fixture(autouse=True)
def _no_real_sleep_during_redis_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Replace time.sleep used by the redis_health retry loop with a no-op
    so the unit-test suite does not incur the (1s + 2s + 4s + 8s) backoff
    for each transient-failure test path.

    Tests that want to assert on the actual sleep schedule pass their own
    ``sleep=...`` callable, which takes precedence over this monkeypatch.
    """
    monkeypatch.setattr(
        "services.api.infrastructure.redis_health.time.sleep",
        lambda _seconds: None,
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
            with pytest.raises(ConfigError, match="Redis health check failed"):
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


# ---------------------------------------------------------------------------
# Socket keepalive option tests — regression guard for minitux install failure
# ---------------------------------------------------------------------------
#
# Background:
# On 2026-04-15 the minitux install (Linux kernel 6.17) failed because the
# previous implementation passed socket_keepalive_options={1: 1, 2: 1} to
# redis-py: magic-integer keys and a 1-second value that the kernel rejects
# with EINVAL (errno 22) inside setsockopt(IPPROTO_TCP, TCP_KEEPIDLE, 1).
#
# The fix replaces the hardcoded dict with _build_keepalive_options(), which
# uses socket.TCP_KEEPIDLE/INTVL/CNT constants with kernel-sane values
# (60s / 30s / 3 probes). These tests lock that contract in place.
#
# Linux-only: the socket.TCP_KEEPIDLE constant does not exist on macOS or
# Windows. _build_keepalive_options() returns an empty dict on those
# platforms so the module still imports cleanly in cross-platform CI —
# keepalive falls back to OS defaults without breaking startup.


class TestBuildKeepaliveOptions:
    """
    _build_keepalive_options() must return kernel-sane TCP keepalive values
    on Linux (where the constants exist) and an empty dict elsewhere.
    """

    @pytest.mark.skipif(
        not hasattr(socket, "TCP_KEEPIDLE"),
        reason="TCP_KEEPIDLE constants are Linux-only",
    )
    def test_build_keepalive_options_on_linux_uses_named_constants(self) -> None:
        """
        On Linux, keys MUST be the symbolic socket.TCP_KEEPIDLE/INTVL/CNT
        constants — not magic integers like {1: ..., 2: ...}.
        """
        opts = _build_keepalive_options()
        assert socket.TCP_KEEPIDLE in opts
        assert socket.TCP_KEEPINTVL in opts
        assert socket.TCP_KEEPCNT in opts

    @pytest.mark.skipif(
        not hasattr(socket, "TCP_KEEPIDLE"),
        reason="TCP_KEEPIDLE constants are Linux-only",
    )
    def test_build_keepalive_options_on_linux_uses_kernel_sane_values(self) -> None:
        """
        Values must be at or above kernel minimums so setsockopt does not
        reject them with EINVAL. 1-second values are known-bad on Linux 6.17
        in Docker's default network namespace.
        """
        opts = _build_keepalive_options()
        assert opts[socket.TCP_KEEPIDLE] == 60
        assert opts[socket.TCP_KEEPINTVL] == 30
        assert opts[socket.TCP_KEEPCNT] == 3

    def test_build_keepalive_options_time_values_meet_kernel_minimum(self) -> None:
        """
        Regression guard: TIME-based options (TCP_KEEPIDLE, TCP_KEEPINTVL)
        must be >= 10 seconds. The 2026-04-15 minitux install failed because
        those two options were set to 1 second each, which Linux kernel 6.17
        rejects with EINVAL inside setsockopt.

        TCP_KEEPCNT is a probe count, not a time — the kernel minimum for
        it is 1, so it is validated separately.
        """
        opts = _build_keepalive_options()
        time_based_keys: list[int] = []
        if hasattr(socket, "TCP_KEEPIDLE"):
            time_based_keys.append(socket.TCP_KEEPIDLE)
        if hasattr(socket, "TCP_KEEPINTVL"):
            time_based_keys.append(socket.TCP_KEEPINTVL)

        for key in time_based_keys:
            if key in opts:
                assert opts[key] >= 10, (
                    f"keepalive time option {key}={opts[key]} seconds is below "
                    f"the kernel minimum. Values < 10 seconds are known to "
                    f"trigger EINVAL on Linux kernels in Docker namespaces "
                    f"(observed on 2026-04-15 minitux install)."
                )

        if hasattr(socket, "TCP_KEEPCNT") and socket.TCP_KEEPCNT in opts:
            # Probe count: kernel minimum is 1. We use 3 as a sensible default.
            assert opts[socket.TCP_KEEPCNT] >= 1

    def test_build_keepalive_options_returns_dict(self) -> None:
        """
        Return type contract: must be a dict (possibly empty on non-Linux).
        """
        opts = _build_keepalive_options()
        assert isinstance(opts, dict)


class TestVerifyRedisConnectionSocketOptions:
    """
    verify_redis_connection() must pass the output of
    _build_keepalive_options() to redis.Redis.from_url() as
    socket_keepalive_options — not a hardcoded dict.
    """

    def test_verify_redis_connection_passes_sane_keepalive_options(self) -> None:
        """
        socket_keepalive_options kwarg must equal _build_keepalive_options().
        Guards against anyone re-introducing {1: 1, 2: 1} or similar magic.
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.info.return_value = {"redis_version": "7.0.0"}
        mock_client.config_get.return_value = {"maxmemory-policy": "allkeys-lru"}

        with patch("redis.Redis.from_url", return_value=mock_client) as mock_from_url:
            verify_redis_connection("redis://localhost:6379/0")

            call_kwargs = mock_from_url.call_args[1]
            assert "socket_keepalive_options" in call_kwargs
            assert call_kwargs["socket_keepalive_options"] == _build_keepalive_options()
            assert call_kwargs["socket_keepalive"] is True

    def test_verify_redis_connection_does_not_pass_magic_integer_keepalive(self) -> None:
        """
        Explicit regression guard for the 2026-04-15 minitux install defect.
        The hardcoded {1: 1, 2: 1} dict must never reappear.

        The defect-era TIME-based values (TCP_KEEPIDLE, TCP_KEEPINTVL) were
        1 second each — below the kernel minimum. We assert those specific
        keys, when present in the passed dict, are >= 10 seconds.
        """
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.info.return_value = {"redis_version": "7.0.0"}
        mock_client.config_get.return_value = {"maxmemory-policy": "allkeys-lru"}

        with patch("redis.Redis.from_url", return_value=mock_client) as mock_from_url:
            verify_redis_connection("redis://localhost:6379/0")

            passed_opts = mock_from_url.call_args[1].get("socket_keepalive_options", {})

            time_based_keys: list[int] = []
            if hasattr(socket, "TCP_KEEPIDLE"):
                time_based_keys.append(socket.TCP_KEEPIDLE)
            if hasattr(socket, "TCP_KEEPINTVL"):
                time_based_keys.append(socket.TCP_KEEPINTVL)

            for key in time_based_keys:
                if key in passed_opts:
                    assert passed_opts[key] >= 10, (
                        f"regression: time-based keepalive option {key}="
                        f"{passed_opts[key]} seconds is below the kernel minimum. "
                        f"This is the exact defect that crashed the minitux install "
                        f"on 2026-04-15."
                    )


# ---------------------------------------------------------------------------
# _classify_connection_error() tests (D2 — differentiated diagnostic messages)
# ---------------------------------------------------------------------------


class TestClassifyConnectionError:
    """
    Classify a Redis connection error into a diagnostic category.

    The goal of this classifier is to stop misleading operators. Before D2,
    a client-side setsockopt EINVAL surfaced as "Cannot connect to Redis,
    ensure Redis is running" — which sent operators chasing a Redis
    availability problem when the real defect was in our own socket-option
    configuration. The classifier must distinguish:

      * client_socket_option — OSError with EINVAL/ENOPROTOOPT in the
        exception chain (kernel rejected our setsockopt call).
      * tls — SSLError in the exception chain.
      * network — anything else that looks like a connectivity failure.
    """

    def test_classify_einval_in_chain_returns_client_socket_option(self) -> None:
        """EINVAL (22) from setsockopt classifies as client_socket_option."""
        import errno

        root_cause = OSError(errno.EINVAL, "Invalid argument")
        wrapped = ConnectionError("socket connection failed")
        wrapped.__cause__ = root_cause

        category, diagnostic = _classify_connection_error(wrapped)

        assert category == "client_socket_option"
        # Message must NOT suggest "Redis is not running"
        assert "not running" not in diagnostic.lower()
        assert "unavailable" not in diagnostic.lower()
        # Message MUST point at the client-side defect
        assert "client-side" in diagnostic.lower() or "api" in diagnostic.lower()
        assert "errno" in diagnostic.lower()
        assert "einval" in diagnostic.lower()

    def test_classify_enoprotoopt_in_chain_returns_client_socket_option(self) -> None:
        """ENOPROTOOPT (92) also indicates a client-side option defect."""
        import errno

        exc = OSError(errno.ENOPROTOOPT, "Protocol not available")
        category, diagnostic = _classify_connection_error(exc)

        assert category == "client_socket_option"
        assert "not running" not in diagnostic.lower()
        assert "enoprotoopt" in diagnostic.lower()

    def test_classify_econnrefused_returns_network(self) -> None:
        """ECONNREFUSED means Redis is genuinely unreachable — network category."""
        import errno

        exc = OSError(errno.ECONNREFUSED, "Connection refused")
        category, diagnostic = _classify_connection_error(exc)

        assert category == "network"
        # For this category it IS appropriate to tell the operator to check Redis.
        assert "redis" in diagnostic.lower()
        assert "refused" in diagnostic.lower() or "running" in diagnostic.lower()

    def test_classify_ssl_error_returns_tls(self) -> None:
        """SSLError anywhere in the chain classifies as tls."""
        import ssl

        root = ssl.SSLError("certificate verify failed")
        wrapped = ConnectionError("TLS handshake failed")
        wrapped.__cause__ = root

        category, diagnostic = _classify_connection_error(wrapped)

        assert category == "tls"
        assert "tls" in diagnostic.lower() or "ssl" in diagnostic.lower()

    def test_classify_generic_exception_returns_network(self) -> None:
        """Unknown errors fall back to network category with generic hint."""
        exc = RuntimeError("something weird happened")
        category, diagnostic = _classify_connection_error(exc)

        assert category == "network"
        assert len(diagnostic) > 0

    def test_classify_handles_context_chain_not_just_cause(self) -> None:
        """
        The classifier should also walk __context__ (implicit chaining) so that
        `except Exception` blocks that wrap a setsockopt error without an
        explicit `from` still get diagnosed correctly.
        """
        import errno

        try:
            try:
                raise OSError(errno.EINVAL, "Invalid argument")
            except OSError:
                raise ConnectionError("wrapper")
        except ConnectionError as wrapped:
            category, diagnostic = _classify_connection_error(wrapped)

        assert category == "client_socket_option"
        assert "einval" in diagnostic.lower()

    def test_classify_self_referential_chain_does_not_infinite_loop(self) -> None:
        """Defensive: a cycle in __cause__ must not hang the classifier."""
        a = RuntimeError("a")
        b = RuntimeError("b")
        a.__cause__ = b
        b.__cause__ = a

        # Must return without hanging.
        category, diagnostic = _classify_connection_error(a)
        assert category in ("network", "client_socket_option", "tls")
        assert len(diagnostic) > 0


class TestVerifyRedisConnectionClassifiedErrorMessages:
    """
    End-to-end: verify_redis_connection uses the classified diagnostic
    message in the raised ConfigError, so the operator sees the right hint.
    """

    def test_einval_from_setsockopt_raises_client_side_configerror(self) -> None:
        """
        When redis-py raises a ConnectionError caused by EINVAL from
        setsockopt, the ConfigError must name the client-side defect —
        NOT tell the operator to check if Redis is running.
        """
        import errno

        import redis

        root_cause = OSError(errno.EINVAL, "Invalid argument")
        wrapped = redis.ConnectionError("socket option setting failed")
        wrapped.__cause__ = root_cause

        mock_client = MagicMock()
        mock_client.ping.side_effect = wrapped

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError) as excinfo:
                verify_redis_connection("redis://localhost:6379/0")

        message = str(excinfo.value).lower()
        # The misleading phrase that 2026-04-15 triage traced through must be gone.
        assert "ensure redis is running" not in message, (
            "Regression: client-side EINVAL should NOT surface as "
            "'Ensure Redis is running'. Operators waste time checking a "
            "healthy server. See D2 in the 2026-04-15 remediation plan."
        )
        assert "client-side" in message or "api" in message
        assert "einval" in message

    def test_econnrefused_keeps_ensure_redis_running_guidance(self) -> None:
        """
        ECONNREFUSED is genuinely a server-availability problem, so the
        'Ensure Redis is running' hint is correct for this branch.
        """
        import errno

        import redis

        root = OSError(errno.ECONNREFUSED, "Connection refused")
        wrapped = redis.ConnectionError("connection refused")
        wrapped.__cause__ = root

        mock_client = MagicMock()
        mock_client.ping.side_effect = wrapped

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError) as excinfo:
                verify_redis_connection("redis://localhost:6379/0")

        message = str(excinfo.value).lower()
        assert "refused" in message or "running" in message
        # And it must NOT misclassify as client-side.
        assert "client-side" not in message


# ---------------------------------------------------------------------------
# _compute_backoff_seconds() tests (B2 — transient-failure retry)
# ---------------------------------------------------------------------------


class TestComputeBackoffSeconds:
    """
    Exponential backoff with upper clamp.

    The backoff schedule is 1s, 2s, 4s, 8s, 16s (doubling) with a hard
    ceiling so a misconfigured max_retries cannot produce a multi-minute
    sleep that makes startup appear hung.
    """

    def test_attempt_1_returns_initial_backoff(self) -> None:
        assert _compute_backoff_seconds(attempt=1, initial=1.0, cap=30.0) == 1.0

    def test_attempt_2_doubles(self) -> None:
        assert _compute_backoff_seconds(attempt=2, initial=1.0, cap=30.0) == 2.0

    def test_attempt_3_quadruples(self) -> None:
        assert _compute_backoff_seconds(attempt=3, initial=1.0, cap=30.0) == 4.0

    def test_attempt_5_is_16_seconds(self) -> None:
        assert _compute_backoff_seconds(attempt=5, initial=1.0, cap=30.0) == 16.0

    def test_cap_prevents_runaway_backoff(self) -> None:
        """High attempt number must not exceed the cap."""
        assert _compute_backoff_seconds(attempt=20, initial=1.0, cap=30.0) == 30.0

    def test_custom_initial_scales_correctly(self) -> None:
        """A 0.5s initial backoff should give 0.5, 1, 2, 4, 8 ..."""
        assert _compute_backoff_seconds(attempt=1, initial=0.5, cap=30.0) == 0.5
        assert _compute_backoff_seconds(attempt=4, initial=0.5, cap=30.0) == 4.0


# ---------------------------------------------------------------------------
# verify_redis_connection retry tests (B2)
# ---------------------------------------------------------------------------


class TestVerifyRedisConnectionRetry:
    """
    Transient-failure retry inside verify_redis_connection.

    Contract:
      * Transient failures (TimeoutError, network-category ConnectionError)
        retry up to max_retries with exponential backoff.
      * Permanent failures (auth, client_socket_option, tls) do NOT retry —
        they fail fast so the operator sees the real root cause immediately.
      * The sleep callable is injectable so tests run instantly.
      * Each retry emits a structured redis.ping_retry log with attempt
        number, delay, and category.
    """

    def test_transient_timeout_retries_and_succeeds(self) -> None:
        """Two transient timeouts followed by success → no exception raised."""
        import redis

        mock_client = MagicMock()
        mock_client.ping.side_effect = [
            redis.TimeoutError("transient 1"),
            redis.TimeoutError("transient 2"),
            True,
        ]
        mock_client.info.return_value = {"redis_version": "7.0.0"}
        mock_client.config_get.return_value = {"maxmemory-policy": "allkeys-lru"}

        sleep_calls: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with patch("redis.Redis.from_url", return_value=mock_client):
            verify_redis_connection(
                "redis://localhost:6379/0",
                max_retries=3,
                initial_backoff_seconds=1.0,
                sleep=fake_sleep,
            )

        assert mock_client.ping.call_count == 3
        # After attempt 1 and 2, one sleep each: 1s, 2s.
        assert sleep_calls == [1.0, 2.0]

    def test_auth_failure_does_not_retry(self) -> None:
        """
        Authentication errors are permanent — retrying will never succeed
        and delays operator visibility into the real problem.
        """
        import redis

        mock_client = MagicMock()
        mock_client.ping.side_effect = redis.AuthenticationError("wrong password")

        sleep_calls: list[float] = []

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError) as excinfo:
                verify_redis_connection(
                    "redis://bad:creds@localhost:6379/0",
                    max_retries=5,
                    initial_backoff_seconds=1.0,
                    sleep=sleep_calls.append,
                )

        # Only a single attempt — no retries.
        assert mock_client.ping.call_count == 1
        assert sleep_calls == []
        message = str(excinfo.value).lower()
        assert "auth" in message

    def test_client_socket_option_defect_does_not_retry(self) -> None:
        """
        EINVAL from setsockopt is a permanent client-side bug. Retrying
        will just loop forever with the same kernel rejection.
        """
        import redis

        root = OSError(errno.EINVAL, "Invalid argument")
        wrapped = redis.ConnectionError("socket option setting failed")
        wrapped.__cause__ = root

        mock_client = MagicMock()
        mock_client.ping.side_effect = wrapped

        sleep_calls: list[float] = []

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError) as excinfo:
                verify_redis_connection(
                    "redis://localhost:6379/0",
                    max_retries=5,
                    initial_backoff_seconds=1.0,
                    sleep=sleep_calls.append,
                )

        assert mock_client.ping.call_count == 1
        assert sleep_calls == []
        assert "client-side" in str(excinfo.value).lower()

    def test_transient_failures_exhaust_retry_budget(self) -> None:
        """
        If every attempt fails with a transient error, we raise after
        max_retries attempts with a message that names attempt count.
        """
        import redis

        mock_client = MagicMock()
        mock_client.ping.side_effect = redis.TimeoutError("always times out")

        sleep_calls: list[float] = []

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError) as excinfo:
                verify_redis_connection(
                    "redis://localhost:6379/0",
                    max_retries=3,
                    initial_backoff_seconds=1.0,
                    sleep=sleep_calls.append,
                )

        assert mock_client.ping.call_count == 3
        # Retries happen between attempts, so two sleeps for three attempts.
        assert sleep_calls == [1.0, 2.0]
        message = str(excinfo.value).lower()
        assert "3 attempts" in message or "after" in message

    def test_max_retries_one_means_no_retry(self) -> None:
        """max_retries=1 is the baseline 'try once' behaviour (no retries)."""
        import redis

        mock_client = MagicMock()
        mock_client.ping.side_effect = redis.TimeoutError("one-shot")

        sleep_calls: list[float] = []

        with patch("redis.Redis.from_url", return_value=mock_client):
            with pytest.raises(ConfigError):
                verify_redis_connection(
                    "redis://localhost:6379/0",
                    max_retries=1,
                    sleep=sleep_calls.append,
                )

        assert mock_client.ping.call_count == 1
        assert sleep_calls == []

