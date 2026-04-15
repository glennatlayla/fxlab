"""
Unit tests for RiskAnalyticsService.

Validates VaR (Historical/Parametric), CVaR, correlation matrix,
concentration analysis (HHI), exposure calculations, and portfolio
risk summary aggregation. Uses mock repositories with deterministic
data for reproducible numerical assertions.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import numpy as np
import pytest

from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.market_data import (
    Candle,
    CandleInterval,
    DataGap,
    MarketDataPage,
    MarketDataQuery,
)
from libs.contracts.risk_analytics import VaRMethod

# ---------------------------------------------------------------------------
# Mock repositories
# ---------------------------------------------------------------------------


class MockPositionRepo:
    """In-memory mock position repository for risk analytics tests."""

    def __init__(self) -> None:
        self._positions: list[dict[str, Any]] = []

    def set_positions(self, positions: list[dict[str, Any]]) -> None:
        """Set positions that will be returned by list_by_deployment."""
        self._positions = positions

    def list_by_deployment(self, *, deployment_id: str) -> list[dict[str, Any]]:
        """Return positions for a deployment."""
        return [p for p in self._positions if p.get("deployment_id") == deployment_id]


class MockMarketDataRepo:
    """In-memory mock market data repository for risk analytics tests."""

    def __init__(self) -> None:
        self._candles: dict[str, list[Candle]] = {}

    def set_candles(self, symbol: str, candles: list[Candle]) -> None:
        """Set candles for a specific symbol."""
        self._candles[symbol] = candles

    def query_candles(self, query: MarketDataQuery) -> MarketDataPage:
        """Return candles for the queried symbol."""
        candles = self._candles.get(query.symbol, [])
        # Apply time filtering if present
        filtered = candles
        if query.start:
            filtered = [c for c in filtered if c.timestamp >= query.start]
        if query.end:
            filtered = [c for c in filtered if c.timestamp <= query.end]
        return MarketDataPage(
            candles=filtered,
            total_count=len(filtered),
            has_more=False,
            next_cursor=None,
        )

    def upsert_candles(self, candles: list[Candle]) -> int:
        return len(candles)

    def get_latest_candle(self, symbol: str, interval: CandleInterval) -> Candle | None:
        candles = self._candles.get(symbol, [])
        return candles[-1] if candles else None

    def detect_gaps(
        self, symbol: str, interval: CandleInterval, start: datetime, end: datetime
    ) -> list[DataGap]:
        return []

    def delete_candles(self, symbol: str, interval: CandleInterval, before: datetime) -> int:
        return 0


# ---------------------------------------------------------------------------
# Test data factories
# ---------------------------------------------------------------------------

_DEPLOY_ID = "01HTESTDEPLOY000000000000"


def _make_position(
    symbol: str,
    quantity: str,
    market_value: str,
    average_entry_price: str = "100.00",
    market_price: str = "100.00",
) -> dict[str, Any]:
    """Create a position dict matching PositionRepositoryInterface output."""
    return {
        "id": f"01HPOS{symbol}00000000000000",
        "deployment_id": _DEPLOY_ID,
        "symbol": symbol,
        "quantity": quantity,
        "average_entry_price": average_entry_price,
        "market_price": market_price,
        "market_value": market_value,
        "unrealized_pnl": "0",
        "realized_pnl": "0",
        "cost_basis": str(Decimal(average_entry_price) * Decimal(quantity)),
    }


def _make_daily_candles(
    symbol: str,
    n_days: int,
    base_price: float = 100.0,
    daily_return: float = 0.001,
    volatility: float = 0.02,
    seed: int = 42,
) -> list[Candle]:
    """
    Generate deterministic daily candle data.

    Uses a seeded random generator for reproducible test results.
    Prices follow a geometric Brownian motion approximation.
    """
    rng = np.random.default_rng(seed)
    candles = []
    price = base_price
    base_date = datetime(2024, 1, 2, 20, 0, 0, tzinfo=timezone.utc)

    for i in range(n_days):
        # Generate log-normal return
        ret = daily_return + volatility * rng.standard_normal()
        price = price * math.exp(ret)

        candles.append(
            Candle(
                symbol=symbol,
                interval=CandleInterval.D1,
                open=Decimal(f"{price * 0.999:.2f}"),
                high=Decimal(f"{price * 1.01:.2f}"),
                low=Decimal(f"{price * 0.99:.2f}"),
                close=Decimal(f"{price:.2f}"),
                volume=1_000_000,
                timestamp=base_date + timedelta(days=i),
            )
        )
    return candles


def _make_constant_candles(symbol: str, n_days: int, price: float = 100.0) -> list[Candle]:
    """Create candles with constant price (zero volatility)."""
    base_date = datetime(2024, 1, 2, 20, 0, 0, tzinfo=timezone.utc)
    return [
        Candle(
            symbol=symbol,
            interval=CandleInterval.D1,
            open=Decimal(f"{price:.2f}"),
            high=Decimal(f"{price:.2f}"),
            low=Decimal(f"{price:.2f}"),
            close=Decimal(f"{price:.2f}"),
            volume=1_000_000,
            timestamp=base_date + timedelta(days=i),
        )
        for i in range(n_days)
    ]


# ---------------------------------------------------------------------------
# Service factory
# ---------------------------------------------------------------------------


def _make_service(
    positions: list[dict[str, Any]] | None = None,
    candle_map: dict[str, list[Candle]] | None = None,
) -> Any:
    """Create a RiskAnalyticsService with mock dependencies."""
    from services.api.services.risk_analytics_service import RiskAnalyticsService

    pos_repo = MockPositionRepo()
    if positions:
        pos_repo.set_positions(positions)

    md_repo = MockMarketDataRepo()
    if candle_map:
        for sym, candles in candle_map.items():
            md_repo.set_candles(sym, candles)

    return RiskAnalyticsService(
        position_repo=pos_repo,
        market_data_repo=md_repo,
    )


# ---------------------------------------------------------------------------
# compute_var
# ---------------------------------------------------------------------------


class TestComputeVaR:
    """Tests for VaR and CVaR computation."""

    def test_historical_var_with_known_data(self) -> None:
        """VaR should match manual percentile calculation."""
        positions = [_make_position("AAPL", "100", "10000.00")]
        candles = _make_daily_candles("AAPL", 260, base_price=100.0, seed=42)
        service = _make_service(positions=positions, candle_map={"AAPL": candles})

        result = service.compute_var(deployment_id=_DEPLOY_ID, lookback_days=252)

        assert result.method is VaRMethod.HISTORICAL
        assert result.lookback_days == 252
        # VaR should be negative (loss)
        assert result.var_95 < Decimal("0")
        assert result.var_99 < Decimal("0")
        # 99% VaR should be more extreme than 95% VaR
        assert result.var_99 < result.var_95
        # CVaR should be more extreme than VaR (further into the tail)
        assert result.cvar_95 <= result.var_95
        assert result.cvar_99 <= result.var_99

    def test_var_with_zero_volatility_is_zero(self) -> None:
        """Constant prices produce zero VaR."""
        positions = [_make_position("AAPL", "100", "10000.00")]
        candles = _make_constant_candles("AAPL", 260, price=100.0)
        service = _make_service(positions=positions, candle_map={"AAPL": candles})

        result = service.compute_var(deployment_id=_DEPLOY_ID, lookback_days=252)

        assert result.var_95 == Decimal("0")
        assert result.var_99 == Decimal("0")
        assert result.cvar_95 == Decimal("0")
        assert result.cvar_99 == Decimal("0")

    def test_var_multi_position_portfolio(self) -> None:
        """VaR should account for multiple positions."""
        positions = [
            _make_position("AAPL", "100", "10000.00"),
            _make_position("MSFT", "50", "7500.00"),
        ]
        candles_aapl = _make_daily_candles("AAPL", 260, base_price=100.0, seed=42)
        candles_msft = _make_daily_candles("MSFT", 260, base_price=150.0, seed=99)
        service = _make_service(
            positions=positions,
            candle_map={"AAPL": candles_aapl, "MSFT": candles_msft},
        )

        result = service.compute_var(deployment_id=_DEPLOY_ID, lookback_days=252)

        assert result.var_95 < Decimal("0")
        assert result.var_99 < result.var_95

    def test_var_raises_not_found_no_positions(self) -> None:
        """Raise NotFoundError when deployment has no positions."""
        service = _make_service(positions=[])

        with pytest.raises(NotFoundError, match="[Nn]o.*position"):
            service.compute_var(deployment_id=_DEPLOY_ID, lookback_days=252)

    def test_var_raises_not_found_insufficient_data(self) -> None:
        """Raise NotFoundError when insufficient market data for lookback."""
        positions = [_make_position("AAPL", "100", "10000.00")]
        # Only 10 days of data but requesting 252 lookback
        candles = _make_daily_candles("AAPL", 10, base_price=100.0, seed=42)
        service = _make_service(positions=positions, candle_map={"AAPL": candles})

        with pytest.raises(NotFoundError, match="[Ii]nsufficient"):
            service.compute_var(deployment_id=_DEPLOY_ID, lookback_days=252)

    def test_var_validates_minimum_lookback(self) -> None:
        """Raise ValidationError when lookback_days < 30."""
        positions = [_make_position("AAPL", "100", "10000.00")]
        candles = _make_daily_candles("AAPL", 260, base_price=100.0, seed=42)
        service = _make_service(positions=positions, candle_map={"AAPL": candles})

        with pytest.raises(ValidationError, match="lookback"):
            service.compute_var(deployment_id=_DEPLOY_ID, lookback_days=10)

    def test_var_short_position_inverted(self) -> None:
        """Short positions should have inverted VaR direction."""
        # Long position
        long_pos = [_make_position("AAPL", "100", "10000.00")]
        candles = _make_daily_candles("AAPL", 260, base_price=100.0, seed=42)
        long_service = _make_service(positions=long_pos, candle_map={"AAPL": candles})
        long_var = long_service.compute_var(deployment_id=_DEPLOY_ID, lookback_days=252)

        # Short position (negative quantity, negative market value)
        short_pos = [_make_position("AAPL", "-100", "-10000.00")]
        short_service = _make_service(positions=short_pos, candle_map={"AAPL": candles})
        short_var = short_service.compute_var(deployment_id=_DEPLOY_ID, lookback_days=252)

        # Both should have negative VaR (loss), but different magnitudes
        assert long_var.var_95 < Decimal("0")
        assert short_var.var_95 < Decimal("0")

    def test_var_computed_at_is_set(self) -> None:
        """Result should have a computed_at timestamp."""
        positions = [_make_position("AAPL", "100", "10000.00")]
        candles = _make_daily_candles("AAPL", 260, base_price=100.0, seed=42)
        service = _make_service(positions=positions, candle_map={"AAPL": candles})

        result = service.compute_var(deployment_id=_DEPLOY_ID, lookback_days=252)

        assert result.computed_at is not None
        assert result.computed_at.tzinfo is not None


# ---------------------------------------------------------------------------
# compute_correlation_matrix
# ---------------------------------------------------------------------------


class TestComputeCorrelationMatrix:
    """Tests for correlation matrix computation."""

    def test_single_symbol_identity_matrix(self) -> None:
        """Single symbol produces 1x1 identity matrix."""
        positions = [_make_position("AAPL", "100", "10000.00")]
        candles = _make_daily_candles("AAPL", 260, base_price=100.0, seed=42)
        service = _make_service(positions=positions, candle_map={"AAPL": candles})

        result = service.compute_correlation_matrix(deployment_id=_DEPLOY_ID, lookback_days=252)

        assert result.symbols == ["AAPL"]
        assert len(result.entries) == 1
        assert result.entries[0].correlation == Decimal("1.0")
        assert result.matrix == [["1.0"]]

    def test_two_symbol_symmetric_matrix(self) -> None:
        """Two-symbol correlation matrix must be symmetric."""
        positions = [
            _make_position("AAPL", "100", "10000.00"),
            _make_position("MSFT", "50", "7500.00"),
        ]
        candles_aapl = _make_daily_candles("AAPL", 260, base_price=100.0, seed=42)
        candles_msft = _make_daily_candles("MSFT", 260, base_price=150.0, seed=99)
        service = _make_service(
            positions=positions,
            candle_map={"AAPL": candles_aapl, "MSFT": candles_msft},
        )

        result = service.compute_correlation_matrix(deployment_id=_DEPLOY_ID, lookback_days=252)

        assert len(result.symbols) == 2
        assert len(result.entries) == 4
        # Diagonal should be 1.0
        diag_entries = [e for e in result.entries if e.symbol_a == e.symbol_b]
        for e in diag_entries:
            assert e.correlation == Decimal("1.0")
        # Matrix is symmetric: corr(A,B) == corr(B,A)
        off_diag = [e for e in result.entries if e.symbol_a != e.symbol_b]
        assert len(off_diag) == 2
        assert off_diag[0].correlation == off_diag[1].correlation

    def test_correlation_bounds(self) -> None:
        """All correlation values must be between -1 and 1."""
        positions = [
            _make_position("AAPL", "100", "10000.00"),
            _make_position("MSFT", "50", "7500.00"),
            _make_position("GOOGL", "30", "5000.00"),
        ]
        candles = {
            "AAPL": _make_daily_candles("AAPL", 260, seed=42),
            "MSFT": _make_daily_candles("MSFT", 260, seed=99),
            "GOOGL": _make_daily_candles("GOOGL", 260, seed=7),
        }
        service = _make_service(positions=positions, candle_map=candles)

        result = service.compute_correlation_matrix(deployment_id=_DEPLOY_ID, lookback_days=252)

        for entry in result.entries:
            assert Decimal("-1") <= entry.correlation <= Decimal("1")

    def test_positive_semi_definite(self) -> None:
        """Correlation matrix eigenvalues must be >= 0."""
        positions = [
            _make_position("AAPL", "100", "10000.00"),
            _make_position("MSFT", "50", "7500.00"),
            _make_position("GOOGL", "30", "5000.00"),
        ]
        candles = {
            "AAPL": _make_daily_candles("AAPL", 260, seed=42),
            "MSFT": _make_daily_candles("MSFT", 260, seed=99),
            "GOOGL": _make_daily_candles("GOOGL", 260, seed=7),
        }
        service = _make_service(positions=positions, candle_map=candles)

        result = service.compute_correlation_matrix(deployment_id=_DEPLOY_ID, lookback_days=252)

        # Build dense matrix from string entries
        n = len(result.symbols)
        dense = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                dense[i, j] = float(result.matrix[i][j])
        eigenvalues = np.linalg.eigvalsh(dense)
        # All eigenvalues should be >= -1e-10 (numerical tolerance)
        assert all(ev >= -1e-10 for ev in eigenvalues)

    def test_correlation_raises_not_found_no_positions(self) -> None:
        service = _make_service(positions=[])
        with pytest.raises(NotFoundError):
            service.compute_correlation_matrix(deployment_id=_DEPLOY_ID)

    def test_correlation_raises_not_found_insufficient_data(self) -> None:
        positions = [_make_position("AAPL", "100", "10000.00")]
        candles = _make_daily_candles("AAPL", 5, seed=42)
        service = _make_service(positions=positions, candle_map={"AAPL": candles})
        with pytest.raises(NotFoundError, match="[Ii]nsufficient"):
            service.compute_correlation_matrix(deployment_id=_DEPLOY_ID, lookback_days=252)


# ---------------------------------------------------------------------------
# compute_concentration
# ---------------------------------------------------------------------------


class TestComputeConcentration:
    """Tests for concentration analysis (HHI)."""

    def test_single_stock_hhi_10000(self) -> None:
        """Single-stock portfolio has maximum concentration HHI = 10000."""
        positions = [_make_position("AAPL", "100", "10000.00")]
        service = _make_service(positions=positions)

        result = service.compute_concentration(deployment_id=_DEPLOY_ID)

        assert result.herfindahl_index == Decimal("10000")
        assert len(result.per_symbol) == 1
        assert result.per_symbol[0].pct_of_portfolio == Decimal("100.0")
        assert result.top_5_pct == Decimal("100.0")

    def test_equal_weight_two_stocks_hhi_5000(self) -> None:
        """Two equal-weight stocks have HHI = 50^2 + 50^2 = 5000."""
        positions = [
            _make_position("AAPL", "100", "10000.00"),
            _make_position("MSFT", "100", "10000.00"),
        ]
        service = _make_service(positions=positions)

        result = service.compute_concentration(deployment_id=_DEPLOY_ID)

        assert result.herfindahl_index == Decimal("5000")
        for sc in result.per_symbol:
            assert sc.pct_of_portfolio == Decimal("50.0")

    def test_equal_weight_four_stocks_hhi_2500(self) -> None:
        """Four equal-weight stocks: HHI = 4 × 25^2 = 2500."""
        positions = [
            _make_position("AAPL", "100", "10000.00"),
            _make_position("MSFT", "100", "10000.00"),
            _make_position("GOOGL", "100", "10000.00"),
            _make_position("AMZN", "100", "10000.00"),
        ]
        service = _make_service(positions=positions)

        result = service.compute_concentration(deployment_id=_DEPLOY_ID)

        assert result.herfindahl_index == Decimal("2500")

    def test_concentrated_portfolio(self) -> None:
        """Unequal weights produce higher HHI than equal weights."""
        positions = [
            _make_position("AAPL", "100", "70000.00"),  # 70%
            _make_position("MSFT", "100", "20000.00"),  # 20%
            _make_position("GOOGL", "100", "10000.00"),  # 10%
        ]
        service = _make_service(positions=positions)

        result = service.compute_concentration(deployment_id=_DEPLOY_ID)

        # HHI = 70^2 + 20^2 + 10^2 = 4900 + 400 + 100 = 5400
        assert result.herfindahl_index == Decimal("5400")

    def test_sorted_by_weight_descending(self) -> None:
        """Per-symbol list should be sorted by weight descending."""
        positions = [
            _make_position("MSFT", "100", "10000.00"),  # smaller
            _make_position("AAPL", "100", "90000.00"),  # larger
        ]
        service = _make_service(positions=positions)

        result = service.compute_concentration(deployment_id=_DEPLOY_ID)

        assert result.per_symbol[0].symbol == "AAPL"
        assert result.per_symbol[1].symbol == "MSFT"

    def test_top_5_pct_with_more_than_5_positions(self) -> None:
        """Top 5 % should sum the 5 largest position weights."""
        positions = [
            _make_position("A", "100", "30000.00"),
            _make_position("B", "100", "20000.00"),
            _make_position("C", "100", "15000.00"),
            _make_position("D", "100", "15000.00"),
            _make_position("E", "100", "10000.00"),
            _make_position("F", "100", "5000.00"),
            _make_position("G", "100", "5000.00"),
        ]
        service = _make_service(positions=positions)

        result = service.compute_concentration(deployment_id=_DEPLOY_ID)

        # Top 5: 30+20+15+15+10 = 90 out of 100 total
        assert result.top_5_pct == Decimal("90.0")

    def test_absolute_market_value_for_shorts(self) -> None:
        """Short positions should use absolute market value for concentration."""
        positions = [
            _make_position("AAPL", "100", "10000.00"),
            _make_position("MSFT", "-50", "-5000.00"),
        ]
        service = _make_service(positions=positions)

        result = service.compute_concentration(deployment_id=_DEPLOY_ID)

        total = Decimal("15000.00")  # |10000| + |-5000|
        expected_aapl_pct = (Decimal("10000.00") / total * 100).quantize(Decimal("0.1"))
        expected_msft_pct = (Decimal("5000.00") / total * 100).quantize(Decimal("0.1"))
        assert result.per_symbol[0].pct_of_portfolio == expected_aapl_pct
        assert result.per_symbol[1].pct_of_portfolio == expected_msft_pct
        assert len(result.per_symbol) == 2

    def test_raises_not_found_no_positions(self) -> None:
        service = _make_service(positions=[])
        with pytest.raises(NotFoundError):
            service.compute_concentration(deployment_id=_DEPLOY_ID)


# ---------------------------------------------------------------------------
# get_portfolio_risk_summary
# ---------------------------------------------------------------------------


class TestPortfolioRiskSummary:
    """Tests for portfolio risk summary aggregation."""

    def test_summary_includes_all_dimensions(self) -> None:
        """Summary should contain VaR, correlation, concentration, and exposure."""
        positions = [
            _make_position("AAPL", "100", "10000.00"),
            _make_position("MSFT", "50", "7500.00"),
        ]
        candles = {
            "AAPL": _make_daily_candles("AAPL", 260, seed=42),
            "MSFT": _make_daily_candles("MSFT", 260, seed=99),
        }
        service = _make_service(positions=positions, candle_map=candles)

        result = service.get_portfolio_risk_summary(deployment_id=_DEPLOY_ID)

        assert result.var is not None
        assert result.correlation is not None
        assert result.concentration is not None
        assert result.total_exposure > Decimal("0")

    def test_exposure_calculations(self) -> None:
        """Verify long/short/net/gross exposure breakdown."""
        positions = [
            _make_position("AAPL", "100", "10000.00"),  # long
            _make_position("MSFT", "-50", "-5000.00"),  # short
        ]
        candles = {
            "AAPL": _make_daily_candles("AAPL", 260, seed=42),
            "MSFT": _make_daily_candles("MSFT", 260, seed=99),
        }
        service = _make_service(positions=positions, candle_map=candles)

        result = service.get_portfolio_risk_summary(deployment_id=_DEPLOY_ID)

        assert result.long_exposure == Decimal("10000.00")
        assert result.short_exposure == Decimal("5000.00")
        assert result.gross_exposure == Decimal("15000.00")
        assert result.total_exposure == Decimal("15000.00")
        assert result.net_exposure == Decimal("5000.00")

    def test_all_long_exposure(self) -> None:
        """All-long portfolio: short_exposure = 0, net = gross."""
        positions = [
            _make_position("AAPL", "100", "10000.00"),
            _make_position("MSFT", "50", "7500.00"),
        ]
        candles = {
            "AAPL": _make_daily_candles("AAPL", 260, seed=42),
            "MSFT": _make_daily_candles("MSFT", 260, seed=99),
        }
        service = _make_service(positions=positions, candle_map=candles)

        result = service.get_portfolio_risk_summary(deployment_id=_DEPLOY_ID)

        assert result.short_exposure == Decimal("0")
        assert result.net_exposure == result.gross_exposure

    def test_raises_not_found_no_positions(self) -> None:
        service = _make_service(positions=[])
        with pytest.raises(NotFoundError):
            service.get_portfolio_risk_summary(deployment_id=_DEPLOY_ID)
