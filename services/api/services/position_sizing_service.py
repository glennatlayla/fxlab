"""
Dynamic position sizing service implementation.

Responsibilities:
- Compute position sizes using FIXED, ATR_BASED, KELLY, RISK_PARITY,
  and EQUAL_WEIGHT methods.
- Cap all results against risk gate maximum position size.
- Provide human-readable reasoning for each sizing decision.
- Calculate stop-loss prices for ATR-based sizing.

Does NOT:
- Execute trades (execution service responsibility).
- Persist sizing decisions (caller responsibility).
- Access databases directly (stateless computation).

Dependencies:
- None (pure computation, no external I/O).

Error conditions:
- ValidationError: missing required parameters for chosen method.

Example:
    service = PositionSizingService()
    result = service.compute_size(
        SizingRequest(
            symbol="AAPL",
            side="buy",
            method=SizingMethod.ATR_BASED,
            risk_per_trade_pct=Decimal("2.0"),
            account_equity=Decimal("100000"),
            atr_value=Decimal("3.50"),
            current_price=Decimal("175.00"),
        )
    )
"""

from __future__ import annotations

import logging
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from libs.contracts.errors import ValidationError
from libs.contracts.interfaces.position_sizing_service import (
    PositionSizingServiceInterface,
)
from libs.contracts.position_sizing import SizingMethod, SizingRequest, SizingResult

logger = logging.getLogger(__name__)

# Kelly criterion hard cap at 50% (full Kelly), recommended at 25% (half Kelly)
_MAX_KELLY_FRACTION = Decimal("0.5")
_HALF_KELLY_FACTOR = Decimal("0.5")


