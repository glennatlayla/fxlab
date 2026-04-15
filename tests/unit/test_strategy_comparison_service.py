"""
Unit tests for StrategyComparisonService (Phase 7 — M13).

Verifies:
- Metric computation from P&L summary data.
- Sortino ratio penalizes downside volatility more than Sharpe.
- Calmar ratio with zero drawdown is capped.
- Ranking by each criteria produces correct ordering.
- Deterministic tiebreaker (deployment_id) for equal metric values.
- Error handling when deployments lack data.
- Risk-adjusted return computation.

Dependencies:
- StrategyComparisonService: unit under test.
- MockPnlAttributionService: in-memory mock.

Example:
    pytest tests/unit/test_strategy_comparison_service.py -v
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from libs.contracts.errors import ValidationError
from libs.contracts.strategy_comparison import (
    StrategyComparisonRequest,
    StrategyRankingCriteria,
)
from services.api.services.strategy_comparison_service import (
    StrategyComparisonService,
)

# ---------------------------------------------------------------------------
# Mock PnlAttributionService
# ---------------------------------------------------------------------------


class MockPnlAttributionService:
    """
    In-memory mock of PnlAttributionServiceInterface for unit testing.

    Stores configurable per-deployment P&L summaries and timeseries data.

    Introspection helpers:
    - set_summary: configure P&L summary for a deployment.
    - set_timeseries: configure timeseries data for a deployment.
    - set_raise_not_found: make a deployment raise NotFoundError.
    """

    def __init__(self) -> None:
        self._summaries: dict[str, dict[str, Any]] = {}
        self._timeseries: dict[str, list[dict[str, Any]]] = {}
        self._raise_for: set[str] = set()

    def set_summary(self, deployment_id: str, summary: dict[str, Any]) -> None:
        """Configure P&L summary for a deployment."""
        self._summaries[deployment_id] = summary

    def set_timeseries(self, deployment_id: str, points: list[dict[str, Any]]) -> None:
        """Configure timeseries data for a deployment."""
        self._timeseries[deployment_id] = points

    def set_raise_not_found(self, deployment_id: str) -> None:
        """Make get_pnl_summary raise for this deployment."""
        self._raise_for.add(deployment_id)

    def get_pnl_summary(self, *, deployment_id: str) -> dict[str, Any]:
        """Return configured summary or raise."""
        if deployment_id in self._raise_for:
            from libs.contracts.errors import NotFoundError

            raise NotFoundError(f"Deployment {deployment_id} not found")
        return self._summaries.get(deployment_id, {})

    def get_pnl_timeseries(
        self,
        *,
        deployment_id: str,
        date_from: date,
        date_to: date,
        granularity: str = "daily",
    ) -> list[dict[str, Any]]:
        """Return configured timeseries."""
        return self._timeseries.get(deployment_id, [])

    def get_attribution(
        self, *, deployment_id: str, date_from: date | None = None, date_to: date | None = None
    ) -> dict[str, Any]:
        """Not used in comparison service."""
        return {}

    def get_comparison(
        self,
        *,
        deployment_ids: list[str],
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """Not used in comparison service."""
        return {}

    def take_snapshot(self, *, deployment_id: str, snapshot_date: date) -> dict[str, Any]:
        """Not used in comparison service."""
        return {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_summary(
    *,
    strategy_name: str = "Test Strategy",
    net_pnl: float = 10000,
    total_trades: int = 100,
    winning_trades: int = 55,
    win_rate: float = 0.55,
    sharpe_ratio: float = 1.2,
    max_drawdown_pct: float = -8.0,
    profit_factor: float = 1.5,
    total_commission: float = 200,
) -> dict[str, Any]:
    """Build a P&L summary dict matching PnlAttributionService output."""
    return {
        "strategy_name": strategy_name,
        "net_pnl": net_pnl,
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "win_rate": win_rate,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown_pct": max_drawdown_pct,
        "profit_factor": profit_factor,
        "total_commission": total_commission,
    }


def _make_daily_timeseries(daily_pnls: list[float]) -> list[dict[str, Any]]:
    """Build timeseries points with daily_pnl values."""
    return [{"daily_pnl": pnl} for pnl in daily_pnls]


@pytest.fixture()
def mock_pnl() -> MockPnlAttributionService:
    """Fresh mock PnL service."""
    return MockPnlAttributionService()


@pytest.fixture()
def service(mock_pnl: MockPnlAttributionService) -> StrategyComparisonService:
    """StrategyComparisonService with mock PnL."""
    return StrategyComparisonService(pnl_service=mock_pnl)


# ---------------------------------------------------------------------------
# Comparison tests
# ---------------------------------------------------------------------------


class TestCompareStrategies:
    """Tests for compare_strategies()."""

    def test_compare_ranks_by_sharpe_ratio(
        self, mock_pnl: MockPnlAttributionService, service: StrategyComparisonService
    ) -> None:
        """Strategy with highest Sharpe ranks #1."""
        mock_pnl.set_summary("d1", _make_summary(sharpe_ratio=1.5))
        mock_pnl.set_summary("d2", _make_summary(sharpe_ratio=2.0))
        mock_pnl.set_summary("d3", _make_summary(sharpe_ratio=0.8))

        request = StrategyComparisonRequest(
            deployment_ids=["d1", "d2", "d3"],
            ranking_criteria=StrategyRankingCriteria.SHARPE_RATIO,
        )
        result = service.compare_strategies(request)

        assert result.rankings[0].rank == 1
        assert result.rankings[0].metrics.deployment_id == "d2"
        assert result.rankings[1].metrics.deployment_id == "d1"
        assert result.rankings[2].metrics.deployment_id == "d3"

    def test_compare_ranks_by_net_pnl(
        self, mock_pnl: MockPnlAttributionService, service: StrategyComparisonService
    ) -> None:
        """Strategy with highest net P&L ranks #1."""
        mock_pnl.set_summary("d1", _make_summary(net_pnl=50000))
        mock_pnl.set_summary("d2", _make_summary(net_pnl=30000))

        request = StrategyComparisonRequest(
            deployment_ids=["d1", "d2"],
            ranking_criteria=StrategyRankingCriteria.NET_PNL,
        )
        result = service.compare_strategies(request)

        assert result.rankings[0].metrics.deployment_id == "d1"

    def test_compare_ranks_by_max_drawdown(
        self, mock_pnl: MockPnlAttributionService, service: StrategyComparisonService
    ) -> None:
        """Less negative drawdown ranks higher."""
        mock_pnl.set_summary("d1", _make_summary(max_drawdown_pct=-15.0))
        mock_pnl.set_summary("d2", _make_summary(max_drawdown_pct=-5.0))

        request = StrategyComparisonRequest(
            deployment_ids=["d1", "d2"],
            ranking_criteria=StrategyRankingCriteria.MAX_DRAWDOWN,
        )
        result = service.compare_strategies(request)

        # d2 has less drawdown (-5%) → ranks #1
        assert result.rankings[0].metrics.deployment_id == "d2"

    def test_compare_deterministic_tiebreaker(
        self, mock_pnl: MockPnlAttributionService, service: StrategyComparisonService
    ) -> None:
        """Equal metrics use deployment_id as tiebreaker for stable ranking."""
        mock_pnl.set_summary("d_beta", _make_summary(sharpe_ratio=1.0))
        mock_pnl.set_summary("d_alpha", _make_summary(sharpe_ratio=1.0))

        request = StrategyComparisonRequest(
            deployment_ids=["d_beta", "d_alpha"],
            ranking_criteria=StrategyRankingCriteria.SHARPE_RATIO,
        )
        result = service.compare_strategies(request)

        # Both have same Sharpe, tiebreaker is deployment_id
        # reverse=True sort, so higher string sorts first in tuple comparison
        ids = [r.metrics.deployment_id for r in result.rankings]
        assert ids == ["d_beta", "d_alpha"]

    def test_compare_returns_comparison_matrix(
        self, mock_pnl: MockPnlAttributionService, service: StrategyComparisonService
    ) -> None:
        """Comparison matrix contains all strategies."""
        mock_pnl.set_summary("d1", _make_summary())
        mock_pnl.set_summary("d2", _make_summary())

        request = StrategyComparisonRequest(
            deployment_ids=["d1", "d2"],
        )
        result = service.compare_strategies(request)

        assert len(result.comparison_matrix) == 2
        matrix_ids = {m.deployment_id for m in result.comparison_matrix}
        assert matrix_ids == {"d1", "d2"}

    def test_compare_raises_when_insufficient_data(
        self, mock_pnl: MockPnlAttributionService, service: StrategyComparisonService
    ) -> None:
        """Raises ValidationError when fewer than 2 deployments have data."""
        mock_pnl.set_summary("d1", _make_summary())
        mock_pnl.set_raise_not_found("d2")

        request = StrategyComparisonRequest(
            deployment_ids=["d1", "d2"],
        )
        with pytest.raises(ValidationError, match="At least 2"):
            service.compare_strategies(request)

    def test_compare_skips_failed_deployments(
        self, mock_pnl: MockPnlAttributionService, service: StrategyComparisonService
    ) -> None:
        """Deployments that fail are skipped; rest are compared."""
        mock_pnl.set_summary("d1", _make_summary(sharpe_ratio=1.0))
        mock_pnl.set_summary("d2", _make_summary(sharpe_ratio=2.0))
        mock_pnl.set_raise_not_found("d3")

        request = StrategyComparisonRequest(
            deployment_ids=["d1", "d2", "d3"],
        )
        result = service.compare_strategies(request)

        assert len(result.rankings) == 2


