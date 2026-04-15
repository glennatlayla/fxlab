"""
Integration tests for Alpaca WebSocket streams against real paper API.

Responsibilities:
- Verify AlpacaMarketStream connects to real Alpaca market data endpoint.
- Verify AlpacaOrderStream connects to real Alpaca trade updates endpoint.
- Verify StreamManager orchestrates both streams for a deployment.
- Confirm authentication, subscription, and message receipt over WebSocket.

Does NOT:
- Run in CI without ALPACA_API_KEY and ALPACA_API_SECRET env vars.
- Test with live trading credentials.
- Guarantee message receipt (markets may be closed).

Dependencies:
- AlpacaMarketStream, AlpacaOrderStream: stream adapters under test.
- AlpacaConfig: configuration model with paper factory.
- StreamManager: lifecycle orchestration.
- ALPACA_API_KEY, ALPACA_API_SECRET env vars: must be set for paper trading.

Example:
    ALPACA_API_KEY=AK... ALPACA_API_SECRET=... pytest tests/integration/test_alpaca_streams.py -v

Skip condition:
    These tests are unconditionally skipped unless both ALPACA_API_KEY and
    ALPACA_API_SECRET environment variables are set. They are intended for
    manual validation against the Alpaca paper trading API, not for CI.
"""

from __future__ import annotations

import os
import time

import pytest

from libs.contracts.alpaca_config import AlpacaConfig
from services.api.adapters.alpaca_market_stream import AlpacaMarketStream
from services.api.adapters.alpaca_order_stream import AlpacaOrderStream
from services.api.infrastructure.stream_manager import StreamManager
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

# ---------------------------------------------------------------------------
# Skip unless Alpaca paper credentials are available
# ---------------------------------------------------------------------------

_API_KEY = os.environ.get("ALPACA_API_KEY", "")
_API_SECRET = os.environ.get("ALPACA_API_SECRET", "")

pytestmark = pytest.mark.skipif(
    not (_API_KEY and _API_SECRET),
    reason="ALPACA_API_KEY and ALPACA_API_SECRET not set — skipping Alpaca stream integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def alpaca_config() -> AlpacaConfig:
    """Create an AlpacaConfig for paper trading with IEX data feed."""
    return AlpacaConfig.paper(api_key=_API_KEY, api_secret=_API_SECRET)


@pytest.fixture(scope="module")
def timeout_config() -> BrokerTimeoutConfig:
    """Use generous timeouts for integration tests over the network."""
    return BrokerTimeoutConfig(
        connect_timeout_s=10.0,
        read_timeout_s=30.0,
        stream_heartbeat_s=60.0,
    )


# ---------------------------------------------------------------------------
# Market stream integration tests
# ---------------------------------------------------------------------------


class TestAlpacaMarketStreamIntegration:
    """Verify market data stream against real Alpaca paper endpoint."""

    def test_market_stream_connects_and_authenticates(
        self,
        alpaca_config: AlpacaConfig,
        timeout_config: BrokerTimeoutConfig,
    ) -> None:
        """Market stream should connect and authenticate with paper API."""
        stream = AlpacaMarketStream(config=alpaca_config, timeout_config=timeout_config)
        stream.subscribe(["AAPL"])
        stream.start()

        # Give time for connection and authentication
        time.sleep(3)

        try:
            assert stream.is_connected(), "Stream should be connected after start()"
            diag = stream.diagnostics()
            assert diag["connected"] is True
            assert "AAPL" in diag["subscribed_symbols"]
        finally:
            stream.stop()

    def test_market_stream_stop_is_clean(
        self,
        alpaca_config: AlpacaConfig,
        timeout_config: BrokerTimeoutConfig,
    ) -> None:
        """Market stream should disconnect cleanly on stop()."""
        stream = AlpacaMarketStream(config=alpaca_config, timeout_config=timeout_config)
        stream.start()
        time.sleep(2)
        stream.stop()

        assert not stream.is_connected()
        diag = stream.diagnostics()
        assert diag["connected"] is False


# ---------------------------------------------------------------------------
# Order stream integration tests
# ---------------------------------------------------------------------------


class TestAlpacaOrderStreamIntegration:
    """Verify order update stream against real Alpaca paper endpoint."""

    def test_order_stream_connects_and_authenticates(
        self,
        alpaca_config: AlpacaConfig,
        timeout_config: BrokerTimeoutConfig,
    ) -> None:
        """Order stream should connect and authenticate with paper API."""
        stream = AlpacaOrderStream(config=alpaca_config, timeout_config=timeout_config)
        stream.start()

        # Give time for connection and authentication
        time.sleep(3)

        try:
            assert stream.is_connected(), "Order stream should be connected"
            diag = stream.diagnostics()
            assert diag["connected"] is True
        finally:
            stream.stop()


# ---------------------------------------------------------------------------
# StreamManager integration test
# ---------------------------------------------------------------------------


class TestStreamManagerIntegration:
    """Verify StreamManager orchestrates real streams."""

    def test_stream_manager_start_stop_lifecycle(
        self,
        alpaca_config: AlpacaConfig,
        timeout_config: BrokerTimeoutConfig,
    ) -> None:
        """StreamManager should start and stop streams for a deployment."""
        market = AlpacaMarketStream(config=alpaca_config, timeout_config=timeout_config)
        market.subscribe(["AAPL"])
        order = AlpacaOrderStream(config=alpaca_config, timeout_config=timeout_config)

        manager = StreamManager()
        manager.register_market_stream("integ-dep", market)
        manager.register_order_stream("integ-dep", order)

        assert manager.is_deployment_streaming("integ-dep")

        manager.start_streams("integ-dep")
        time.sleep(3)

        try:
            diag = manager.diagnostics()
            assert diag["total_deployments"] == 1
            assert "integ-dep" in diag["deployments"]
        finally:
            manager.stop_all()
