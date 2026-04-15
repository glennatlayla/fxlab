"""
Unit tests for PositionSizingService.

Validates all sizing methods: FIXED, ATR_BASED, KELLY, RISK_PARITY,
EQUAL_WEIGHT. Tests known-input/known-output calculations, risk gate
caps, and error handling.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.errors import ValidationError
from libs.contracts.position_sizing import SizingMethod, SizingRequest, SizingResult
from services.api.services.position_sizing_service import PositionSizingService

# ---------------------------------------------------------------------------
# Service factory
# ---------------------------------------------------------------------------


def _service() -> PositionSizingService:
    return PositionSizingService()


# ---------------------------------------------------------------------------
# FIXED method
# ---------------------------------------------------------------------------


class TestFixedSizing:
    """Tests for FIXED sizing method."""

    def test_uses_max_position_size_when_set(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.FIXED,
            account_equity=Decimal("100000"),
            current_price=Decimal("175.00"),
            max_position_size=Decimal("500"),
        )
        result = _service().compute_size(request)

        assert result.recommended_quantity == Decimal("500")
        assert result.method_used is SizingMethod.FIXED
        assert "max_position_size" in result.reasoning

    def test_falls_back_to_risk_pct_without_max(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.FIXED,
            risk_per_trade_pct=Decimal("2.0"),
            account_equity=Decimal("100000"),
            current_price=Decimal("100.00"),
        )
        result = _service().compute_size(request)

        # 2% of 100000 = 2000, at $100/share = 20 shares
        assert result.recommended_quantity == Decimal("20")
        assert result.risk_amount == Decimal("2000.00")


# ---------------------------------------------------------------------------
# ATR_BASED method
# ---------------------------------------------------------------------------


class TestATRBasedSizing:
    """Tests for ATR_BASED sizing method."""

    def test_basic_atr_calculation(self) -> None:
        """quantity = risk_budget / (ATR × multiplier)."""
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.ATR_BASED,
            risk_per_trade_pct=Decimal("2.0"),
            account_equity=Decimal("100000"),
            atr_value=Decimal("3.50"),
            atr_multiplier=Decimal("2.0"),
            current_price=Decimal("175.00"),
        )
        result = _service().compute_size(request)

        # risk = 2% * 100000 = 2000
        # stop_distance = 3.50 * 2.0 = 7.0
        # quantity = 2000 / 7.0 = 285 (rounded down)
        assert result.recommended_quantity == Decimal("285")
        assert result.method_used is SizingMethod.ATR_BASED
        assert result.stop_loss_price is not None

    def test_high_atr_reduces_position(self) -> None:
        """Doubling ATR should halve the position size."""
        base_req = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.ATR_BASED,
            risk_per_trade_pct=Decimal("2.0"),
            account_equity=Decimal("100000"),
            atr_value=Decimal("3.50"),
            atr_multiplier=Decimal("2.0"),
            current_price=Decimal("175.00"),
        )
        high_atr_req = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.ATR_BASED,
            risk_per_trade_pct=Decimal("2.0"),
            account_equity=Decimal("100000"),
            atr_value=Decimal("7.00"),
            atr_multiplier=Decimal("2.0"),
            current_price=Decimal("175.00"),
        )

        base_result = _service().compute_size(base_req)
        high_result = _service().compute_size(high_atr_req)

        # Doubling ATR halves quantity (within rounding)
        assert high_result.recommended_quantity <= base_result.recommended_quantity / 2 + 1

    def test_buy_stop_loss_below_price(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.ATR_BASED,
            account_equity=Decimal("100000"),
            atr_value=Decimal("5.00"),
            atr_multiplier=Decimal("2.0"),
            current_price=Decimal("175.00"),
        )
        result = _service().compute_size(request)

        # stop = 175 - (5 * 2) = 165
        assert result.stop_loss_price == Decimal("165.00")

    def test_sell_stop_loss_above_price(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="sell",
            method=SizingMethod.ATR_BASED,
            account_equity=Decimal("100000"),
            atr_value=Decimal("5.00"),
            atr_multiplier=Decimal("2.0"),
            current_price=Decimal("175.00"),
        )
        result = _service().compute_size(request)

        # stop = 175 + (5 * 2) = 185
        assert result.stop_loss_price == Decimal("185.00")

    def test_risk_gate_cap_applied(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.ATR_BASED,
            risk_per_trade_pct=Decimal("5.0"),
            account_equity=Decimal("1000000"),
            atr_value=Decimal("1.00"),
            atr_multiplier=Decimal("1.0"),
            current_price=Decimal("100.00"),
            max_position_size=Decimal("100"),
        )
        result = _service().compute_size(request)

        # Uncapped: 50000 / 1.0 = 50000, but capped at 100
        assert result.recommended_quantity == Decimal("100")
        assert result.was_capped is True

    def test_raises_without_atr(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.ATR_BASED,
            account_equity=Decimal("100000"),
            current_price=Decimal("175.00"),
        )
        with pytest.raises(ValidationError, match="atr_value"):
            _service().compute_size(request)


# ---------------------------------------------------------------------------
# KELLY method
# ---------------------------------------------------------------------------


class TestKellySizing:
    """Tests for KELLY sizing method."""

    def test_known_kelly_calculation(self) -> None:
        """W=0.6, R=2.0 → f*=0.6-(0.4/2.0)=0.40, half=0.20."""
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.KELLY,
            account_equity=Decimal("100000"),
            current_price=Decimal("100.00"),
            win_rate=Decimal("0.6"),
            avg_win_loss_ratio=Decimal("2.0"),
        )
        result = _service().compute_size(request)

        # Kelly = 0.6 - 0.4/2.0 = 0.40
        # Half-Kelly = 0.20
        # Allocation = 100000 * 0.20 = 20000
        # At $100/share = 200 shares
        assert result.recommended_quantity == Decimal("200")
        assert result.risk_amount == Decimal("20000.00")

    def test_kelly_capped_at_half(self) -> None:
        """High win rate should still cap at half-Kelly."""
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.KELLY,
            account_equity=Decimal("100000"),
            current_price=Decimal("100.00"),
            win_rate=Decimal("0.95"),
            avg_win_loss_ratio=Decimal("10.0"),
        )
        result = _service().compute_size(request)

        # Kelly = 0.95 - 0.05/10 = 0.945, capped at 0.5
        # Half-Kelly = 0.25
        # Allocation = 25000, 250 shares
        assert result.recommended_quantity == Decimal("250")

    def test_negative_kelly_gives_zero(self) -> None:
        """Negative Kelly (losing strategy) should give zero position."""
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.KELLY,
            account_equity=Decimal("100000"),
            current_price=Decimal("100.00"),
            win_rate=Decimal("0.2"),
            avg_win_loss_ratio=Decimal("0.5"),
        )
        result = _service().compute_size(request)

        # Kelly = 0.2 - 0.8/0.5 = 0.2 - 1.6 = -1.4, clamped to 0
        assert result.recommended_quantity == Decimal("0")

    def test_raises_without_win_rate(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.KELLY,
            account_equity=Decimal("100000"),
            avg_win_loss_ratio=Decimal("2.0"),
        )
        with pytest.raises(ValidationError, match="win_rate"):
            _service().compute_size(request)

    def test_raises_without_ratio(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.KELLY,
            account_equity=Decimal("100000"),
            win_rate=Decimal("0.6"),
        )
        with pytest.raises(ValidationError, match="avg_win_loss_ratio"):
            _service().compute_size(request)


# ---------------------------------------------------------------------------
# EQUAL_WEIGHT method
# ---------------------------------------------------------------------------


class TestEqualWeightSizing:
    """Tests for EQUAL_WEIGHT sizing method."""

    def test_ten_positions_each_gets_10_pct(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.EQUAL_WEIGHT,
            account_equity=Decimal("100000"),
            current_price=Decimal("100.00"),
            total_positions=10,
        )
        result = _service().compute_size(request)

        # 100000 / 10 = 10000 per position, at $100 = 100 shares
        assert result.recommended_quantity == Decimal("100")
        assert result.recommended_value == Decimal("10000.00")

    def test_single_position_full_allocation(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.EQUAL_WEIGHT,
            account_equity=Decimal("50000"),
            current_price=Decimal("250.00"),
            total_positions=1,
        )
        result = _service().compute_size(request)

        # 50000 / 1 = 50000, at $250 = 200 shares
        assert result.recommended_quantity == Decimal("200")

    def test_risk_gate_cap(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.EQUAL_WEIGHT,
            account_equity=Decimal("100000"),
            current_price=Decimal("100.00"),
            total_positions=2,
            max_position_size=Decimal("100"),
        )
        result = _service().compute_size(request)

        # 100000 / 2 = 50000, at $100 = 500, capped at 100
        assert result.recommended_quantity == Decimal("100")
        assert result.was_capped is True


# ---------------------------------------------------------------------------
# RISK_PARITY method
# ---------------------------------------------------------------------------


class TestRiskParitySizing:
    """Tests for RISK_PARITY sizing method."""

    def test_falls_back_to_equal_weight_without_atr(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.RISK_PARITY,
            risk_per_trade_pct=Decimal("2.0"),
            account_equity=Decimal("100000"),
            current_price=Decimal("100.00"),
            total_positions=5,
        )
        result = _service().compute_size(request)

        # Without ATR, falls back to equal weight
        # But note risk parity uses risk budget, not full equity
        assert result.recommended_quantity > Decimal("0")
        assert result.method_used is SizingMethod.RISK_PARITY

    def test_with_atr_data(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.RISK_PARITY,
            risk_per_trade_pct=Decimal("2.0"),
            account_equity=Decimal("100000"),
            current_price=Decimal("100.00"),
            atr_value=Decimal("3.00"),
            total_positions=5,
        )
        result = _service().compute_size(request)

        # risk budget = 2% * 100000 = 2000
        # per position = 2000 / 5 = 400, at $100 = 4 shares
        assert result.recommended_quantity == Decimal("4")


# ---------------------------------------------------------------------------
# get_available_methods
# ---------------------------------------------------------------------------


class TestGetAvailableMethods:
    """Tests for get_available_methods()."""

    def test_returns_all_methods(self) -> None:
        methods = _service().get_available_methods()
        assert len(methods) == 5
        assert SizingMethod.FIXED in methods
        assert SizingMethod.ATR_BASED in methods
        assert SizingMethod.KELLY in methods
        assert SizingMethod.RISK_PARITY in methods
        assert SizingMethod.EQUAL_WEIGHT in methods


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestSizingContracts:
    """Tests for position sizing Pydantic contracts."""

    def test_sizing_request_frozen(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.FIXED,
            account_equity=Decimal("100000"),
        )
        with pytest.raises(PydanticValidationError):
            request.symbol = "MSFT"  # type: ignore[misc]

    def test_sizing_result_frozen(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        result = SizingResult(
            recommended_quantity=Decimal("100"),
            recommended_value=Decimal("10000"),
            method_used=SizingMethod.FIXED,
            reasoning="Test",
        )
        with pytest.raises(PydanticValidationError):
            result.recommended_quantity = Decimal("0")  # type: ignore[misc]

    def test_invalid_side_rejected(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError, match="side"):
            SizingRequest(
                symbol="AAPL",
                side="hold",
                method=SizingMethod.FIXED,
                account_equity=Decimal("100000"),
            )

    def test_negative_equity_rejected(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError, match="account_equity"):
            SizingRequest(
                symbol="AAPL",
                side="buy",
                method=SizingMethod.FIXED,
                account_equity=Decimal("-100"),
            )

    def test_serialization_roundtrip(self) -> None:
        request = SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.ATR_BASED,
            account_equity=Decimal("100000"),
            atr_value=Decimal("3.50"),
        )
        data = request.model_dump()
        restored = SizingRequest(**data)
        assert restored.symbol == request.symbol
        assert restored.method == request.method
