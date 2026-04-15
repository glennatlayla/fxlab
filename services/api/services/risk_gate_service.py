"""
Risk gate service — centralized pre-trade risk checking.

Responsibilities:
- Run ordered risk checks on every order before it reaches a broker adapter.
- Fail-fast: cheapest checks first, stop on first violation.
- Record risk events to an append-only audit trail.
- Manage per-deployment risk limits.

Does NOT:
- Route orders to broker adapters (execution service responsibility).
- Persist data directly (delegates to RiskEventRepositoryInterface).
- Make trading decisions or modify orders.

Dependencies:
- DeploymentRepositoryInterface (injected): risk limits persistence via JSON column.
- RiskEventRepositoryInterface (injected): append-only risk event persistence.
- structlog: structured logging.

Error conditions:
- NotFoundError: deployment not found or has no risk limits configured (get/clear).

Check ordering (cheapest first):
1. order_value — pure arithmetic, no external data needed.
2. position_size — needs current positions for same symbol.
3. concentration — needs positions + account equity.
4. open_orders — needs account pending_orders_count.
5. daily_loss — needs account daily_pnl.

Example:
    service = RiskGateService(deployment_repo=deployment_repo, risk_event_repo=repo)
    service.set_risk_limits(
        deployment_id="01HDEPLOY...",
        limits=PreTradeRiskLimits(max_order_value=Decimal("50000")),
    )
    result = service.check_order(
        deployment_id="01HDEPLOY...",
        order=order_request,
        positions=current_positions,
        account=account_snapshot,
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

from decimal import Decimal

import structlog
import ulid as _ulid_mod

from libs.contracts.errors import NotFoundError
from libs.contracts.execution import (
    AccountSnapshot,
    OrderRequest,
    OrderSide,
    PositionSnapshot,
)
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)
from libs.contracts.interfaces.risk_event_repository_interface import (
    RiskEventRepositoryInterface,
)
from libs.contracts.interfaces.risk_gate_interface import RiskGateInterface
from libs.contracts.risk import (
    PreTradeRiskLimits,
    RiskCheckResult,
    RiskEvent,
    RiskEventSeverity,
)

logger = structlog.get_logger(__name__)


class RiskGateService(RiskGateInterface):
    """
    Production implementation of the pre-trade risk gate.

    Responsibilities:
    - Persist per-deployment risk limits to durable storage via DeploymentRepository.
    - Run ordered checks (cheapest first, fail-fast) on each order.
    - Record every check result as a RiskEvent in the audit trail.

    Does NOT:
    - Route orders or interact with broker adapters.
    - Make trading decisions or modify orders.

    Dependencies:
    - DeploymentRepositoryInterface (injected): for risk limits persistence.
    - RiskEventRepositoryInterface (injected): for event persistence.
    - structlog: for structured logging.

    Example:
        service = RiskGateService(
            deployment_repo=deployment_repo,
            risk_event_repo=repo,
        )
        service.set_risk_limits(deployment_id="dep-001", limits=limits)
        result = service.check_order(
            deployment_id="dep-001",
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-001",
        )
    """

    def __init__(
        self,
        *,
        deployment_repo: DeploymentRepositoryInterface,
        risk_event_repo: RiskEventRepositoryInterface,
    ) -> None:
        """
        Initialise the risk gate service.

        Args:
            deployment_repo: Repository for deployment lookups and risk limits persistence.
            risk_event_repo: Repository for persisting risk events.
        """
        self._deployment_repo = deployment_repo
        self._risk_event_repo = risk_event_repo

    # ------------------------------------------------------------------
    # Risk limits management
    # ------------------------------------------------------------------

    def set_risk_limits(
        self,
        *,
        deployment_id: str,
        limits: PreTradeRiskLimits,
    ) -> None:
        """
        Configure risk limits for a deployment.

        Persists the limits to the deployment record's risk_limits JSON
        column via DeploymentRepository, ensuring they survive process
        restarts.

        Args:
            deployment_id: ULID of the deployment.
            limits: Risk limits to apply.

        Raises:
            NotFoundError: deployment does not exist.
        """
        # Serialize PreTradeRiskLimits to a dict for JSON persistence.
        limits_dict = {
            "max_order_value": str(limits.max_order_value),
            "max_position_size": str(limits.max_position_size),
            "max_daily_loss": str(limits.max_daily_loss),
            "max_concentration_pct": str(limits.max_concentration_pct),
            "max_open_orders": limits.max_open_orders,
        }
        self._deployment_repo.update_risk_limits(
            deployment_id=deployment_id,
            risk_limits=limits_dict,
        )
        logger.info(
            "risk_limits_set",
            deployment_id=deployment_id,
            max_position_size=str(limits.max_position_size),
            max_daily_loss=str(limits.max_daily_loss),
            max_order_value=str(limits.max_order_value),
            max_concentration_pct=str(limits.max_concentration_pct),
            max_open_orders=limits.max_open_orders,
        )

    def get_risk_limits(
        self,
        *,
        deployment_id: str,
    ) -> PreTradeRiskLimits:
        """
        Get current risk limits for a deployment.

        Reads from the deployment record's risk_limits JSON column
        via DeploymentRepository.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            PreTradeRiskLimits for the deployment.

        Raises:
            NotFoundError: deployment not found or has no risk limits configured.
        """
        deployment = self._deployment_repo.get_by_id(deployment_id)
        if deployment is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")
        limits_dict = deployment.get("risk_limits", {})
        if not limits_dict:
            raise NotFoundError(f"No risk limits configured for deployment {deployment_id}")
        return self._deserialize_limits(limits_dict)

    def clear_risk_limits(
        self,
        *,
        deployment_id: str,
    ) -> None:
        """
        Remove risk limits for a deployment.

        Writes an empty dict to the deployment's risk_limits column.

        Args:
            deployment_id: ULID of the deployment.

        Raises:
            NotFoundError: deployment not found or has no risk limits configured.
        """
        deployment = self._deployment_repo.get_by_id(deployment_id)
        if deployment is None:
            raise NotFoundError(f"Deployment {deployment_id} not found")
        limits_dict = deployment.get("risk_limits", {})
        if not limits_dict:
            raise NotFoundError(f"No risk limits configured for deployment {deployment_id}")
        self._deployment_repo.update_risk_limits(
            deployment_id=deployment_id,
            risk_limits={},
        )
        logger.info("risk_limits_cleared", deployment_id=deployment_id)

    def get_risk_events(
        self,
        *,
        deployment_id: str,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[RiskEvent]:
        """
        Get risk events for a deployment.

        Args:
            deployment_id: ULID of the deployment.
            severity: Optional filter by severity level.
            limit: Maximum number of events to return.

        Returns:
            List of RiskEvent objects, most recent first.
        """
        return self._risk_event_repo.list_by_deployment(
            deployment_id=deployment_id,
            severity=severity,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Core check_order — fail-fast ordered checks
    # ------------------------------------------------------------------

    def check_order(
        self,
        *,
        deployment_id: str,
        order: OrderRequest,
        positions: list[PositionSnapshot],
        account: AccountSnapshot,
        correlation_id: str,
    ) -> RiskCheckResult:
        """
        Run all pre-trade risk checks on an order.

        Checks are ordered cheapest-first, fail-fast on first violation.

        Order:
        1. order_value — max notional value per order.
        2. position_size — max position size per symbol.
        3. concentration — max portfolio concentration in single symbol.
        4. open_orders — max open order count.
        5. daily_loss — max daily loss threshold.

        Args:
            deployment_id: ULID of the deployment.
            order: The order to validate.
            positions: Current positions for the deployment.
            account: Current account snapshot.
            correlation_id: Distributed tracing ID.

        Returns:
            RiskCheckResult — passed=True if all checks pass,
            or the first failing check result.
        """
        # Read risk limits from the deployment record (durable storage).
        deployment = self._deployment_repo.get_by_id(deployment_id)
        if deployment is None:
            # Deployment not found — fail-closed
            logger.warning(
                "risk_gate_deployment_not_found",
                deployment_id=deployment_id,
                order_id=order.client_order_id,
            )
            result = RiskCheckResult(
                passed=False,
                check_name="no_limits_configured",
                severity=RiskEventSeverity.CRITICAL,
                reason=f"Deployment {deployment_id} not found. Cannot process order without deployment context.",
            )
            self._record_event(
                deployment_id=deployment_id,
                result=result,
                order=order,
                correlation_id=correlation_id,
            )
            return result

        limits_dict = deployment.get("risk_limits", {})
        if not limits_dict:
            # No limits configured — fail-closed for live, pass-through for paper/shadow
            execution_mode = deployment.get("execution_mode", "paper")

            if execution_mode == "live":
                # Live mode without risk limits is a critical safety violation
                logger.warning(
                    "risk_gate_no_limits_live",
                    deployment_id=deployment_id,
                    order_id=order.client_order_id,
                    execution_mode=execution_mode,
                )
                result = RiskCheckResult(
                    passed=False,
                    check_name="no_limits_configured",
                    severity=RiskEventSeverity.CRITICAL,
                    reason=f"Risk limits not configured for live deployment {deployment_id}. Configure limits before submitting live orders.",
                )
                self._record_event(
                    deployment_id=deployment_id,
                    result=result,
                    order=order,
                    correlation_id=correlation_id,
                )
                return result

            # Paper/shadow mode without limits is acceptable — backward compatible
            logger.debug(
                "risk_gate_no_limits_paper_shadow",
                deployment_id=deployment_id,
                order_id=order.client_order_id,
                execution_mode=execution_mode,
            )
            result = RiskCheckResult(
                passed=True,
                check_name="no_limits_configured",
                severity=RiskEventSeverity.INFO,
            )
            self._record_event(
                deployment_id=deployment_id,
                result=result,
                order=order,
                correlation_id=correlation_id,
            )
            return result
        limits = self._deserialize_limits(limits_dict)

        # Build position lookup for the order's symbol
        symbol_position = self._find_position(order.symbol, positions)

        # Estimate order market price from positions or default
        market_price = self._estimate_market_price(order.symbol, positions)

        # Ordered checks — fail-fast
        checks = [
            lambda: self._check_order_value(order, market_price, limits),
            lambda: self._check_position_size(order, symbol_position, limits),
            lambda: self._check_concentration(
                order, market_price, symbol_position, account, limits
            ),
            lambda: self._check_open_orders(account, limits),
            lambda: self._check_daily_loss(account, limits),
        ]

        for check_fn in checks:
            result = check_fn()
            self._record_event(
                deployment_id=deployment_id,
                result=result,
                order=order,
                correlation_id=correlation_id,
            )

            # Emit Prometheus metric for each risk gate evaluation.
            try:
                from services.api.metrics import RISK_GATE_CHECKS_TOTAL

                RISK_GATE_CHECKS_TOTAL.labels(
                    check_name=result.check_name,
                    result="pass" if result.passed else "fail",
                ).inc()
            except ImportError:
                pass

            if not result.passed:
                logger.warning(
                    "risk_gate_check_failed",
                    deployment_id=deployment_id,
                    check_name=result.check_name,
                    reason=result.reason,
                    order_id=order.client_order_id,
                    correlation_id=correlation_id,
                )
                return result

        # All checks passed
        all_passed = RiskCheckResult(
            passed=True,
            check_name="all_checks_passed",
            severity=RiskEventSeverity.INFO,
        )
        logger.info(
            "risk_gate_all_checks_passed",
            deployment_id=deployment_id,
            order_id=order.client_order_id,
            correlation_id=correlation_id,
        )
        return all_passed

    def enforce_order(
        self,
        *,
        deployment_id: str,
        order: OrderRequest,
        positions: list[PositionSnapshot],
        account: AccountSnapshot,
        correlation_id: str,
    ) -> None:
        """
        Enforce pre-trade risk checks — raise on failure, return silently on success.

        Calls check_order() internally (which persists events for both pass
        and fail outcomes), then raises RiskGateRejectionError if the order
        fails any risk check. This makes it structurally impossible to
        accidentally skip or ignore a failing risk check.

        Args:
            deployment_id: ULID of the deployment.
            order: The order to validate.
            positions: Current positions for the deployment.
            account: Current account snapshot.
            correlation_id: Distributed tracing ID.

        Raises:
            RiskGateRejectionError: risk check failed — order MUST NOT be
                submitted to any broker adapter.

        Example:
            risk_gate.enforce_order(
                deployment_id="dep-001",
                order=order,
                positions=positions,
                account=account,
                correlation_id="corr-001",
            )
            # If we reach here, risk checks passed — safe to submit order.
        """
        from libs.contracts.errors import RiskGateRejectionError

        result = self.check_order(
            deployment_id=deployment_id,
            order=order,
            positions=positions,
            account=account,
            correlation_id=correlation_id,
        )

        if not result.passed:
            raise RiskGateRejectionError(
                f"Risk gate rejected order {order.client_order_id}: "
                f"{result.check_name} — {result.reason}",
                check_name=result.check_name,
                severity=result.severity.value
                if hasattr(result.severity, "value")
                else str(result.severity),
                reason=result.reason or "",
                deployment_id=deployment_id,
                order_client_id=order.client_order_id,
                current_value=result.current_value or "",
                limit_value=result.limit_value or "",
            )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_order_value(
        self,
        order: OrderRequest,
        market_price: Decimal,
        limits: PreTradeRiskLimits,
    ) -> RiskCheckResult:
        """
        Check order notional value against limit.

        Args:
            order: The order being checked.
            market_price: Estimated market price for the symbol.
            limits: Applicable risk limits.

        Returns:
            RiskCheckResult for order_value check.
        """
        if limits.max_order_value == Decimal("0"):
            return RiskCheckResult(
                passed=True, check_name="order_value", severity=RiskEventSeverity.INFO
            )

        order_value = order.quantity * market_price
        if order_value > limits.max_order_value:
            return RiskCheckResult(
                passed=False,
                check_name="order_value",
                reason=(f"Order value {order_value} exceeds limit {limits.max_order_value}"),
                severity=RiskEventSeverity.CRITICAL,
                current_value=str(order_value),
                limit_value=str(limits.max_order_value),
            )
        return RiskCheckResult(
            passed=True,
            check_name="order_value",
            severity=RiskEventSeverity.INFO,
            current_value=str(order_value),
            limit_value=str(limits.max_order_value),
        )

    def _check_position_size(
        self,
        order: OrderRequest,
        symbol_position: PositionSnapshot | None,
        limits: PreTradeRiskLimits,
    ) -> RiskCheckResult:
        """
        Check resulting position size against limit.

        Args:
            order: The order being checked.
            symbol_position: Current position for the symbol (or None).
            limits: Applicable risk limits.

        Returns:
            RiskCheckResult for position_size check.
        """
        if limits.max_position_size == Decimal("0"):
            return RiskCheckResult(
                passed=True, check_name="position_size", severity=RiskEventSeverity.INFO
            )

        current_qty = symbol_position.quantity if symbol_position else Decimal("0")
        order_qty = order.quantity if order.side == OrderSide.BUY else -order.quantity
        resulting_qty = abs(current_qty + order_qty)

        if resulting_qty > limits.max_position_size:
            return RiskCheckResult(
                passed=False,
                check_name="position_size",
                reason=(
                    f"Resulting position size {resulting_qty} exceeds "
                    f"limit {limits.max_position_size}"
                ),
                severity=RiskEventSeverity.CRITICAL,
                current_value=str(resulting_qty),
                limit_value=str(limits.max_position_size),
            )
        return RiskCheckResult(
            passed=True,
            check_name="position_size",
            severity=RiskEventSeverity.INFO,
            current_value=str(resulting_qty),
            limit_value=str(limits.max_position_size),
        )

    def _check_concentration(
        self,
        order: OrderRequest,
        market_price: Decimal,
        symbol_position: PositionSnapshot | None,
        account: AccountSnapshot,
        limits: PreTradeRiskLimits,
    ) -> RiskCheckResult:
        """
        Check portfolio concentration in a single symbol against limit.

        Args:
            order: The order being checked.
            market_price: Estimated market price for the symbol.
            symbol_position: Current position for the symbol (or None).
            account: Current account snapshot.
            limits: Applicable risk limits.

        Returns:
            RiskCheckResult for concentration check.
        """
        if limits.max_concentration_pct == Decimal("0"):
            return RiskCheckResult(
                passed=True, check_name="concentration", severity=RiskEventSeverity.INFO
            )

        if account.equity <= Decimal("0"):
            return RiskCheckResult(
                passed=True, check_name="concentration", severity=RiskEventSeverity.INFO
            )

        # Current position value + order value
        current_value = Decimal("0")
        if symbol_position:
            current_value = abs(symbol_position.quantity) * market_price
        order_value = order.quantity * market_price

        if order.side == OrderSide.BUY:
            total_exposure = current_value + order_value
        else:
            # Selling reduces exposure
            total_exposure = abs(current_value - order_value)

        concentration_pct = (total_exposure / account.equity) * Decimal("100")

        if concentration_pct > limits.max_concentration_pct:
            return RiskCheckResult(
                passed=False,
                check_name="concentration",
                reason=(
                    f"Concentration {concentration_pct:.2f}% exceeds "
                    f"limit {limits.max_concentration_pct}%"
                ),
                severity=RiskEventSeverity.CRITICAL,
                current_value=str(concentration_pct.quantize(Decimal("0.01"))),
                limit_value=str(limits.max_concentration_pct),
            )
        return RiskCheckResult(
            passed=True,
            check_name="concentration",
            severity=RiskEventSeverity.INFO,
            current_value=str(concentration_pct.quantize(Decimal("0.01"))),
            limit_value=str(limits.max_concentration_pct),
        )

    def _check_open_orders(
        self,
        account: AccountSnapshot,
        limits: PreTradeRiskLimits,
    ) -> RiskCheckResult:
        """
        Check open order count against limit.

        Args:
            account: Current account snapshot.
            limits: Applicable risk limits.

        Returns:
            RiskCheckResult for open_orders check.
        """
        if limits.max_open_orders == 0:
            return RiskCheckResult(
                passed=True, check_name="open_orders", severity=RiskEventSeverity.INFO
            )

        # +1 for the order being submitted
        total = account.pending_orders_count + 1
        if total > limits.max_open_orders:
            return RiskCheckResult(
                passed=False,
                check_name="open_orders",
                reason=(
                    f"Open orders {total} (including new) exceeds limit {limits.max_open_orders}"
                ),
                severity=RiskEventSeverity.CRITICAL,
                current_value=str(total),
                limit_value=str(limits.max_open_orders),
            )
        return RiskCheckResult(
            passed=True,
            check_name="open_orders",
            severity=RiskEventSeverity.INFO,
            current_value=str(total),
            limit_value=str(limits.max_open_orders),
        )

    def _check_daily_loss(
        self,
        account: AccountSnapshot,
        limits: PreTradeRiskLimits,
    ) -> RiskCheckResult:
        """
        Check daily loss against limit.

        Args:
            account: Current account snapshot.
            limits: Applicable risk limits.

        Returns:
            RiskCheckResult for daily_loss check.
        """
        if limits.max_daily_loss == Decimal("0"):
            return RiskCheckResult(
                passed=True, check_name="daily_loss", severity=RiskEventSeverity.INFO
            )

        # daily_pnl is negative for losses; max_daily_loss is positive
        if account.daily_pnl < Decimal("0") and abs(account.daily_pnl) > limits.max_daily_loss:
            return RiskCheckResult(
                passed=False,
                check_name="daily_loss",
                reason=(
                    f"Daily loss {abs(account.daily_pnl)} exceeds limit {limits.max_daily_loss}"
                ),
                severity=RiskEventSeverity.CRITICAL,
                current_value=str(abs(account.daily_pnl)),
                limit_value=str(limits.max_daily_loss),
            )
        return RiskCheckResult(
            passed=True,
            check_name="daily_loss",
            severity=RiskEventSeverity.INFO,
            current_value=str(abs(account.daily_pnl)),
            limit_value=str(limits.max_daily_loss),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_position(
        self,
        symbol: str,
        positions: list[PositionSnapshot],
    ) -> PositionSnapshot | None:
        """
        Find the position for a given symbol.

        Args:
            symbol: Instrument ticker.
            positions: Current positions.

        Returns:
            PositionSnapshot or None if not found.
        """
        for pos in positions:
            if pos.symbol == symbol:
                return pos
        return None

    def _estimate_market_price(
        self,
        symbol: str,
        positions: list[PositionSnapshot],
    ) -> Decimal:
        """
        Estimate market price for a symbol from positions.

        Uses the position's market_price if available, otherwise
        falls back to the average_entry_price. If no position exists,
        returns a default of 1 (safe for zero-limit bypass scenarios).

        Args:
            symbol: Instrument ticker.
            positions: Current positions.

        Returns:
            Estimated market price.
        """
        for pos in positions:
            if pos.symbol == symbol:
                return pos.market_price
        return Decimal("1")

    @staticmethod
    def _deserialize_limits(limits_dict: dict) -> PreTradeRiskLimits:
        """
        Deserialize a risk limits dict from the deployment record to PreTradeRiskLimits.

        Args:
            limits_dict: Dict from deployment.risk_limits JSON column.

        Returns:
            PreTradeRiskLimits instance.
        """
        return PreTradeRiskLimits(
            max_order_value=Decimal(str(limits_dict.get("max_order_value", "0"))),
            max_position_size=Decimal(str(limits_dict.get("max_position_size", "0"))),
            max_daily_loss=Decimal(str(limits_dict.get("max_daily_loss", "0"))),
            max_concentration_pct=Decimal(str(limits_dict.get("max_concentration_pct", "0"))),
            max_open_orders=int(limits_dict.get("max_open_orders", 0)),
        )

    def _record_event(
        self,
        *,
        deployment_id: str,
        result: RiskCheckResult,
        order: OrderRequest,
        correlation_id: str,
    ) -> None:
        """
        Record a risk check result as a RiskEvent.

        Args:
            deployment_id: ULID of the deployment.
            result: The check result to record.
            order: The order being checked.
            correlation_id: Distributed tracing ID.
        """
        event = RiskEvent(
            event_id=str(_ulid_mod.ULID()),
            deployment_id=deployment_id,
            check_name=result.check_name,
            severity=result.severity,
            passed=result.passed,
            reason=result.reason,
            current_value=result.current_value,
            limit_value=result.limit_value,
            order_client_id=order.client_order_id,
            symbol=order.symbol,
            correlation_id=correlation_id,
        )
        self._risk_event_repo.save(event)