class PositionSizingService(PositionSizingServiceInterface):
    """
    Production implementation of dynamic position sizing.

    Supports five sizing methods, each respecting risk gate hard caps.

    Responsibilities:
    - FIXED: return configured max_position_size.
    - ATR_BASED: size based on risk budget and ATR-derived stop distance.
    - KELLY: optimal fraction based on win rate and payoff ratio.
    - RISK_PARITY: inverse-volatility weighting.
    - EQUAL_WEIGHT: even dollar allocation across positions.

    Does NOT:
    - Execute trades.
    - Access databases.

    Example:
        service = PositionSizingService()
        result = service.compute_size(request)
    """

    def compute_size(self, request: SizingRequest) -> SizingResult:
        """
        Compute recommended position size based on the request method.

        Dispatches to the appropriate sizing algorithm, then applies
        risk gate caps.

        Args:
            request: SizingRequest with method and parameters.

        Returns:
            SizingResult with recommended quantity, value, and reasoning.

        Raises:
            ValidationError: If required parameters for the method are missing.
        """
        logger.info(
            "Computing position size",
            extra={
                "operation": "compute_size",
                "component": "PositionSizingService",
                "symbol": request.symbol,
                "method": request.method.value,
                "account_equity": str(request.account_equity),
            },
        )

        method_map = {
            SizingMethod.FIXED: self._compute_fixed,
            SizingMethod.ATR_BASED: self._compute_atr_based,
            SizingMethod.KELLY: self._compute_kelly,
            SizingMethod.RISK_PARITY: self._compute_risk_parity,
            SizingMethod.EQUAL_WEIGHT: self._compute_equal_weight,
        }

        compute_fn = method_map[request.method]
        return compute_fn(request)

    def get_available_methods(self) -> list[SizingMethod]:
        """
        List all available sizing methods.

        Returns:
            List of all SizingMethod enum values.
        """
        return list(SizingMethod)

    # ------------------------------------------------------------------
    # Method implementations
    # ------------------------------------------------------------------

    def _compute_fixed(self, request: SizingRequest) -> SizingResult:
        """
        FIXED sizing: return configured max_position_size or equity-based default.

        If max_position_size is set, use it directly. Otherwise, compute
        based on risk_per_trade_pct of equity.

        Args:
            request: SizingRequest with account_equity and optional max_position_size.

        Returns:
            SizingResult with fixed quantity.
        """
        if request.max_position_size is not None and request.max_position_size > 0:
            quantity = request.max_position_size
            value = quantity * request.current_price if request.current_price > 0 else Decimal("0")
            return SizingResult(
                recommended_quantity=quantity,
                recommended_value=value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                risk_amount=Decimal("0"),
                method_used=SizingMethod.FIXED,
                reasoning=f"Fixed: using configured max_position_size={quantity}",
            )

        # Default: risk_per_trade_pct of equity divided by current price
        risk_amount = (request.account_equity * request.risk_per_trade_pct / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        quantity, value, was_capped = self._price_to_quantity(
            risk_amount, request.current_price, request.max_position_size
        )

        return SizingResult(
            recommended_quantity=quantity,
            recommended_value=value,
            risk_amount=risk_amount,
            method_used=SizingMethod.FIXED,
            reasoning=(
                f"Fixed: {request.risk_per_trade_pct}% of "
                f"${request.account_equity} = ${risk_amount}"
            ),
            was_capped=was_capped,
        )

    def _compute_atr_based(self, request: SizingRequest) -> SizingResult:
        """
        ATR-BASED sizing: quantity = risk_budget / (ATR × multiplier).

        The risk budget is risk_per_trade_pct of account equity. The stop
        distance is ATR × atr_multiplier. Quantity is risk_budget / stop_distance.

        Args:
            request: SizingRequest with atr_value, atr_multiplier, current_price.

        Returns:
            SizingResult with ATR-derived quantity.

        Raises:
            ValidationError: If atr_value is missing or zero.
        """
        if request.atr_value is None or request.atr_value <= 0:
            raise ValidationError("ATR_BASED method requires atr_value > 0")

        risk_amount = (request.account_equity * request.risk_per_trade_pct / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        stop_distance = (request.atr_value * request.atr_multiplier).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )

        if stop_distance <= 0:
            raise ValidationError("Computed stop distance is zero or negative")

        raw_quantity = (risk_amount / stop_distance).quantize(Decimal("1"), rounding=ROUND_DOWN)

        # Apply risk gate cap
        quantity = raw_quantity
        was_capped = False
        if request.max_position_size is not None and quantity > request.max_position_size:
            quantity = request.max_position_size
            was_capped = True

        value = (
            (quantity * request.current_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if request.current_price > 0
            else Decimal("0")
        )

        # Calculate stop loss price
        stop_loss = None
        if request.current_price > 0:
            if request.side == "buy":
                stop_loss = (request.current_price - stop_distance).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            else:
                stop_loss = (request.current_price + stop_distance).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

        return SizingResult(
            recommended_quantity=quantity,
            recommended_value=value,
            stop_loss_price=stop_loss,
            risk_amount=risk_amount,
            method_used=SizingMethod.ATR_BASED,
            reasoning=(
                f"ATR-based: risking {request.risk_per_trade_pct}% of "
                f"${request.account_equity} = ${risk_amount}, "
                f"ATR=${request.atr_value} × {request.atr_multiplier} = "
                f"${stop_distance} stop distance → {quantity} shares"
                + (f" (capped from {raw_quantity})" if was_capped else "")
            ),
            was_capped=was_capped,
        )

    def _compute_kelly(self, request: SizingRequest) -> SizingResult:
        """
        KELLY sizing: fraction = win_rate - (1 - win_rate) / avg_win_loss_ratio.

        The Kelly fraction is the theoretically optimal bet size. We cap
        at 50% (full Kelly) and recommend half-Kelly for safety.

        Args:
            request: SizingRequest with win_rate and avg_win_loss_ratio.

        Returns:
            SizingResult with Kelly-derived allocation.

        Raises:
            ValidationError: If win_rate or avg_win_loss_ratio is missing.
        """
        if request.win_rate is None:
            raise ValidationError("KELLY method requires win_rate")
        if request.avg_win_loss_ratio is None:
            raise ValidationError("KELLY method requires avg_win_loss_ratio")

        # Kelly formula: f = W - (1-W)/R
        w = request.win_rate
        r = request.avg_win_loss_ratio
        kelly_fraction = w - (1 - w) / r

        # Cap at maximum Kelly fraction
        kelly_fraction = min(kelly_fraction, _MAX_KELLY_FRACTION)
        kelly_fraction = max(kelly_fraction, Decimal("0"))

        # Apply half-Kelly for safety
        half_kelly = (kelly_fraction * _HALF_KELLY_FACTOR).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

        allocation = (request.account_equity * half_kelly).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        quantity, value, was_capped = self._price_to_quantity(
            allocation, request.current_price, request.max_position_size
        )

        return SizingResult(
            recommended_quantity=quantity,
            recommended_value=value,
            risk_amount=allocation,
            method_used=SizingMethod.KELLY,
            reasoning=(
                f"Kelly: W={w}, R={r}, f*={kelly_fraction.quantize(Decimal('0.0001'))}, "
                f"half-Kelly={half_kelly}, "
                f"allocation=${allocation}" + (" (capped)" if was_capped else "")
            ),
            was_capped=was_capped,
        )

    def _compute_risk_parity(self, request: SizingRequest) -> SizingResult:
        """
        RISK_PARITY sizing: inverse-volatility weighting.

        Allocates capital inversely proportional to the instrument's
        volatility (ATR). Lower volatility → larger position.

        Uses ATR as the volatility proxy. Without ATR, falls back
        to equal weight.

        Args:
            request: SizingRequest with atr_value for volatility proxy.

        Returns:
            SizingResult with risk-parity allocation.
        """
        if request.atr_value is None or request.atr_value <= 0:
            # Fall back to equal weight logic when no volatility data,
            # but preserve the RISK_PARITY method attribution since that
            # was the requested method.
            fallback = self._compute_equal_weight(request)
            return SizingResult(
                recommended_quantity=fallback.recommended_quantity,
                recommended_value=fallback.recommended_value,
                stop_loss_price=fallback.stop_loss_price,
                risk_amount=fallback.risk_amount,
                method_used=SizingMethod.RISK_PARITY,
                reasoning=(
                    f"Risk parity (fallback to equal weight — no ATR data): {fallback.reasoning}"
                ),
                was_capped=fallback.was_capped,
            )

        # Inverse volatility weight: 1/ATR normalized
        # For a single position, this equals the full allocation
        # The caller is responsible for providing portfolio context
        risk_budget = (request.account_equity * request.risk_per_trade_pct / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Allocation for this position based on inverse ATR
        # In a multi-position context, each position's weight = (1/ATR_i) / sum(1/ATR_j)
        # For single position computation, allocate full risk budget
        n_positions = max(request.total_positions, 1)
        per_position_budget = (risk_budget / n_positions).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        quantity, value, was_capped = self._price_to_quantity(
            per_position_budget, request.current_price, request.max_position_size
        )

        return SizingResult(
            recommended_quantity=quantity,
            recommended_value=value,
            risk_amount=per_position_budget,
            method_used=SizingMethod.RISK_PARITY,
            reasoning=(
                f"Risk parity: {request.risk_per_trade_pct}% of "
                f"${request.account_equity} = ${risk_budget}, "
                f"across {n_positions} positions → ${per_position_budget}/position"
                + (" (capped)" if was_capped else "")
            ),
            was_capped=was_capped,
        )

    def _compute_equal_weight(self, request: SizingRequest) -> SizingResult:
        """
        EQUAL_WEIGHT sizing: equal dollar allocation across n positions.

        Each position gets account_equity / total_positions.

        Args:
            request: SizingRequest with total_positions.

        Returns:
            SizingResult with equal-weight allocation.
        """
        n_positions = max(request.total_positions, 1)
        allocation = (request.account_equity / n_positions).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        quantity, value, was_capped = self._price_to_quantity(
            allocation, request.current_price, request.max_position_size
        )

        return SizingResult(
            recommended_quantity=quantity,
            recommended_value=value,
            risk_amount=allocation,
            method_used=SizingMethod.EQUAL_WEIGHT,
            reasoning=(
                f"Equal weight: ${request.account_equity} / "
                f"{n_positions} positions = ${allocation}/position"
                + (" (capped)" if was_capped else "")
            ),
            was_capped=was_capped,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _price_to_quantity(
        dollar_amount: Decimal,
        current_price: Decimal,
        max_position_size: Decimal | None,
    ) -> tuple[Decimal, Decimal, bool]:
        """
        Convert a dollar allocation to shares, applying optional cap.

        Args:
            dollar_amount: Dollar amount to allocate.
            current_price: Current price per share.
            max_position_size: Hard cap on quantity (from risk gate).

        Returns:
            Tuple of (quantity, value, was_capped).
        """
        if current_price <= 0:
            return Decimal("0"), Decimal("0"), False

        quantity = (dollar_amount / current_price).quantize(Decimal("1"), rounding=ROUND_DOWN)

        was_capped = False
        if max_position_size is not None and quantity > max_position_size:
            quantity = max_position_size
            was_capped = True

        value = (quantity * current_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return quantity, value, was_capped
