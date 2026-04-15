"""
Unit tests for portfolio risk analytics contracts.

Validates Pydantic models: VaRResult, CorrelationEntry, CorrelationMatrix,
SymbolConcentration, ConcentrationReport, PortfolioRiskSummary.
Tests construction, immutability, validation boundaries, and serialization.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from libs.contracts.risk_analytics import (
    ConcentrationReport,
    CorrelationEntry,
    CorrelationMatrix,
    PortfolioRiskSummary,
    SymbolConcentration,
    VaRMethod,
    VaRResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)


def _make_var_result(**overrides: object) -> VaRResult:
    defaults = {
        "var_95": Decimal("-2500.00"),
        "var_99": Decimal("-4100.00"),
        "cvar_95": Decimal("-3200.00"),
        "cvar_99": Decimal("-5000.00"),
        "method": VaRMethod.HISTORICAL,
        "lookback_days": 252,
        "computed_at": _NOW,
    }
    defaults.update(overrides)
    return VaRResult(**defaults)


def _make_correlation_entry(**overrides: object) -> CorrelationEntry:
    defaults = {
        "symbol_a": "AAPL",
        "symbol_b": "MSFT",
        "correlation": Decimal("0.85"),
        "lookback_days": 252,
    }
    defaults.update(overrides)
    return CorrelationEntry(**defaults)


def _make_concentration_report(**overrides: object) -> ConcentrationReport:
    defaults = {
        "per_symbol": [
            SymbolConcentration(
                symbol="AAPL",
                market_value=Decimal("50000"),
                pct_of_portfolio=Decimal("50"),
            ),
            SymbolConcentration(
                symbol="MSFT",
                market_value=Decimal("50000"),
                pct_of_portfolio=Decimal("50"),
            ),
        ],
        "herfindahl_index": Decimal("5000"),
        "top_5_pct": Decimal("100.0"),
        "computed_at": _NOW,
    }
    defaults.update(overrides)
    return ConcentrationReport(**defaults)


def _make_correlation_matrix(**overrides: object) -> CorrelationMatrix:
    defaults = {
        "symbols": ["AAPL", "MSFT"],
        "entries": [
            CorrelationEntry(
                symbol_a="AAPL", symbol_b="AAPL", correlation=Decimal("1.0"), lookback_days=252
            ),
            CorrelationEntry(
                symbol_a="AAPL", symbol_b="MSFT", correlation=Decimal("0.85"), lookback_days=252
            ),
            CorrelationEntry(
                symbol_a="MSFT", symbol_b="AAPL", correlation=Decimal("0.85"), lookback_days=252
            ),
            CorrelationEntry(
                symbol_a="MSFT", symbol_b="MSFT", correlation=Decimal("1.0"), lookback_days=252
            ),
        ],
        "matrix": [["1.0", "0.85"], ["0.85", "1.0"]],
        "lookback_days": 252,
        "computed_at": _NOW,
    }
    defaults.update(overrides)
    return CorrelationMatrix(**defaults)


# ---------------------------------------------------------------------------
# VaRMethod enum
# ---------------------------------------------------------------------------


class TestVaRMethod:
    """Tests for VaRMethod enum."""

    def test_historical_value(self) -> None:
        assert VaRMethod.HISTORICAL.value == "historical"

    def test_parametric_value(self) -> None:
        assert VaRMethod.PARAMETRIC.value == "parametric"

    def test_from_string(self) -> None:
        assert VaRMethod("historical") is VaRMethod.HISTORICAL
        assert VaRMethod("parametric") is VaRMethod.PARAMETRIC


# ---------------------------------------------------------------------------
# VaRResult
# ---------------------------------------------------------------------------


class TestVaRResult:
    """Tests for VaRResult construction and validation."""

    def test_construction_with_all_fields(self) -> None:
        result = _make_var_result()
        assert result.var_95 == Decimal("-2500.00")
        assert result.var_99 == Decimal("-4100.00")
        assert result.cvar_95 == Decimal("-3200.00")
        assert result.cvar_99 == Decimal("-5000.00")
        assert result.method is VaRMethod.HISTORICAL
        assert result.lookback_days == 252
        assert result.computed_at == _NOW

    def test_frozen_model_rejects_mutation(self) -> None:
        result = _make_var_result()
        with pytest.raises(ValidationError):
            result.var_95 = Decimal("0")  # type: ignore[misc]

    def test_lookback_days_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="lookback_days"):
            _make_var_result(lookback_days=0)

    def test_negative_lookback_days_rejected(self) -> None:
        with pytest.raises(ValidationError, match="lookback_days"):
            _make_var_result(lookback_days=-1)

    def test_parametric_method(self) -> None:
        result = _make_var_result(method=VaRMethod.PARAMETRIC)
        assert result.method is VaRMethod.PARAMETRIC

    def test_default_computed_at_is_utc(self) -> None:
        result = VaRResult(
            var_95=Decimal("-100"),
            var_99=Decimal("-200"),
            cvar_95=Decimal("-150"),
            cvar_99=Decimal("-250"),
            method=VaRMethod.HISTORICAL,
            lookback_days=30,
        )
        assert result.computed_at.tzinfo is not None

    def test_serialization_roundtrip(self) -> None:
        result = _make_var_result()
        data = result.model_dump()
        restored = VaRResult(**data)
        assert restored.var_95 == result.var_95
        assert restored.method == result.method


# ---------------------------------------------------------------------------
# CorrelationEntry
# ---------------------------------------------------------------------------


class TestCorrelationEntry:
    """Tests for CorrelationEntry construction and validation."""

    def test_construction(self) -> None:
        entry = _make_correlation_entry()
        assert entry.symbol_a == "AAPL"
        assert entry.symbol_b == "MSFT"
        assert entry.correlation == Decimal("0.85")
        assert entry.lookback_days == 252

    def test_frozen_model(self) -> None:
        entry = _make_correlation_entry()
        with pytest.raises(ValidationError):
            entry.correlation = Decimal("0")  # type: ignore[misc]

    def test_correlation_bounds_max(self) -> None:
        entry = _make_correlation_entry(correlation=Decimal("1.0"))
        assert entry.correlation == Decimal("1.0")

    def test_correlation_bounds_min(self) -> None:
        entry = _make_correlation_entry(correlation=Decimal("-1.0"))
        assert entry.correlation == Decimal("-1.0")

    def test_correlation_exceeds_max_rejected(self) -> None:
        with pytest.raises(ValidationError, match="correlation"):
            _make_correlation_entry(correlation=Decimal("1.01"))

    def test_correlation_below_min_rejected(self) -> None:
        with pytest.raises(ValidationError, match="correlation"):
            _make_correlation_entry(correlation=Decimal("-1.01"))

    def test_empty_symbol_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_correlation_entry(symbol_a="")


# ---------------------------------------------------------------------------
# CorrelationMatrix
# ---------------------------------------------------------------------------


class TestCorrelationMatrix:
    """Tests for CorrelationMatrix construction and validation."""

    def test_construction(self) -> None:
        matrix = _make_correlation_matrix()
        assert matrix.symbols == ["AAPL", "MSFT"]
        assert len(matrix.entries) == 4
        assert len(matrix.matrix) == 2
        assert matrix.lookback_days == 252

    def test_frozen_model(self) -> None:
        matrix = _make_correlation_matrix()
        with pytest.raises(ValidationError):
            matrix.lookback_days = 100  # type: ignore[misc]

    def test_empty_symbols_rejected(self) -> None:
        with pytest.raises(ValidationError, match="symbols"):
            _make_correlation_matrix(symbols=[])

    def test_serialization_roundtrip(self) -> None:
        matrix = _make_correlation_matrix()
        data = matrix.model_dump()
        restored = CorrelationMatrix(**data)
        assert restored.symbols == matrix.symbols
        assert len(restored.entries) == len(matrix.entries)


# ---------------------------------------------------------------------------
# SymbolConcentration
# ---------------------------------------------------------------------------


class TestSymbolConcentration:
    """Tests for SymbolConcentration construction and validation."""

    def test_construction(self) -> None:
        sc = SymbolConcentration(
            symbol="AAPL",
            market_value=Decimal("25000"),
            pct_of_portfolio=Decimal("25.0"),
        )
        assert sc.symbol == "AAPL"
        assert sc.market_value == Decimal("25000")
        assert sc.pct_of_portfolio == Decimal("25.0")

    def test_frozen_model(self) -> None:
        sc = SymbolConcentration(
            symbol="AAPL",
            market_value=Decimal("25000"),
            pct_of_portfolio=Decimal("25.0"),
        )
        with pytest.raises(ValidationError):
            sc.symbol = "MSFT"  # type: ignore[misc]

    def test_negative_pct_rejected(self) -> None:
        with pytest.raises(ValidationError, match="pct_of_portfolio"):
            SymbolConcentration(
                symbol="AAPL",
                market_value=Decimal("25000"),
                pct_of_portfolio=Decimal("-1"),
            )

    def test_pct_over_100_rejected(self) -> None:
        with pytest.raises(ValidationError, match="pct_of_portfolio"):
            SymbolConcentration(
                symbol="AAPL",
                market_value=Decimal("25000"),
                pct_of_portfolio=Decimal("101"),
            )


# ---------------------------------------------------------------------------
# ConcentrationReport
# ---------------------------------------------------------------------------


class TestConcentrationReport:
    """Tests for ConcentrationReport construction and validation."""

    def test_construction(self) -> None:
        report = _make_concentration_report()
        assert len(report.per_symbol) == 2
        assert report.herfindahl_index == Decimal("5000")
        assert report.top_5_pct == Decimal("100.0")

    def test_single_stock_hhi_10000(self) -> None:
        """Single-stock portfolio has maximum HHI."""
        report = ConcentrationReport(
            per_symbol=[
                SymbolConcentration(
                    symbol="AAPL",
                    market_value=Decimal("100000"),
                    pct_of_portfolio=Decimal("100"),
                ),
            ],
            herfindahl_index=Decimal("10000"),
            top_5_pct=Decimal("100.0"),
            computed_at=_NOW,
        )
        assert report.herfindahl_index == Decimal("10000")

    def test_hhi_exceeds_max_rejected(self) -> None:
        with pytest.raises(ValidationError, match="herfindahl_index"):
            _make_concentration_report(herfindahl_index=Decimal("10001"))

    def test_hhi_negative_rejected(self) -> None:
        with pytest.raises(ValidationError, match="herfindahl_index"):
            _make_concentration_report(herfindahl_index=Decimal("-1"))

    def test_frozen_model(self) -> None:
        report = _make_concentration_report()
        with pytest.raises(ValidationError):
            report.herfindahl_index = Decimal("0")  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        report = _make_concentration_report()
        data = report.model_dump()
        restored = ConcentrationReport(**data)
        assert restored.herfindahl_index == report.herfindahl_index
        assert len(restored.per_symbol) == len(report.per_symbol)


# ---------------------------------------------------------------------------
# PortfolioRiskSummary
# ---------------------------------------------------------------------------


class TestPortfolioRiskSummary:
    """Tests for PortfolioRiskSummary construction and validation."""

    def test_construction(self) -> None:
        summary = PortfolioRiskSummary(
            var=_make_var_result(),
            correlation=_make_correlation_matrix(),
            concentration=_make_concentration_report(),
            total_exposure=Decimal("100000"),
            net_exposure=Decimal("80000"),
            gross_exposure=Decimal("100000"),
            long_exposure=Decimal("90000"),
            short_exposure=Decimal("10000"),
            computed_at=_NOW,
        )
        assert summary.total_exposure == Decimal("100000")
        assert summary.net_exposure == Decimal("80000")
        assert summary.long_exposure == Decimal("90000")
        assert summary.short_exposure == Decimal("10000")

    def test_frozen_model(self) -> None:
        summary = PortfolioRiskSummary(
            var=_make_var_result(),
            correlation=_make_correlation_matrix(),
            concentration=_make_concentration_report(),
            total_exposure=Decimal("100000"),
            net_exposure=Decimal("80000"),
            gross_exposure=Decimal("100000"),
            long_exposure=Decimal("90000"),
            short_exposure=Decimal("10000"),
            computed_at=_NOW,
        )
        with pytest.raises(ValidationError):
            summary.total_exposure = Decimal("0")  # type: ignore[misc]

    def test_negative_long_exposure_rejected(self) -> None:
        with pytest.raises(ValidationError, match="long_exposure"):
            PortfolioRiskSummary(
                var=_make_var_result(),
                correlation=_make_correlation_matrix(),
                concentration=_make_concentration_report(),
                total_exposure=Decimal("100000"),
                net_exposure=Decimal("80000"),
                gross_exposure=Decimal("100000"),
                long_exposure=Decimal("-1"),
                short_exposure=Decimal("10000"),
                computed_at=_NOW,
            )

    def test_negative_short_exposure_rejected(self) -> None:
        with pytest.raises(ValidationError, match="short_exposure"):
            PortfolioRiskSummary(
                var=_make_var_result(),
                correlation=_make_correlation_matrix(),
                concentration=_make_concentration_report(),
                total_exposure=Decimal("100000"),
                net_exposure=Decimal("80000"),
                gross_exposure=Decimal("100000"),
                long_exposure=Decimal("90000"),
                short_exposure=Decimal("-1"),
                computed_at=_NOW,
            )

    def test_serialization_roundtrip(self) -> None:
        summary = PortfolioRiskSummary(
            var=_make_var_result(),
            correlation=_make_correlation_matrix(),
            concentration=_make_concentration_report(),
            total_exposure=Decimal("100000"),
            net_exposure=Decimal("80000"),
            gross_exposure=Decimal("100000"),
            long_exposure=Decimal("90000"),
            short_exposure=Decimal("10000"),
            computed_at=_NOW,
        )
        data = summary.model_dump()
        restored = PortfolioRiskSummary(**data)
        assert restored.total_exposure == summary.total_exposure
        assert restored.var.var_95 == summary.var.var_95
