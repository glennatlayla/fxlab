"""
Unit tests for BrokerTimeoutConfig (M4 — Timeout Infrastructure).

Tests cover:
- Default values are sensible for financial trading operations.
- from_env() loads overrides from environment variables.
- Invalid environment values fall back to defaults with warning.
- Non-positive values are rejected and fall back to defaults.
- Config is immutable (frozen dataclass).

Dependencies:
    - services.api.infrastructure.timeout_config: BrokerTimeoutConfig.

Example:
    pytest tests/unit/test_timeout_config.py -v
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from services.api.infrastructure.timeout_config import BrokerTimeoutConfig


class TestBrokerTimeoutConfigDefaults:
    """Tests for default timeout values."""

    def test_default_connect_timeout(self) -> None:
        """Default connect timeout should be 5 seconds."""
        config = BrokerTimeoutConfig()
        assert config.connect_timeout_s == 5.0

    def test_default_read_timeout(self) -> None:
        """Default read timeout should be 10 seconds."""
        config = BrokerTimeoutConfig()
        assert config.read_timeout_s == 10.0

    def test_default_order_timeout(self) -> None:
        """Default order timeout should be 30 seconds."""
        config = BrokerTimeoutConfig()
        assert config.order_timeout_s == 30.0

    def test_default_cancel_timeout(self) -> None:
        """Default cancel timeout should be 15 seconds."""
        config = BrokerTimeoutConfig()
        assert config.cancel_timeout_s == 15.0

    def test_default_stream_heartbeat(self) -> None:
        """Default stream heartbeat should be 30 seconds."""
        config = BrokerTimeoutConfig()
        assert config.stream_heartbeat_s == 30.0

    def test_config_is_frozen(self) -> None:
        """Config should be immutable (frozen dataclass)."""
        config = BrokerTimeoutConfig()
        with pytest.raises(AttributeError):
            config.connect_timeout_s = 99.0  # type: ignore[misc]

    def test_order_timeout_gt_read_timeout(self) -> None:
        """Order timeout should be larger than read timeout by default."""
        config = BrokerTimeoutConfig()
        assert config.order_timeout_s > config.read_timeout_s

    def test_cancel_timeout_gt_read_timeout(self) -> None:
        """Cancel timeout should be larger than read timeout by default."""
        config = BrokerTimeoutConfig()
        assert config.cancel_timeout_s > config.read_timeout_s


class TestBrokerTimeoutConfigFromEnv:
    """Tests for from_env() factory method."""

    def test_from_env_uses_defaults_when_no_env_set(self) -> None:
        """from_env should use defaults when no env vars are set."""
        env_vars_to_clear = [
            "BROKER_CONNECT_TIMEOUT",
            "BROKER_READ_TIMEOUT",
            "BROKER_ORDER_TIMEOUT",
            "BROKER_CANCEL_TIMEOUT",
            "BROKER_STREAM_HEARTBEAT",
        ]
        with patch.dict(os.environ, {}, clear=False):
            for var in env_vars_to_clear:
                os.environ.pop(var, None)
            config = BrokerTimeoutConfig.from_env()
            assert config == BrokerTimeoutConfig()

    def test_from_env_reads_connect_timeout(self) -> None:
        """BROKER_CONNECT_TIMEOUT env var should override connect_timeout_s."""
        with patch.dict(os.environ, {"BROKER_CONNECT_TIMEOUT": "3.0"}):
            config = BrokerTimeoutConfig.from_env()
            assert config.connect_timeout_s == 3.0

    def test_from_env_reads_read_timeout(self) -> None:
        """BROKER_READ_TIMEOUT env var should override read_timeout_s."""
        with patch.dict(os.environ, {"BROKER_READ_TIMEOUT": "8.0"}):
            config = BrokerTimeoutConfig.from_env()
            assert config.read_timeout_s == 8.0

    def test_from_env_reads_order_timeout(self) -> None:
        """BROKER_ORDER_TIMEOUT env var should override order_timeout_s."""
        with patch.dict(os.environ, {"BROKER_ORDER_TIMEOUT": "20.0"}):
            config = BrokerTimeoutConfig.from_env()
            assert config.order_timeout_s == 20.0

    def test_from_env_reads_cancel_timeout(self) -> None:
        """BROKER_CANCEL_TIMEOUT env var should override cancel_timeout_s."""
        with patch.dict(os.environ, {"BROKER_CANCEL_TIMEOUT": "12.0"}):
            config = BrokerTimeoutConfig.from_env()
            assert config.cancel_timeout_s == 12.0

    def test_from_env_reads_stream_heartbeat(self) -> None:
        """BROKER_STREAM_HEARTBEAT env var should override stream_heartbeat_s."""
        with patch.dict(os.environ, {"BROKER_STREAM_HEARTBEAT": "45.0"}):
            config = BrokerTimeoutConfig.from_env()
            assert config.stream_heartbeat_s == 45.0

    def test_from_env_invalid_value_falls_back_to_default(self) -> None:
        """Non-numeric env value should fall back to default."""
        with patch.dict(os.environ, {"BROKER_CONNECT_TIMEOUT": "not_a_number"}):
            config = BrokerTimeoutConfig.from_env()
            assert config.connect_timeout_s == 5.0  # default

    def test_from_env_negative_value_falls_back_to_default(self) -> None:
        """Negative env value should fall back to default."""
        with patch.dict(os.environ, {"BROKER_ORDER_TIMEOUT": "-5.0"}):
            config = BrokerTimeoutConfig.from_env()
            assert config.order_timeout_s == 30.0  # default

    def test_from_env_zero_value_falls_back_to_default(self) -> None:
        """Zero env value should fall back to default."""
        with patch.dict(os.environ, {"BROKER_READ_TIMEOUT": "0"}):
            config = BrokerTimeoutConfig.from_env()
            assert config.read_timeout_s == 10.0  # default

    def test_from_env_multiple_overrides(self) -> None:
        """Multiple env vars should all be respected."""
        with patch.dict(
            os.environ,
            {
                "BROKER_CONNECT_TIMEOUT": "2.0",
                "BROKER_ORDER_TIMEOUT": "25.0",
                "BROKER_STREAM_HEARTBEAT": "60.0",
            },
        ):
            config = BrokerTimeoutConfig.from_env()
            assert config.connect_timeout_s == 2.0
            assert config.read_timeout_s == 10.0  # default (not set)
            assert config.order_timeout_s == 25.0
            assert config.cancel_timeout_s == 15.0  # default (not set)
            assert config.stream_heartbeat_s == 60.0

    def test_from_env_integer_string_accepted(self) -> None:
        """Integer string values should be accepted and converted to float."""
        with patch.dict(os.environ, {"BROKER_CONNECT_TIMEOUT": "3"}):
            config = BrokerTimeoutConfig.from_env()
            assert config.connect_timeout_s == 3.0


class TestBrokerTimeoutConfigCustom:
    """Tests for custom (non-env) construction."""

    def test_custom_constructor(self) -> None:
        """Direct constructor should accept custom values."""
        config = BrokerTimeoutConfig(
            connect_timeout_s=2.0,
            read_timeout_s=5.0,
            order_timeout_s=15.0,
            cancel_timeout_s=8.0,
            stream_heartbeat_s=20.0,
        )
        assert config.connect_timeout_s == 2.0
        assert config.read_timeout_s == 5.0
        assert config.order_timeout_s == 15.0
        assert config.cancel_timeout_s == 8.0
        assert config.stream_heartbeat_s == 20.0

    def test_equality(self) -> None:
        """Two configs with same values should be equal."""
        a = BrokerTimeoutConfig(connect_timeout_s=3.0)
        b = BrokerTimeoutConfig(connect_timeout_s=3.0)
        assert a == b

    def test_inequality(self) -> None:
        """Two configs with different values should not be equal."""
        a = BrokerTimeoutConfig(connect_timeout_s=3.0)
        b = BrokerTimeoutConfig(connect_timeout_s=5.0)
        assert a != b