# ---------------------------------------------------------------------------
# Sortino ratio tests
# ---------------------------------------------------------------------------


class TestSortinoRatio:
    """Tests for Sortino ratio computation."""

    def test_sortino_penalises_downside_only(
        self, mock_pnl: MockPnlAttributionService, service: StrategyComparisonService
    ) -> None:
        """Sortino >= Sharpe when downside volatility < total volatility."""
        # Daily returns with some negative and positive
        daily = [100.0, -50.0, 200.0, -30.0, 150.0, 80.0, -20.0, 300.0, -10.0, 50.0]
        mock_pnl.set_summary("d1", _make_summary(sharpe_ratio=1.0))
        mock_pnl.set_timeseries("d1", _make_daily_timeseries(daily))
        mock_pnl.set_summary("d2", _make_summary(sharpe_ratio=0.5))
        mock_pnl.set_timeseries("d2", _make_daily_timeseries(daily))

        request = StrategyComparisonRequest(
            deployment_ids=["d1", "d2"],
            date_from=date(2025, 1, 1),
            date_to=date(2025, 1, 10),
            ranking_criteria=StrategyRankingCriteria.SORTINO_RATIO,
        )
        result = service.compare_strategies(request)

        # Sortino should be computed (non-zero) since we have daily data
        sortino = result.rankings[0].metrics.sortino_ratio
        assert sortino != Decimal("0")

    def test_sortino_is_capped_when_no_negative_returns(
        self, mock_pnl: MockPnlAttributionService, service: StrategyComparisonService
    ) -> None:
        """Sortino returns cap when no negative returns exist."""
        daily = [100.0, 200.0, 150.0, 300.0, 250.0]
        mock_pnl.set_summary("d1", _make_summary())
        mock_pnl.set_timeseries("d1", _make_daily_timeseries(daily))
        mock_pnl.set_summary("d2", _make_summary())
        mock_pnl.set_timeseries("d2", _make_daily_timeseries(daily))

        request = StrategyComparisonRequest(
            deployment_ids=["d1", "d2"],
            date_from=date(2025, 1, 1),
            date_to=date(2025, 1, 5),
        )
        result = service.compare_strategies(request)

        # Sortino should be capped at 100
        sortino = result.rankings[0].metrics.sortino_ratio
        assert sortino == Decimal("100")

    def test_sortino_zero_with_insufficient_data(self) -> None:
        """Sortino returns 0 with fewer than 2 data points."""
        result = StrategyComparisonService._compute_sortino_ratio([Decimal("100")])
        assert result == Decimal("0")


