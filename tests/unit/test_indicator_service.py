"""
Unit tests for IndicatorService.

Validates service layer logic: candle fetching, indicator computation
delegation, error handling, and listing.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from libs.contracts.errors import IndicatorNotFoundError, NotFoundError
from libs.contracts.indicator import IndicatorRequest
from libs.contracts.market_data import (
    Candle,
    CandleInterval,
    MarketDataPage,
)
from libs.indicators import default_engine
from services.api.services.indicator_service import IndicatorService

# ---------------------------------------------------------------------------
# Mock repository
# ---------------------------------------------------------------------------


class _MockRepo:
    """In-memory mock market data repository for service tests."""

    def __init__(self, candles: list[Candle] | None = None) -> None:
        self._candles = candles or []

    def query_candles(self, query: Any) -> MarketDataPage:
        return MarketDataPage(
            candles=self._candles,
            total_count=len(self._candles),
            has_more=False,
            next_cursor=None,
        )


def _make_candles(n: int = 20) -> list[Candle]:
    return [
        Candle(
            symbol="TEST",
            interval=CandleInterval.D1,
            open=Decimal(f"{100 + i}.00"),
            high=Decimal(f"{102 + i}.00"),
            low=Decimal(f"{99 + i}.00"),
            close=Decimal(f"{101 + i}.00"),
            volume=1_000_000,
            timestamp=datetime(2026, 1, 2 + i, 14, 30, 0, tzinfo=timezone.utc),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComputeIndicator:
    """Tests for compute_indicator()."""

    def test_computes_sma_successfully(self) -> None:
        service = IndicatorService(
            engine=default_engine,
            market_data_repo=_MockRepo(_make_candles(20)),
        )
        result = service.compute_indicator("SMA", "TEST", CandleInterval.D1, period=5)
        assert result.indicator_name == "SMA"
        assert len(result.values) == 20

    def test_raises_not_found_when_no_candles(self) -> None:
        service = IndicatorService(
            engine=default_engine,
            market_data_repo=_MockRepo([]),
        )
        with pytest.raises(NotFoundError, match="No candle data"):
            service.compute_indicator("SMA", "EMPTY", CandleInterval.D1, period=5)

    def test_raises_indicator_not_found(self) -> None:
        service = IndicatorService(
            engine=default_engine,
            market_data_repo=_MockRepo(_make_candles(10)),
        )
        with pytest.raises(IndicatorNotFoundError):
            service.compute_indicator("NOPE", "TEST", CandleInterval.D1)


class TestComputeBatch:
    """Tests for compute_batch()."""

    def test_batch_computes_multiple(self) -> None:
        service = IndicatorService(
            engine=default_engine,
            market_data_repo=_MockRepo(_make_candles(30)),
        )
        requests = [
            IndicatorRequest(indicator_name="SMA", params={"period": 5}),
            IndicatorRequest(indicator_name="RSI", params={"period": 14}),
        ]
        results = service.compute_batch(requests, "TEST", CandleInterval.D1)
        assert "SMA" in results
        assert "RSI" in results

    def test_batch_raises_not_found_when_no_candles(self) -> None:
        service = IndicatorService(
            engine=default_engine,
            market_data_repo=_MockRepo([]),
        )
        requests = [IndicatorRequest(indicator_name="SMA")]
        with pytest.raises(NotFoundError):
            service.compute_batch(requests, "EMPTY", CandleInterval.D1)


class TestListAndInfo:
    """Tests for list_available() and get_indicator_info()."""

    def test_list_available_returns_all_registered(self) -> None:
        service = IndicatorService(
            engine=default_engine,
            market_data_repo=_MockRepo(),
        )
        available = service.list_available()
        assert len(available) >= 24
        names = {i.name for i in available}
        assert "SMA" in names
        assert "RSI" in names
        assert "BOLLINGER_BANDS" in names

    def test_get_indicator_info_returns_metadata(self) -> None:
        service = IndicatorService(
            engine=default_engine,
            market_data_repo=_MockRepo(),
        )
        info = service.get_indicator_info("MACD")
        assert info.name == "MACD"
        assert info.category == "momentum"
        assert len(info.output_names) == 3

    def test_get_indicator_info_unknown_raises(self) -> None:
        service = IndicatorService(
            engine=default_engine,
            market_data_repo=_MockRepo(),
        )
        with pytest.raises(IndicatorNotFoundError):
            service.get_indicator_info("UNKNOWN")
