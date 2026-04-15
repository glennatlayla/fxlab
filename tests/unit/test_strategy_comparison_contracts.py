"""
Unit tests for strategy comparison contracts (Phase 7 — M13).

Verifies:
- StrategyRankingCriteria enum values and count.
- StrategyComparisonRequest validation (min/max deployment IDs).
- StrategyMetrics defaults, custom values, and immutability.
- StrategyRank validation.
- StrategyComparisonResult defaults and computed_at auto-population.

Dependencies:
- libs/contracts/strategy_comparison.py: All comparison contract models.

Example:
    pytest tests/unit/test_strategy_comparison_contracts.py -v
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from libs.contracts.strategy_comparison import (
    StrategyComparisonRequest,
    StrategyComparisonResult,
    StrategyMetrics,
    StrategyRank,
    StrategyRankingCriteria,
)

# ---------------------------------------------------------------------------
# StrategyRankingCriteria
# ---------------------------------------------------------------------------


class TestStrategyRankingCriteria:
    """Tests for StrategyRankingCriteria enum."""

    def test_all_criteria_have_expected_values(self) -> None:
        """All enum members map to expected string values."""
        expected = {
            "SHARPE_RATIO": "sharpe_ratio",
            "SORTINO_RATIO": "sortino_ratio",
            "CALMAR_RATIO": "calmar_ratio",
            "MAX_DRAWDOWN": "max_drawdown",
            "WIN_RATE": "win_rate",
            "PROFIT_FACTOR": "profit_factor",
            "NET_PNL": "net_pnl",
            "RISK_ADJUSTED_RETURN": "risk_adjusted_return",
        }
        for name, value in expected.items():
            assert StrategyRankingCriteria[name].value == value

    def test_criteria_count(self) -> None:
        """Exactly 8 criteria are defined."""
        assert len(StrategyRankingCriteria) == 8


# ---------------------------------------------------------------------------
# StrategyComparisonRequest
# ---------------------------------------------------------------------------


class TestStrategyComparisonRequest:
    """Tests for StrategyComparisonRequest frozen model."""

    def test_request_with_defaults(self) -> None:
        """Request accepts deployment IDs and applies defaults."""
        request = StrategyComparisonRequest(
            deployment_ids=["deploy_1", "deploy_2"],
        )
        assert request.date_from is None
        assert request.date_to is None
        assert request.ranking_criteria == StrategyRankingCriteria.SHARPE_RATIO

    def test_request_with_custom_values(self) -> None:
        """Request accepts all custom values."""
        request = StrategyComparisonRequest(
            deployment_ids=["d1", "d2", "d3"],
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
            ranking_criteria=StrategyRankingCriteria.SORTINO_RATIO,
        )
        assert len(request.deployment_ids) == 3
        assert request.ranking_criteria == StrategyRankingCriteria.SORTINO_RATIO

    def test_request_rejects_single_deployment(self) -> None:
        """At least 2 deployments are required."""
        with pytest.raises(ValidationError, match="deployment_ids"):
            StrategyComparisonRequest(deployment_ids=["only_one"])

    def test_request_rejects_empty_deployments(self) -> None:
        """Empty deployment list is rejected."""
        with pytest.raises(ValidationError, match="deployment_ids"):
            StrategyComparisonRequest(deployment_ids=[])

    def test_request_is_frozen(self) -> None:
        """Request is immutable."""
        request = StrategyComparisonRequest(
            deployment_ids=["d1", "d2"],
        )
        with pytest.raises(ValidationError):
            request.ranking_criteria = StrategyRankingCriteria.NET_PNL  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StrategyMetrics
# ---------------------------------------------------------------------------


class TestStrategyMetrics:
    """Tests for StrategyMetrics frozen model."""

    def test_metrics_with_defaults(self) -> None:
        """Metrics accepts deployment_id and applies defaults."""
        m = StrategyMetrics(deployment_id="deploy_1")
        assert m.net_pnl == Decimal("0")
        assert m.sharpe_ratio == Decimal("0")
        assert m.sortino_ratio == Decimal("0")
        assert m.calmar_ratio == Decimal("0")
        assert m.max_drawdown_pct == Decimal("0")
        assert m.profit_factor == Decimal("0")
        assert m.risk_adjusted_return == Decimal("0")
        assert m.strategy_name == ""

    def test_metrics_with_custom_values(self) -> None:
        """Metrics accepts all custom values."""
        m = StrategyMetrics(
            deployment_id="deploy_1",
            strategy_name="Alpha Strategy",
            net_pnl=Decimal("50000"),
            total_trades=100,
            winning_trades=60,
            win_rate=Decimal("0.60"),
            sharpe_ratio=Decimal("1.50"),
            sortino_ratio=Decimal("2.10"),
            calmar_ratio=Decimal("3.00"),
            max_drawdown_pct=Decimal("-8.50"),
            profit_factor=Decimal("1.80"),
            risk_adjusted_return=Decimal("23.81"),
            annualized_return_pct=Decimal("15.00"),
            total_commission=Decimal("500"),
        )
        assert m.strategy_name == "Alpha Strategy"
        assert m.net_pnl == Decimal("50000")
        assert m.sortino_ratio == Decimal("2.10")

    def test_metrics_is_frozen(self) -> None:
        """Metrics is immutable."""
        m = StrategyMetrics(deployment_id="deploy_1")
        with pytest.raises(ValidationError):
            m.net_pnl = Decimal("999")  # type: ignore[misc]

    def test_metrics_rejects_positive_drawdown(self) -> None:
        """Max drawdown must be <= 0."""
        with pytest.raises(ValidationError, match="max_drawdown_pct"):
            StrategyMetrics(
                deployment_id="deploy_1",
                max_drawdown_pct=Decimal("5.0"),
            )

    def test_metrics_rejects_win_rate_over_one(self) -> None:
        """Win rate must be between 0 and 1."""
        with pytest.raises(ValidationError, match="win_rate"):
            StrategyMetrics(
                deployment_id="deploy_1",
                win_rate=Decimal("1.5"),
            )


# ---------------------------------------------------------------------------
# StrategyRank
# ---------------------------------------------------------------------------


class TestStrategyRank:
    """Tests for StrategyRank frozen model."""

    def test_rank_basic(self) -> None:
        """Rank wraps metrics with a position."""
        m = StrategyMetrics(deployment_id="deploy_1")
        rank = StrategyRank(rank=1, metrics=m)
        assert rank.rank == 1
        assert rank.metrics.deployment_id == "deploy_1"

    def test_rank_rejects_zero(self) -> None:
        """Rank must be >= 1."""
        m = StrategyMetrics(deployment_id="deploy_1")
        with pytest.raises(ValidationError, match="rank"):
            StrategyRank(rank=0, metrics=m)


# ---------------------------------------------------------------------------
# StrategyComparisonResult
# ---------------------------------------------------------------------------


class TestStrategyComparisonResult:
    """Tests for StrategyComparisonResult frozen model."""

    def test_result_with_defaults(self) -> None:
        """Result applies defaults."""
        result = StrategyComparisonResult()
        assert result.rankings == []
        assert result.comparison_matrix == []
        assert result.ranking_criteria == StrategyRankingCriteria.SHARPE_RATIO
        assert result.computed_at is not None

    def test_result_computed_at_auto_populated(self) -> None:
        """computed_at is auto-set to current UTC time."""
        before = datetime.now(timezone.utc)
        result = StrategyComparisonResult()
        after = datetime.now(timezone.utc)
        assert before <= result.computed_at <= after

    def test_result_serialization_roundtrip(self) -> None:
        """Result survives model_dump → model_validate roundtrip."""
        m1 = StrategyMetrics(deployment_id="d1", sharpe_ratio=Decimal("1.5"))
        m2 = StrategyMetrics(deployment_id="d2", sharpe_ratio=Decimal("0.8"))
        result = StrategyComparisonResult(
            rankings=[
                StrategyRank(rank=1, metrics=m1),
                StrategyRank(rank=2, metrics=m2),
            ],
            ranking_criteria=StrategyRankingCriteria.SHARPE_RATIO,
            comparison_matrix=[m1, m2],
        )
        data = result.model_dump()
        restored = StrategyComparisonResult.model_validate(data)
        assert len(restored.rankings) == 2
        assert restored.rankings[0].rank == 1