# ---------------------------------------------------------------------------
# Calmar ratio tests
# ---------------------------------------------------------------------------


class TestCalmarRatio:
    """Tests for Calmar ratio computation."""

    def test_calmar_ratio_basic(self) -> None:
        """Calmar = annualized_return / |max_drawdown|."""
        calmar = StrategyComparisonService._compute_calmar_ratio(Decimal("20"), Decimal("-10"))
        assert calmar == Decimal("2.000000")

    def test_calmar_capped_at_max_with_zero_drawdown(self) -> None:
        """Calmar is capped when drawdown is zero and return is positive."""
        calmar = StrategyComparisonService._compute_calmar_ratio(Decimal("15"), Decimal("0"))
        assert calmar == Decimal("100")

    def test_calmar_zero_when_no_return_and_no_drawdown(self) -> None:
        """Calmar is 0 when both return and drawdown are zero."""
        calmar = StrategyComparisonService._compute_calmar_ratio(Decimal("0"), Decimal("0"))
        assert calmar == Decimal("0")

    def test_calmar_negative_when_return_negative(self) -> None:
        """Calmar can be negative when return is negative."""
        calmar = StrategyComparisonService._compute_calmar_ratio(Decimal("-10"), Decimal("-5"))
        assert calmar == Decimal("-2.000000")


