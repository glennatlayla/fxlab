"""
Unit tests for AlpacaMarketDataProvider.

Tests use httpx mock transport to simulate Alpaca Market Data API v2
responses. No real HTTP calls are made.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import pytest

from libs.contracts.alpaca_config import AlpacaConfig
from libs.contracts.errors import (
    AuthError,
    ExternalServiceError,
    TransientError,
)
from libs.contracts.market_data import CandleInterval
from services.worker.collectors.alpaca_market_data_provider import (
    AlpacaMarketDataProvider,
)

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------

_CONFIG = AlpacaConfig(
    api_key="AKTEST123",
    api_secret="secret123",
    base_url="https://paper-api.alpaca.markets",
    data_base_url="https://data.alpaca.markets",
)

_SAMPLE_BARS_RESPONSE: dict[str, Any] = {
    "bars": [
        {
            "t": "2026-01-02T05:00:00Z",
            "o": 174.50,
            "h": 176.25,
            "l": 173.80,
            "c": 175.90,
            "v": 58000000,
            "n": 12345,
            "vw": 175.10,
        },
        {
            "t": "2026-01-05T05:00:00Z",
            "o": 176.00,
            "h": 178.50,
            "l": 175.20,
            "c": 177.30,
            "v": 62000000,
            "n": 15000,
            "vw": 176.80,
        },
    ],
    "symbol": "AAPL",
    "next_page_token": None,
}

_PAGINATED_PAGE1: dict[str, Any] = {
    "bars": [
        {
            "t": "2026-01-02T05:00:00Z",
            "o": 174.50,
            "h": 176.25,
            "l": 173.80,
            "c": 175.90,
            "v": 58000000,
            "n": 12345,
            "vw": 175.10,
        },
    ],
    "symbol": "AAPL",
    "next_page_token": "QUFQTHwyMDI2LTAxLTAy",
}

_PAGINATED_PAGE2: dict[str, Any] = {
    "bars": [
        {
            "t": "2026-01-05T05:00:00Z",
            "o": 176.00,
            "h": 178.50,
            "l": 175.20,
            "c": 177.30,
            "v": 62000000,
            "n": 15000,
            "vw": 176.80,
        },
    ],
    "symbol": "AAPL",
    "next_page_token": None,
}


def _mock_transport(
    responses: list[tuple[int, dict[str, Any]]],
) -> httpx.MockTransport:
    """
    Create an httpx MockTransport that returns responses in sequence.

    Args:
        responses: List of (status_code, body_dict) tuples.

    Returns:
        httpx.MockTransport configured to return responses in order.
    """
    call_index = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = call_index["i"]
        call_index["i"] += 1
        if idx >= len(responses):
            return httpx.Response(500, json={"message": "unexpected extra call"})
        status, body = responses[idx]
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def _make_provider(
    transport: httpx.MockTransport,
    config: AlpacaConfig | None = None,
) -> AlpacaMarketDataProvider:
    """Create an AlpacaMarketDataProvider with mock transport."""
    cfg = config or _CONFIG
    return AlpacaMarketDataProvider(config=cfg, transport=transport)


# ---------------------------------------------------------------------------
# Successful fetch tests
# ---------------------------------------------------------------------------


class TestAlpacaProviderFetchBars:
    """Tests for successful bar fetching."""

    def test_fetch_returns_candles_from_api_response(self) -> None:
        transport = _mock_transport([(200, _SAMPLE_BARS_RESPONSE)])
        provider = _make_provider(transport)

        candles = provider.fetch_historical_bars(
            symbol="AAPL",
            interval=CandleInterval.D1,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

        assert len(candles) == 2
        assert candles[0].symbol == "AAPL"
        assert candles[0].interval == CandleInterval.D1
        assert candles[0].open == Decimal("174.50")
        assert candles[0].high == Decimal("176.25")
        assert candles[0].low == Decimal("173.80")
        assert candles[0].close == Decimal("175.90")
        assert candles[0].volume == 58_000_000
        assert candles[0].trade_count == 12345
        assert candles[0].vwap == Decimal("175.10")
        assert candles[0].timestamp == datetime(2026, 1, 2, 5, 0, tzinfo=timezone.utc)

    def test_fetch_handles_pagination(self) -> None:
        """Provider follows page_token to retrieve all pages."""
        transport = _mock_transport(
            [
                (200, _PAGINATED_PAGE1),
                (200, _PAGINATED_PAGE2),
            ]
        )
        provider = _make_provider(transport)

        candles = provider.fetch_historical_bars(
            symbol="AAPL",
            interval=CandleInterval.D1,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

        assert len(candles) == 2

    def test_fetch_empty_bars_returns_empty_list(self) -> None:
        transport = _mock_transport(
            [
                (200, {"bars": [], "symbol": "AAPL", "next_page_token": None}),
            ]
        )
        provider = _make_provider(transport)

        candles = provider.fetch_historical_bars(
            symbol="AAPL",
            interval=CandleInterval.D1,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

        assert candles == []

    def test_fetch_null_bars_returns_empty_list(self) -> None:
        """Alpaca sometimes returns null instead of empty array."""
        transport = _mock_transport(
            [
                (200, {"bars": None, "symbol": "AAPL", "next_page_token": None}),
            ]
        )
        provider = _make_provider(transport)

        candles = provider.fetch_historical_bars(
            symbol="AAPL",
            interval=CandleInterval.D1,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

        assert candles == []

    def test_candles_ordered_by_timestamp(self) -> None:
        """Results are always sorted by timestamp ascending."""
        transport = _mock_transport([(200, _SAMPLE_BARS_RESPONSE)])
        provider = _make_provider(transport)

        candles = provider.fetch_historical_bars(
            symbol="AAPL",
            interval=CandleInterval.D1,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

        timestamps = [c.timestamp for c in candles]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestAlpacaProviderErrorHandling:
    """Tests for HTTP error handling and domain exception mapping."""

    def test_401_raises_auth_error(self) -> None:
        transport = _mock_transport(
            [
                (401, {"message": "invalid credentials"}),
            ]
        )
        provider = _make_provider(transport)

        with pytest.raises(AuthError, match="invalid credentials"):
            provider.fetch_historical_bars(
                "AAPL",
                CandleInterval.D1,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 2, 1, tzinfo=timezone.utc),
            )

    def test_403_raises_auth_error(self) -> None:
        transport = _mock_transport(
            [
                (403, {"message": "forbidden"}),
            ]
        )
        provider = _make_provider(transport)

        with pytest.raises(AuthError, match="forbidden"):
            provider.fetch_historical_bars(
                "AAPL",
                CandleInterval.D1,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 2, 1, tzinfo=timezone.utc),
            )

    def test_429_raises_transient_error(self) -> None:
        transport = _mock_transport(
            [
                (429, {"message": "rate limit exceeded"}),
            ]
        )
        provider = _make_provider(transport)

        with pytest.raises(TransientError, match="rate limit"):
            provider.fetch_historical_bars(
                "AAPL",
                CandleInterval.D1,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 2, 1, tzinfo=timezone.utc),
            )

    def test_500_raises_transient_error(self) -> None:
        transport = _mock_transport(
            [
                (500, {"message": "internal server error"}),
            ]
        )
        provider = _make_provider(transport)

        with pytest.raises(TransientError, match="internal server error"):
            provider.fetch_historical_bars(
                "AAPL",
                CandleInterval.D1,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 2, 1, tzinfo=timezone.utc),
            )

    def test_422_raises_external_service_error(self) -> None:
        transport = _mock_transport(
            [
                (422, {"message": "invalid request parameters"}),
            ]
        )
        provider = _make_provider(transport)

        with pytest.raises(ExternalServiceError, match="invalid request"):
            provider.fetch_historical_bars(
                "AAPL",
                CandleInterval.D1,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 2, 1, tzinfo=timezone.utc),
            )


# ---------------------------------------------------------------------------
# Interval mapping tests
# ---------------------------------------------------------------------------


class TestAlpacaProviderIntervalMapping:
    """Tests for CandleInterval to Alpaca timeframe mapping."""

    def test_get_supported_intervals(self) -> None:
        transport = _mock_transport([])
        provider = _make_provider(transport)
        intervals = provider.get_supported_intervals()
        # Alpaca supports all our defined intervals
        assert set(intervals) == set(CandleInterval)

    def test_get_provider_name(self) -> None:
        transport = _mock_transport([])
        provider = _make_provider(transport)
        assert provider.get_provider_name() == "alpaca"
