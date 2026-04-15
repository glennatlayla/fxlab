"""
Integration tests for AlpacaBrokerAdapter against the real Alpaca Paper API.

Responsibilities:
- Verify connect/disconnect lifecycle against real Alpaca paper endpoint.
- Verify account retrieval, market clock, and position listing.
- Verify order submission, retrieval, and cancellation round-trip.
- Confirm error handling with real HTTP error responses.

Does NOT:
- Run in CI without ALPACA_API_KEY and ALPACA_API_SECRET env vars.
- Place live orders — paper trading only.
- Test business logic (that lives in services).

Dependencies:
- AlpacaBrokerAdapter: the adapter under test.
- AlpacaConfig: configuration model.
- BrokerTimeoutConfig: timeout configuration.
- ALPACA_API_KEY, ALPACA_API_SECRET env vars: must be set for paper trading.

Example:
    ALPACA_API_KEY=AK... ALPACA_API_SECRET=... pytest tests/integration/test_alpaca_broker_adapter.py -v

Skip condition:
    These tests are unconditionally skipped unless both ALPACA_API_KEY and
    ALPACA_API_SECRET environment variables are set. They are intended for
    manual validation against the Alpaca paper trading API, not for CI.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from libs.contracts.alpaca_config import AlpacaConfig
from libs.contracts.execution import ConnectionStatus, OrderRequest, OrderSide, OrderStatus
from services.api.adapters.alpaca_broker_adapter import AlpacaBrokerAdapter
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

# ---------------------------------------------------------------------------
# Skip unless Alpaca paper credentials are available
# ---------------------------------------------------------------------------

_API_KEY = os.environ.get("ALPACA_API_KEY", "")
_API_SECRET = os.environ.get("ALPACA_API_SECRET", "")

pytestmark = pytest.mark.skipif(
    not (_API_KEY and _API_SECRET),
    reason="ALPACA_API_KEY and ALPACA_API_SECRET not set — skipping Alpaca integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def alpaca_config() -> AlpacaConfig:
    """Create an AlpacaConfig pointed at the paper trading API."""
    return AlpacaConfig.paper(api_key=_API_KEY, api_secret=_API_SECRET)


@pytest.fixture(scope="module")
def timeout_config() -> BrokerTimeoutConfig:
    """Use generous timeouts for integration tests over the network."""
    return BrokerTimeoutConfig(
        connect_timeout_s=10.0,
        read_timeout_s=30.0,
        order_timeout_s=60.0,
        cancel_timeout_s=30.0,
    )


@pytest.fixture()
def adapter(
    alpaca_config: AlpacaConfig,
    timeout_config: BrokerTimeoutConfig,
) -> AlpacaBrokerAdapter:
    """
    Create and connect an AlpacaBrokerAdapter for each test.

    Disconnects after the test completes.
    """
    adp = AlpacaBrokerAdapter(config=alpaca_config, timeout_config=timeout_config)
    adp.connect()
    yield adp  # type: ignore[misc]
    adp.disconnect()


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestAlpacaIntegrationLifecycle:
    """Verify connect/disconnect against the real Alpaca paper API."""

    def test_connect_succeeds(self, adapter: AlpacaBrokerAdapter) -> None:
        """connect() should establish a real connection to Alpaca paper."""
        assert adapter._client is not None
        assert adapter._connected_at is not None

    def test_diagnostics_show_connected(self, adapter: AlpacaBrokerAdapter) -> None:
        """diagnostics() should report connected status after connect."""
        diag = adapter.diagnostics()
        assert diag.connection_status == ConnectionStatus.CONNECTED
        assert diag.broker_name == "alpaca"
        assert diag.latency_ms >= 0


# ---------------------------------------------------------------------------
# Account and market data tests
# ---------------------------------------------------------------------------


class TestAlpacaIntegrationAccountData:
    """Verify account retrieval and market clock against real API."""

    def test_get_account_returns_snapshot(self, adapter: AlpacaBrokerAdapter) -> None:
        """get_account() should return valid account data from paper."""
        account = adapter.get_account()
        # Paper accounts always have these fields
        assert "equity" in account
        assert "cash" in account
        assert "buying_power" in account
        assert Decimal(str(account["equity"])) >= 0

    def test_is_market_open_returns_bool(self, adapter: AlpacaBrokerAdapter) -> None:
        """is_market_open() should return a boolean from the real clock."""
        result = adapter.is_market_open()
        assert isinstance(result, bool)

    def test_get_positions_returns_list(self, adapter: AlpacaBrokerAdapter) -> None:
        """get_positions() should return a list (possibly empty) from paper."""
        positions = adapter.get_positions()
        assert isinstance(positions, list)


# ---------------------------------------------------------------------------
# Order round-trip test
# ---------------------------------------------------------------------------


class TestAlpacaIntegrationOrderRoundTrip:
    """Submit, retrieve, and cancel an order on the paper API."""

    def test_submit_and_cancel_market_order(self, adapter: AlpacaBrokerAdapter) -> None:
        """Submit a small market buy, verify, then cancel if still open."""
        request = OrderRequest(
            deployment_id="integ-test-001",
            strategy_id="integ-strat-001",
            correlation_id="integ-corr-001",
            execution_mode="paper",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            order_type="market",
            time_in_force="day",
        )

        # Submit
        response = adapter.submit_order(request)
        assert response.broker_order_id
        assert response.symbol == "AAPL"
        assert response.status in (
            OrderStatus.SUBMITTED,
            OrderStatus.PENDING,
            OrderStatus.FILLED,
        )

        broker_id = response.broker_order_id

        # Retrieve
        fetched = adapter.get_order(broker_id)
        assert fetched.broker_order_id == broker_id

        # Cancel if not already filled
        if fetched.status != OrderStatus.FILLED:
            cancelled = adapter.cancel_order(broker_id)
            assert cancelled.status in (
                OrderStatus.CANCELLED,
                OrderStatus.SUBMITTED,  # pending_cancel maps to submitted
                OrderStatus.FILLED,  # may have filled between check and cancel
            )

    def test_list_open_orders(self, adapter: AlpacaBrokerAdapter) -> None:
        """list_open_orders() should return a list from the paper API."""
        orders = adapter.list_open_orders()
        assert isinstance(orders, list)