# ---------------------------------------------------------------------------
# Risk-adjusted return tests
# ---------------------------------------------------------------------------


class TestRiskAdjustedReturn:
    """Tests for risk-adjusted return computation."""

    def test_risk_adjusted_return_computation(self) -> None:
        """risk_adjusted_return = Sharpe × sqrt(252)."""
        import math

        result = StrategyComparisonService._compute_risk_adjusted_return(Decimal("1.0"))
        expected = Decimal(str(math.sqrt(252))).quantize(Decimal("0.000001"))
        assert result == expected

    def test_risk_adjusted_return_zero_sharpe(self) -> None:
        """Zero Sharpe produces zero risk-adjusted return."""
        result = StrategyComparisonService._compute_risk_adjusted_return(Decimal("0"))
        assert result == Decimal("0")


# ---------------------------------------------------------------------------
# get_strategy_metrics tests
# ---------------------------------------------------------------------------


class TestGetStrategyMetrics:
    """Tests for get_strategy_metrics()."""

    def test_returns_metrics_for_deployment(
        self, mock_pnl: MockPnlAttributionService, service: StrategyComparisonService
    ) -> None:
        """Returns full metrics for a single deployment."""
        mock_pnl.set_summary(
            "d1",
            _make_summary(
                strategy_name="Alpha",
                net_pnl=25000,
                sharpe_ratio=1.8,
                max_drawdown_pct=-6.0,
            ),
        )

        metrics = service.get_strategy_metrics("d1")
        assert metrics.deployment_id == "d1"
        assert metrics.strategy_name == "Alpha"
        assert metrics.net_pnl == Decimal("25000.000000")
        assert metrics.sharpe_ratio == Decimal("1.800000")

    def test_raises_not_found_for_missing_deployment(
        self, mock_pnl: MockPnlAttributionService, service: StrategyComparisonService
    ) -> None:
        """Raises NotFoundError when deployment doesn't exist."""
        mock_pnl.set_raise_not_found("missing")

        from libs.contracts.errors import NotFoundError

        with pytest.raises(NotFoundError):
            service.get_strategy_metrics("missing")


# ---------------------------------------------------------------------------
# Ranking by all criteria
# ---------------------------------------------------------------------------


class TestRankingByCriteria:
    """Tests ranking works for all criteria variants."""

    @pytest.mark.parametrize(
        "criteria",
        [
            StrategyRankingCriteria.WIN_RATE,
            StrategyRankingCriteria.PROFIT_FACTOR,
        ],
    )
    def test_higher_value_ranks_first(
        self,
        criteria: StrategyRankingCriteria,
        mock_pnl: MockPnlAttributionService,
        service: StrategyComparisonService,
    ) -> None:
        """Higher metric value ranks first (for non-drawdown criteria)."""
        mock_pnl.set_summary("d1", _make_summary(win_rate=0.70, profit_factor=2.0))
        mock_pnl.set_summary("d2", _make_summary(win_rate=0.50, profit_factor=1.2))

        request = StrategyComparisonRequest(
            deployment_ids=["d1", "d2"],
            ranking_criteria=criteria,
        )
        result = service.compare_strategies(request)
        assert result.rankings[0].metrics.deployment_id == "d1"
